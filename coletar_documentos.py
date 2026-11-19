"""Coleta mensal em uma unica sessao A1 da SEFAZ-MT.

Ordem: NF-e recebidas/emitidas, CT-e emissor/tomador e CT-e OS
emissor. Nenhuma etapa reabre o login ou cria outra sessao.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import sys
import time

from DrissionPage import ChromiumOptions, ChromiumPage

from coletar_cte import coletar_tipo as coletar_cte_tipo
from coletar_nfe import SAIDA, coletar_tipo as coletar_nfe_tipo
from main import analisar_pagina
from sefaz_login import LOGIN, autenticar_contribuinte, titulo_sem_espera, url_sem_espera


def argumentos():
    cli = argparse.ArgumentParser(description='Coleta NF-e e CT-e em uma unica sessao SEFAZ-MT')
    cli.add_argument('--cnpj', required=True)
    cli.add_argument('--ie', required=True)
    cli.add_argument('--inicio', required=True, help='DD/MM/AAAA')
    cli.add_argument('--fim', required=True, help='DD/MM/AAAA')
    cli.add_argument('--porta', type=int, default=9331)
    cli.add_argument('--timeout-download', type=int, default=180)
    return cli.parse_args()


def main() -> int:
    args = argumentos()
    try:
        inicio, fim = (datetime.strptime(args.inicio, '%d/%m/%Y'),
                       datetime.strptime(args.fim, '%d/%m/%Y'))
    except ValueError:
        print('FALHA: datas devem estar em DD/MM/AAAA', file=sys.stderr)
        return 2
    if inicio > fim or (inicio.year, inicio.month) != (fim.year, fim.month):
        print('FALHA: informe uma unica competencia mensal', file=sys.stderr)
        return 2
    if not re.fullmatch(r'\d{14}', args.cnpj) or not re.fullmatch(r'\d{9}', args.ie):
        print('FALHA: CNPJ ou IE invalidos', file=sys.stderr)
        return 2

    base_empresa = SAIDA / args.cnpj / f'{inicio:%Y-%m}'
    base_empresa.mkdir(parents=True, exist_ok=True)
    base = base_empresa / f'{datetime.now():%Y%m%d_%H%M%S_%f}_{secrets.token_hex(4)}'
    base.mkdir()
    perfil = Path(__file__).resolve().parent / 'saida' / 'perfis' / f'empresa_{args.cnpj}'
    perfil.mkdir(parents=True, exist_ok=True)
    opcoes = ChromiumOptions()
    opcoes.set_timeouts(base=10, page_load=10, script=10)
    opcoes.set_local_port(args.porta)
    opcoes.set_argument(f'--user-data-dir={perfil}')
    opcoes.set_argument('--start-maximized')
    pagina = ChromiumPage(addr_or_opts=opcoes)
    relatorio = {'status': 'EM_ANDAMENTO', 'pasta': str(base), 'etapas': {}}
    try:
        pagina.get(LOGIN, timeout=10)
        time.sleep(10)
        estado = analisar_pagina(pagina)
        if estado['status'] != 'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE':
            raise RuntimeError(f'Portal indisponivel ou desafio de seguranca: {estado["status"]}')
        envios = autenticar_contribuinte(pagina, args.cnpj, args.ie,
                                         tentativas=0, tentativas_certificado=0)
        print(f'Login confirmado apos {envios} envio(s).', flush=True)

        for tipo in ('recebidas', 'emitidas'):
            relatorio['etapas'][f'nfe_{tipo}'] = coletar_nfe_tipo(
                pagina, base, args.cnpj, args.ie, inicio, fim, tipo, args.timeout_download)
        for consulta, tipos in (('cte', ('Emissor', 'Tomador')), ('cteos', ('Emissor',))):
            for tipo in tipos:
                nome = f'{consulta}_{tipo.lower()}'
                relatorio['etapas'][nome] = coletar_cte_tipo(pagina, base, consulta, tipo, inicio, fim)
        relatorio['status'] = 'CONCLUIDO'
        return 0
    except Exception as erro:
        relatorio['status'] = 'FALHA'
        relatorio['motivo'] = f'{type(erro).__name__}: {erro}'
        return 1
    finally:
        try:
            relatorio['pagina_final'] = {'url': url_sem_espera(pagina), 'titulo': titulo_sem_espera(pagina)}
        except Exception:
            pass
        (base / 'relatorio_documentos.json').write_text(json.dumps(relatorio, ensure_ascii=False, indent=2),
                                                         encoding='utf-8')
        try:
            pagina.quit()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
