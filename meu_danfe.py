"""Prova controlada de recuperação de uma NF-e 55 pela API v2 do Meu Danfe.

Contrato: https://meudanfe.com.br/doc/v2.php (Swagger oficial).
Nenhuma busca cobrada ocorre sem --autorizar-consulta-paga.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from extrair_chaves import chave_valida, extrair_do_arquivo
from validar_xml import validar_nfe_completa


RAIZ = Path(__file__).resolve().parent
BASE_URL = 'https://api.meudanfe.com.br/v2'
LIMITE_RESPOSTA = 25 * 1024 * 1024


def ler_api_key(arquivo_env: Path) -> str:
    if os.environ.get('MEUDANFE_API_KEY'):
        return os.environ['MEUDANFE_API_KEY'].strip()
    if not arquivo_env.is_file():
        return ''
    for linha in arquivo_env.read_text(encoding='utf-8-sig').splitlines():
        if linha.strip().startswith('#') or '=' not in linha:
            continue
        nome, valor = linha.split('=', 1)
        if nome.strip() == 'MEUDANFE_API_KEY':
            return valor.strip().strip('"\'')
    return ''


def escolher_chave(chave: str | None, planilha: Path | None, indice: int = 0) -> str:
    if bool(chave) == bool(planilha):
        raise ValueError('Informe exatamente uma opção: --chave ou --planilha')
    if indice < 0 or (chave and indice != 0):
        raise ValueError('--indice-chave deve ser não negativo e usado somente com --planilha')
    if planilha:
        chaves, _ = extrair_do_arquivo(planilha)
        candidatas = [c for c in chaves if c[20:22] == '55']
        if not candidatas:
            raise ValueError('Planilha sem chave válida de NF-e modelo 55')
        if indice >= len(candidatas):
            raise ValueError(f'Índice fora da lista de {len(candidatas)} chaves NF-e válidas')
        return candidatas[indice]
    if not chave_valida(chave) or chave[20:22] != '55':
        raise ValueError('Chave inválida ou não é NF-e modelo 55')
    return chave


def requisitar(metodo: str, rota: str, api_key: str) -> tuple[int, dict | None]:
    """Devolve apenas JSON; nunca expõe corpo fiscal ou a API-Key em erros."""
    request = Request(BASE_URL + rota, method=metodo, headers={
        'Api-Key': api_key, 'Accept': 'application/json',
    })
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read(LIMITE_RESPOSTA + 1)
    except HTTPError as erro:
        status = erro.code
        raw = erro.read(LIMITE_RESPOSTA + 1)
    except (URLError, TimeoutError, OSError) as erro:
        raise RuntimeError(f'Falha de transporte: {type(erro).__name__}') from None
    if len(raw) > LIMITE_RESPOSTA:
        raise RuntimeError('Resposta maior que o limite permitido')
    try:
        obj = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None
    return status, obj if isinstance(obj, dict) else None


def bytes_xml(data: str) -> bytes:
    """Preserva o texto XML retornado no campo JSON data, sem reformatá-lo."""
    inicio = data[:150]
    match = re.match(r'\s*<\?xml\s+[^?]*encoding=["\']([A-Za-z0-9._-]+)["\']', inicio, re.I)
    encoding = match.group(1) if match else 'utf-8'
    try:
        return data.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        raise ValueError('Codificação XML declarada não pode ser preservada') from None


def gravar_json(destino: Path, dados: dict) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix('.tmp')
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
    temporario.replace(destino)


def executar(chave: str, api_key: str, raiz_saida: Path, cnpj: str,
             tipo: str, autorizar_consulta_paga: bool, pausa=time.sleep,
             request=requisitar, origem: str = 'chave_informada') -> dict:
    if not chave_valida(chave) or chave[20:22] != '55':
        raise ValueError('Apenas uma chave NF-e modelo 55 válida é aceita')
    if not api_key:
        raise ValueError('MEUDANFE_API_KEY ausente do ambiente e do .env')
    if not re.fullmatch(r'\d{14}', cnpj):
        raise ValueError('CNPJ da empresa deve ter 14 dígitos')
    if tipo not in ('emitidas', 'recebidas'):
        raise ValueError('Tipo de operação inválido')
    ano, mes = '20' + chave[2:4], chave[4:6]
    destino = raiz_saida / cnpj / ano / mes / f'nfe_{tipo}' / f'{chave}.xml'
    destino_dados = raiz_saida / cnpj / ano / mes / f'nfe_{tipo}_dados_meudanfe' / f'{chave}.xml'
    historico = raiz_saida / 'historico' / f'{chave}.json'
    anterior = json.loads(historico.read_text(encoding='utf-8')) if historico.exists() else {}
    resultado = {'chave': chave, 'cnpj_empresa': cnpj, 'tipo': tipo,
                 'origem': origem,
                 'registrado_em': datetime.now(timezone.utc).isoformat(),
                 'status': 'CONSULTA_PENDENTE', 'xml': None,
                 'busca_paga_potencialmente_enviada': anterior.get('busca_paga_potencialmente_enviada', False),
                 'busca_paga_nova_potencialmente_enviada': False,
                 'assinatura_verificada': False}

    def registrar(status: str, **extras) -> dict:
        resultado.update(status=status, **extras)
        gravar_json(historico, resultado)
        return resultado

    if destino.exists():
        xml = destino.read_bytes()
        validacao = validar_nfe_completa(xml, chave, cnpj_empresa=cnpj, tipo=tipo)
        if validacao.status == 'VALIDO_ESTRUTURAL':
            return registrar('JA_EXISTE_XML', xml=str(destino), sha256=hashlib.sha256(xml).hexdigest(),
                             assinatura_presente=validacao.assinatura_presente)
        return registrar('XML_LOCAL_INVALIDO', validacao=validacao.status)
    if destino_dados.exists():
        xml = destino_dados.read_bytes()
        validacao = validar_nfe_completa(xml, chave, cnpj_empresa=cnpj, tipo=tipo)
        if validacao.status == 'DADOS_FISCAIS_CONFERIDOS':
            return registrar('JA_EXISTEM_DADOS_FISCAIS', xml=str(destino_dados),
                             sha256=hashlib.sha256(xml).hexdigest(),
                             assinatura_presente=validacao.assinatura_presente,
                             estrutura_transformada=validacao.estrutura_transformada)
        return registrar('XML_LOCAL_INVALIDO', validacao=validacao.status)

    def baixar() -> tuple[int, dict | None]:
        return request('GET', f'/fd/get/xml/{chave}', api_key)

    def tratar_download(status_http: int, corpo: dict | None) -> dict:
        if status_http != 200:
            if status_http == 404:
                return registrar('XML_INDISPONIVEL')
            return registrar('FALHA_API', http_status=status_http)
        if not corpo or corpo.get('type') != 'NFE' or corpo.get('format') != 'XML' or not isinstance(corpo.get('data'), str):
            return registrar('RESPOSTA_INESPERADA')
        try:
            xml = bytes_xml(corpo['data'])
        except ValueError:
            return registrar('XML_INVALIDO', validacao='CODIFICACAO')
        validacao = validar_nfe_completa(xml, chave, cnpj_empresa=cnpj, tipo=tipo)
        if validacao.status not in {'VALIDO_ESTRUTURAL', 'DADOS_FISCAIS_CONFERIDOS'}:
            digest = hashlib.sha256(xml).hexdigest()
            quarentena = raiz_saida / 'quarentena' / f'{chave}-{digest[:12]}.bin'
            quarentena.parent.mkdir(parents=True, exist_ok=True)
            try:
                with quarentena.open('xb') as arquivo:
                    arquivo.write(xml)
            except FileExistsError:
                pass
            return registrar('XML_INVALIDO', validacao=validacao.status, motivo=validacao.motivo,
                             quarentena=str(quarentena), sha256=digest)
        destino_final = destino if validacao.status == 'VALIDO_ESTRUTURAL' else destino_dados
        destino_final.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destino_final.open('xb') as arquivo:
                arquivo.write(xml)
        except FileExistsError:
            return registrar('ARQUIVO_JA_EXISTE_REVALIDAR')
        status = ('XML_VALIDADO_ESTRUTURALMENTE' if validacao.status == 'VALIDO_ESTRUTURAL'
                  else 'XML_DADOS_FISCAIS_CONFERIDOS')
        return registrar(status, xml=str(destino_final),
                         sha256=hashlib.sha256(xml).hexdigest(),
                         protocolo_presente=True, itens_presentes=True,
                         assinatura_presente=validacao.assinatura_presente,
                         estrutura_transformada=validacao.estrutura_transformada)

    try:
        status_http, corpo = baixar()
    except RuntimeError as erro:
        return registrar('FALHA_API', erro=str(erro))
    if status_http != 404:
        return tratar_download(status_http, corpo)
    if anterior.get('busca_paga_potencialmente_enviada'):
        return registrar('CONSULTA_PENDENTE', motivo='Busca anterior enviada; não reenviar automaticamente')
    if not autorizar_consulta_paga:
        return registrar('AGUARDANDO_APROVACAO_CUSTO', custo_maximo_brl='0.03')

    # Persistir antes do PUT evita repetir uma possível cobrança após interrupção.
    registrar('ENVIO_INDETERMINADO', busca_paga_potencialmente_enviada=True,
             busca_paga_nova_potencialmente_enviada=True,
             motivo='PUT pode ter sido enviado; não repetir automaticamente')
    try:
        status_http, corpo = request('PUT', f'/fd/add/{chave}', api_key)
    except RuntimeError as erro:
        return registrar('ENVIO_INDETERMINADO', erro=str(erro))
    if status_http != 200 or not corpo:
        return registrar('FALHA_API', http_status=status_http)
    if corpo.get('value') != chave or corpo.get('type') != 'NFE':
        return registrar('RESPOSTA_INESPERADA')
    status_busca = corpo.get('status')
    if status_busca == 'NOT_FOUND':
        return registrar('XML_INDISPONIVEL')
    if status_busca == 'ERROR':
        return registrar('FALHA_API', status_busca=status_busca)
    if status_busca not in {'OK', 'WAITING', 'SEARCHING'}:
        return registrar('RESPOSTA_INESPERADA')
    registrar('CONSULTA_ENVIADA', status_busca=status_busca)
    for tentativa in range(3):
        pausa(2)
        try:
            status_http, corpo = baixar()
        except RuntimeError as erro:
            return registrar('CONSULTA_PENDENTE', erro=str(erro))
        if status_http == 200:
            return tratar_download(status_http, corpo)
        if status_http != 404:
            return registrar('FALHA_API', http_status=status_http)
        if tentativa < 2:
            # A documentação autoriza reutilizar PUT para consultar o status,
            # respeitando intervalo >= 1 segundo para a mesma chave.
            try:
                status_http, corpo = request('PUT', f'/fd/add/{chave}', api_key)
            except RuntimeError as erro:
                return registrar('CONSULTA_PENDENTE', erro=str(erro))
            if status_http != 200 or not corpo or corpo.get('value') != chave:
                return registrar('CONSULTA_PENDENTE', http_status=status_http)
            if corpo.get('status') == 'NOT_FOUND':
                return registrar('XML_INDISPONIVEL')
            if corpo.get('status') == 'ERROR':
                return registrar('FALHA_API', status_busca='ERROR')
            if corpo.get('status') not in {'OK', 'WAITING', 'SEARCHING'}:
                return registrar('RESPOSTA_INESPERADA')
    return registrar('CONSULTA_PENDENTE', motivo='XML ainda não disponível após sondagens limitadas')


def main() -> int:
    parser = argparse.ArgumentParser(description='Teste de uma única NF-e via API v2 Meu Danfe')
    origem = parser.add_mutually_exclusive_group(required=True)
    origem.add_argument('--chave', help='Chave NF-e 55 de 44 dígitos')
    origem.add_argument('--planilha', type=Path, help='Seleciona uma chave NF-e 55 válida da planilha')
    parser.add_argument('--indice-chave', type=int, default=0,
                        help='Índice da chave distinta na planilha, começando em 0; uma por execução')
    parser.add_argument('--cnpj-empresa', help='CNPJ da empresa atendida; em emitidas, padrão: CNPJ da chave')
    parser.add_argument('--tipo', choices=['emitidas', 'recebidas'], required=True)
    parser.add_argument('--autorizar-consulta-paga', action='store_true',
                        help='Permite uma busca de NF-e por chave que pode custar R$ 0,03')
    parser.add_argument('--saida', type=Path, default=RAIZ / 'saida' / 'xmls')
    parser.add_argument('--relatorio-xlsx', type=Path,
                        help='Destino da planilha por produto; padrão: saida/relatorios/<CNPJ>/<AAAA-MM>/RelatorioNFe_XML.xlsx')
    args = parser.parse_args()
    try:
        chave = escolher_chave(args.chave, args.planilha, args.indice_chave)
        cnpj = args.cnpj_empresa or (chave[6:20] if args.tipo == 'emitidas' else '')
        resultado = executar(chave, ler_api_key(RAIZ / '.env'), args.saida,
                            cnpj, args.tipo, args.autorizar_consulta_paga,
                            origem=args.planilha.name if args.planilha else 'chave_informada')
        if resultado['status'] in {'XML_VALIDADO_ESTRUTURALMENTE', 'JA_EXISTE_XML',
                                 'XML_DADOS_FISCAIS_CONFERIDOS', 'JA_EXISTEM_DADOS_FISCAIS'}:
            from relatorio_nfe import reunir_xmls, salvar_xlsx
            ano, mes = '20' + chave[2:4], chave[4:6]
            destino_relatorio = (args.relatorio_xlsx or RAIZ / 'saida' / 'relatorios' / cnpj /
                                 f'{ano}-{mes}' / 'RelatorioNFe_XML.xlsx')
            from relatorio_mensal import gerar_mensal
            destino_mensal = (RAIZ / 'saida' / 'relatorios' / cnpj /
                              f'{ano}-{mes}' / 'RelatorioMensal.xlsx')
            try:
                gerar_mensal(args.saida, cnpj, f'{ano}-{mes}', destino_mensal)
                resultado['relatorio_mensal_xlsx'] = str(destino_mensal)
            except PermissionError:
                resultado['relatorio_mensal_pendente'] = 'Arquivo aberto no Excel; feche-o e gere novamente'
            linhas, resumo = reunir_xmls(args.saida / cnpj / ano / mes, cnpj)
            try:
                salvar_xlsx(linhas, destino_relatorio)
                resultado['relatorio_xlsx'] = str(destino_relatorio)
                resultado['itens_no_relatorio'] = resumo['itens']
            except PermissionError:
                resultado['relatorio_xlsx_pendente'] = 'Arquivo aberto no Excel; feche-o e gere novamente'
    except (ValueError, OSError) as erro:
        parser.error(str(erro))
    print(json.dumps({k: v for k, v in resultado.items() if k not in {'chave', 'cnpj_empresa', 'xml', 'quarentena'}},
                     ensure_ascii=False, indent=2))
    return 0 if resultado['status'] in {'XML_VALIDADO_ESTRUTURALMENTE', 'JA_EXISTE_XML',
                                       'XML_DADOS_FISCAIS_CONFERIDOS', 'JA_EXISTEM_DADOS_FISCAIS'} else 2


if __name__ == '__main__':
    sys.exit(main())
