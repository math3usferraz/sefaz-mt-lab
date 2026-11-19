"""Coleta mensal de NF-e por empresa, com checkpoint retomavel.

O CSV de entrada tem as colunas cnpj e ie, ambas textuais. Este programa nao
consulta o Meu Danfe. Os dados de cada execucao permanecem em saida/coletas.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

RAIZ = Path(__file__).resolve().parent


def carregar_empresas(arquivo: Path) -> list[dict[str, str]]:
    texto = arquivo.read_text(encoding='utf-8-sig')
    try:
        dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=';,')
    except csv.Error:
        raise ValueError('CSV deve usar ponto e virgula ou virgula como separador.') from None
    leitor = csv.DictReader(texto.splitlines(), dialect=dialeto)
    if leitor.fieldnames is None:
        raise ValueError('CSV sem cabecalho.')
    leitor.fieldnames = [x.strip().lower() for x in leitor.fieldnames]
    if not {'cnpj', 'ie'} <= set(leitor.fieldnames):
        raise ValueError('CSV precisa das colunas cnpj e ie.')
    empresas = []
    vistos = set()
    for n, linha in enumerate(leitor, 2):
        cnpj_bruto, ie_bruta = linha.get('cnpj') or '', linha.get('ie') or ''
        if not re.fullmatch(r'[\d.\-/\s]+', cnpj_bruto) or not re.fullmatch(r'[\d.\-/\s]+', ie_bruta):
            raise ValueError(f'CNPJ ou IE invalido na linha {n}.')
        cnpj = re.sub(r'\D', '', cnpj_bruto)
        ie = re.sub(r'\D', '', ie_bruta)
        if not re.fullmatch(r'\d{14}', cnpj) or not re.fullmatch(r'\d{9}', ie):
            raise ValueError(f'CNPJ deve ter 14 digitos e IE 9 digitos na linha {n}.')
        if cnpj in vistos:
            raise ValueError(f'CNPJ duplicado na linha {n}; confira a lista.')
        vistos.add(cnpj)
        empresas.append({'cnpj': cnpj, 'ie': ie})
    if not empresas:
        raise ValueError('CSV nao contem empresas.')
    return empresas


def salvar_checkpoint(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix('.tmp')
    with temporario.open('w', encoding='utf-8') as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(temporario, caminho)


def preparar_checkpoint(caminho: Path, empresas: list[dict], inicio: str, fim: str) -> dict:
    try:
        dt_inicio, dt_fim = datetime.strptime(inicio, '%d/%m/%Y'), datetime.strptime(fim, '%d/%m/%Y')
    except ValueError:
        raise ValueError('Datas devem estar em DD/MM/AAAA.') from None
    if dt_inicio > dt_fim or (dt_inicio.year, dt_inicio.month) != (dt_fim.year, dt_fim.month):
        raise ValueError('O periodo deve estar dentro da mesma competencia.')
    if caminho.exists():
        dados = json.loads(caminho.read_text(encoding='utf-8'))
        if dados.get('inicio') != inicio or dados.get('fim') != fim:
            raise ValueError('O checkpoint pertence a outro periodo.')
        empresas_anteriores = [(x['cnpj'], x['ie']) for x in dados.get('empresas', [])]
        if empresas_anteriores != [(x['cnpj'], x['ie']) for x in empresas]:
            raise ValueError('A lista ou ordem das empresas difere do checkpoint.')
        return dados
    return {'versao': 1, 'inicio': inicio, 'fim': fim,
            'empresas': [{**e, 'status': 'PENDENTE', 'tentativas': 0} for e in empresas]}


def _pastas_existentes(pasta: Path) -> set[str]:
    return {p.name for p in pasta.iterdir() if p.is_dir()} if pasta.exists() else set()


def _relatorio_novo(pasta: Path, anteriores: set[str], inicio: str, fim: str) -> dict | None:
    novos = [p for p in pasta.iterdir() if p.is_dir() and p.name not in anteriores] if pasta.exists() else []
    if len(novos) != 1:
        return None
    arquivo = novos[0] / 'relatorio.json'
    try:
        relatorio = json.loads(arquivo.read_text(encoding='utf-8'))
        dt_inicio = datetime.strptime(inicio, '%d/%m/%Y').date().isoformat()
        dt_fim = datetime.strptime(fim, '%d/%m/%Y').date().isoformat()
        if relatorio['status'] != 'CONCLUIDO':
            return None
        for tipo in ('recebidas', 'emitidas'):
            dados = relatorio['tipos'][tipo]
            if dados['periodo_inicial'] != dt_inicio or dados['periodo_final'] != dt_fim:
                return None
            if not (novos[0] / tipo / dados['csv_chaves']).is_file():
                return None
        return {'coleta': str(novos[0]),
                'recebidas': relatorio['tipos']['recebidas']['chaves_unicas'],
                'emitidas': relatorio['tipos']['emitidas']['chaves_unicas']}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _encerrar_processo(processo: subprocess.Popen) -> None:
    if os.name == 'nt':
        # O PID e o processo filho que acabamos de criar, nao uma busca por nome.
        subprocess.run(['taskkill', '/PID', str(processo.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        processo.kill()
    try:
        processo.wait(timeout=15)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait()


def executar_empresa(empresa: dict, inicio: str, fim: str, porta: int,
                     tempo_limite: int, tentativas_login: int, tentativas_certificado: int) -> dict:
    competencia = datetime.strptime(inicio, '%d/%m/%Y').strftime('%Y-%m')
    pasta = RAIZ / 'saida' / 'coletas' / empresa['cnpj'] / competencia
    anteriores = _pastas_existentes(pasta)
    comando = [sys.executable, str(RAIZ / 'coletar_nfe.py'), '--cnpj', empresa['cnpj'],
               '--ie', empresa['ie'], '--inicio', inicio, '--fim', fim, '--tipo', 'ambas',
               '--porta', str(porta), '--tentativas-login', str(tentativas_login),
               '--tentativas-certificado', str(tentativas_certificado)]
    # Herda o terminal para que o operador veja, em tempo real, mensagens
    # como a necessidade de resolver manualmente um desafio do Cloudflare.
    processo = subprocess.Popen(comando, cwd=str(RAIZ))
    try:
        processo.communicate(timeout=tempo_limite)
    except subprocess.TimeoutExpired:
        _encerrar_processo(processo)
        return {'status': 'TEMPO_ESGOTADO'}
    relatorio = _relatorio_novo(pasta, anteriores, inicio, fim)
    if processo.returncode == 0 and relatorio is not None:
        return {'status': 'CONCLUIDO', **relatorio}
    return {'status': 'FALHA', 'codigo_saida': processo.returncode}


def executar_lote(dados: dict, checkpoint: Path, executar=executar_empresa, *,
                  porta: int = 9331, tempo_limite: int = 900,
                  tentativas_login: int = 15, tentativas_certificado: int = 6) -> dict:
    for i, empresa in enumerate(dados['empresas'], 1):
        if empresa['status'] == 'CONCLUIDO':
            continue
        if empresa['status'] == 'EM_ANDAMENTO':
            # Uma interrupcao abrupta nao prova que a execucao anterior parou.
            empresa['status'] = 'INTERROMPIDO_VERIFICAR'
            salvar_checkpoint(checkpoint, dados)
            continue
        if empresa['status'] == 'INTERROMPIDO_VERIFICAR':
            continue
        empresa['status'] = 'EM_ANDAMENTO'
        empresa['tentativas'] += 1
        empresa['atualizado_em'] = datetime.now(timezone.utc).isoformat()
        salvar_checkpoint(checkpoint, dados)
        print(f'Empresa {i}/{len(dados["empresas"])}: iniciando coleta.', flush=True)
        try:
            resultado = executar(empresa, dados['inicio'], dados['fim'], porta, tempo_limite,
                                 tentativas_login, tentativas_certificado)
        except (OSError, ValueError):
            resultado = {'status': 'FALHA_INICIAR'}
        empresa.update(resultado)
        empresa['atualizado_em'] = datetime.now(timezone.utc).isoformat()
        salvar_checkpoint(checkpoint, dados)
        print(f'Empresa {i}/{len(dados["empresas"])}: {empresa["status"]}.', flush=True)
    return dados


def main() -> int:
    cli = argparse.ArgumentParser(description='Coleta NF-e de varias empresas, uma de cada vez.')
    cli.add_argument('--empresas', type=Path, required=True, help='CSV com colunas cnpj;ie')
    cli.add_argument('--inicio', required=True, help='DD/MM/AAAA')
    cli.add_argument('--fim', required=True, help='DD/MM/AAAA')
    cli.add_argument('--porta', type=int, default=9331)
    cli.add_argument('--tempo-limite-empresa', type=int, default=900)
    cli.add_argument('--tentativas-login', type=int, default=15)
    cli.add_argument('--tentativas-certificado', type=int, default=6)
    args = cli.parse_args()
    if not 1 <= args.porta <= 65535 or min(args.tempo_limite_empresa, args.tentativas_login,
                                           args.tentativas_certificado) < 1:
        cli.error('Porta, tempo e tentativas devem ser positivos.')
    try:
        empresas = carregar_empresas(args.empresas)
        # Identifica o lote por lista normalizada e periodo; caminho do CSV nao e gravado.
        identidade = json.dumps([args.inicio, args.fim, empresas], ensure_ascii=True, sort_keys=True)
        identificador = hashlib.sha256(identidade.encode('utf-8')).hexdigest()[:20]
        checkpoint = RAIZ / 'saida' / 'lotes' / identificador / 'checkpoint.json'
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        # Exclusao mutua garante que dois operadores nao executem o mesmo lote.
        # A porta do navegador e o dialogo de certificado sao recursos da
        # maquina, compartilhados inclusive por lotes com listas distintas.
        trava = RAIZ / 'saida' / 'lotes' / 'execucao.lock'
        with trava.open('x', encoding='utf-8') as arquivo:
            arquivo.write(str(os.getpid()))
        try:
            dados = preparar_checkpoint(checkpoint, empresas, args.inicio, args.fim)
            salvar_checkpoint(checkpoint, dados)
            executar_lote(dados, checkpoint, porta=args.porta,
                          tempo_limite=args.tempo_limite_empresa,
                          tentativas_login=args.tentativas_login,
                          tentativas_certificado=args.tentativas_certificado)
        finally:
            trava.unlink(missing_ok=True)
        concluidas = sum(e['status'] == 'CONCLUIDO' for e in dados['empresas'])
        print(f'Concluidas: {concluidas}/{len(empresas)}. Checkpoint: {checkpoint}')
        return 0 if concluidas == len(empresas) else 1
    except FileExistsError:
        print('Lote em execucao ou bloqueio anterior presente; confira execucao.lock.', file=sys.stderr)
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Falha no lote: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
