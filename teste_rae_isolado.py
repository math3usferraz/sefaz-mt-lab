"""Aponta o Reverse API Engineer para um Chrome separado, já aberto.

Uso com .venv-rae. Verifica as abas antes de iniciar, para evitar o Chrome
principal. A versão instalada do RAE é adaptada somente nesta execução.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from reverse_api.chrome_mcp import CHROME_DEVTOOLS_MCP_PACKAGE
from reverse_api.codex_engineer import CodexAutoEngineer, MCP_STARTUP_TIMEOUT_SEC
from seguranca_rae import ExecucaoRaeBloqueada, validar_abas_para_rae


PORTA = 9351


def main() -> None:
    with urllib.request.urlopen(f'http://127.0.0.1:{PORTA}/json/list', timeout=3) as resposta:
        abas = json.load(resposta)
    try:
        validar_abas_para_rae(abas)
    except ExecucaoRaeBloqueada as exc:
        raise SystemExit(str(exc)) from exc
    paginas = [p.get('url', '') for p in abas if p.get('type') == 'page']
    if False and (not paginas or any(not (url.startswith('https://www.sefaz.mt.gov.br/') or
                               url in ('about:blank', 'chrome://newtab/', 'chrome://new-tab-page/'))
                           for url in paginas)):
        raise SystemExit('Chrome dedicado ausente ou contém abas fora da SEFAZ; execução interrompida.')

    def browser_dedicado(self):
        if self.agent_provider != 'chrome-mcp' or self.headless:
            raise RuntimeError('Este teste exige chrome-mcp com janela visível.')
        return {'chrome-devtools': {
            'command': 'npx',
            'args': ['-y', CHROME_DEVTOOLS_MCP_PACKAGE, '--no-usage-statistics', '--no-performance-crux',
                     '--browserUrl', f'http://127.0.0.1:{PORTA}'],
            'startup_timeout_sec': MCP_STARTUP_TIMEOUT_SEC,
        }}

    CodexAutoEngineer._browser_servers = browser_dedicado
    from reverse_api.cli import config_manager, main as cli
    config_manager.config['real_time_sync'] = False
    sys.argv = [sys.argv[0], *sys.argv[1:]]
    cli()


if __name__ == '__main__':
    main()
