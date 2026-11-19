"""Diagnóstico somente de leitura do menu de CT-e no portal autenticado."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import secrets
import sys
import time
import traceback

from DrissionPage import ChromiumOptions, ChromiumPage

from main import analisar_pagina
from sefaz_login import LOGIN, autenticar_contribuinte, titulo_sem_espera, url_sem_espera


RAIZ = Path(__file__).resolve().parent


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument('--cnpj', required=True)
    cli.add_argument('--ie', required=True)
    cli.add_argument('--porta', type=int, default=9332)
    cli.add_argument('--consulta', choices=['cte', 'cteos'], default='cte',
                     help='Consulta de CT-e comum ou CT-e OS a inspecionar')
    cli.add_argument('--perfil-existente', type=Path)
    cli.add_argument('--manter-aberto', action='store_true', help='Mantem o Chrome aberto ao final do diagnostico')
    args = cli.parse_args()
    id_execucao = f'{datetime.now():%Y%m%d_%H%M%S_%f}_{secrets.token_hex(4)}'
    pasta = RAIZ / 'saida' / 'diagnosticos' / 'cte' / id_execucao
    raiz_perfis = (RAIZ / 'saida' / 'perfis').resolve()
    perfil = (args.perfil_existente.resolve() if args.perfil_existente
              else raiz_perfis / f'empresa_{args.cnpj}')
    if not perfil.is_relative_to(raiz_perfis):
        cli.error('Perfil deve estar dentro de saida/perfis')
    pasta.mkdir(parents=True, exist_ok=False)
    if not args.perfil_existente:
        perfil.mkdir(parents=True, exist_ok=True)
    elif not perfil.is_dir():
        cli.error('Perfil existente não encontrado')
    opcoes = ChromiumOptions()
    opcoes.set_timeouts(base=10, page_load=10, script=10)
    opcoes.set_local_port(args.porta)
    opcoes.set_argument(f'--user-data-dir={perfil}')
    opcoes.set_argument('--start-maximized')
    pagina = ChromiumPage(addr_or_opts=opcoes)
    resultado = {'status': 'INICIADO', 'pasta': str(pasta)}
    try:
        pagina.get(LOGIN, timeout=10)
        time.sleep(10)
        estado = analisar_pagina(pagina)
        if estado['status'] == 'DESAFIO_DETECTADO':
            limite = time.monotonic() + 30
            while time.monotonic() < limite and analisar_pagina(pagina)['status'] == 'DESAFIO_DETECTADO':
                time.sleep(1)
            estado = analisar_pagina(pagina)
        if estado['status'] != 'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE':
            raise RuntimeError(f'Portal: {estado["status"]}')
        if '/acesso/pages/paginainicial.xhtml' not in url_sem_espera(pagina):
            autenticar_contribuinte(pagina, args.cnpj, args.ie,
                                    tentativas=0, tentativas_certificado=0)
        limite = time.monotonic() + 40
        menu = None
        while time.monotonic() < limite:
            try:
                menu = pagina.get_frame('iframeMenu')
                if menu and menu.eles('tag:a'):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if menu is None:
            raise RuntimeError('Menu do contribuinte não apareceu')
        links = [{'texto': a.text.strip(), 'href': a.attr('href'), 'onclick': a.attr('onclick')}
                 for a in menu.eles('tag:a') if a.text.strip()]
        (pasta / 'menu.html').write_text(menu.html or '', encoding='utf-8')
        (pasta / 'menu.json').write_text(json.dumps(links, ensure_ascii=False, indent=2),
                                         encoding='utf-8')
        relevantes = [x for x in links if 'ct-e' in x['texto'].lower() or
                      'conhecimento de transporte' in x['texto'].lower()]
        resultado['status'] = 'MENU_INSPECIONADO'
        resultado['links_cte'] = [x['texto'] for x in relevantes]
        texto_consulta = ('Consulta CT-e Emitidos/Recebidos' if args.consulta == 'cte'
                          else 'Consulta Emitidos/Recebidos CTe-OS')
        candidatos = [a for a in menu.eles('tag:a') if a.text.strip() == texto_consulta]
        if len(candidatos) == 1:
            candidatos[0].click(by_js=True)
            time.sleep(5)
            try:
                frame = pagina.get_frame('iframeCenter')
                (pasta / 'consulta.html').write_text(frame.html or '', encoding='utf-8')
                resultado['status'] = 'CONSULTA_ABERTA'
                resultado['url_consulta'] = frame.url
                resultado['texto_consulta_inicio'] = (frame.run_js('return document.body.innerText') or '')[:300]
            except Exception as erro:
                resultado['falha_frame'] = type(erro).__name__
        try:
            pagina.get_screenshot(path=str(pasta), name='pagina.png')
        except Exception:
            pass
        return 0
    except Exception as erro:
        resultado['status'] = 'FALHA'
        resultado['motivo'] = f'{type(erro).__name__}: {erro}'
        resultado['etapa_erro'] = [
            {'arquivo': Path(x.filename).name, 'linha': x.lineno, 'funcao': x.name}
            for x in traceback.extract_tb(erro.__traceback__) if Path(x.filename).name in
            {'diagnosticar_cte.py', 'sefaz_login.py'}
        ]
        return 1
    finally:
        try:
            resultado['url_final'] = url_sem_espera(pagina)
            resultado['titulo_final'] = titulo_sem_espera(pagina)
        except Exception:
            pass
        try:
            resposta = pagina.run_cdp('Runtime.evaluate',
                                      expression="document.documentElement?.outerHTML || ''",
                                      returnByValue=True, _timeout=3)
            (pasta / 'pagina.html').write_text(
                str(resposta.get('result', {}).get('value') or ''), encoding='utf-8')
        except Exception:
            pass
        try:
            pagina.get_screenshot(path=str(pasta), name='pagina_final.png')
        except Exception:
            pass
        (pasta / 'resultado.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                               encoding='utf-8')
        print(json.dumps({k: v for k, v in resultado.items() if k != 'texto_consulta_inicio'},
                         ensure_ascii=True))
        if not args.manter_aberto:
            try:
                pagina.quit()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
