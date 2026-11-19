"""PoC de acesso à SEFAZ-MT e extração local de planilha de chaves.

Não automatiza CAPTCHA ou Cloudflare. Usa navegador normal e pausa para
interação humana autorizada quando o portal solicitar autenticação.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlsplit, urlunsplit

from extrair_chaves import extrair_do_arquivo, salvar_csv

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "saida"
PERFIL = RAIZ / "perfil_chrome"
DOWNLOADS = SAIDA / "downloads"
PORTAL = "https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml"


def analisar_pagina(pagina) -> dict:
    html_lido = False
    if hasattr(pagina, 'run_cdp'):
        # title/url/html no DrissionPage esperam doc_loaded(); o portal pode
        # manter essa espera aberta mesmo depois de mudar de tela.
        try:
            info = pagina.run_cdp('Target.getTargetInfo', _timeout=3)['targetInfo']
            titulo, url = str(info.get('title') or ''), str(info.get('url') or '')
        except Exception:
            titulo, url = '', ''
        try:
            js = pagina.run_cdp('Runtime.evaluate',
                                expression="document.documentElement?.outerHTML?.slice(0,350000) || ''",
                                returnByValue=True, _timeout=3)
            valor = js.get('result', {}).get('value')
            html_lido = isinstance(valor, str) and bool(valor.strip())
            html = str(valor or '').lower()
        except Exception:
            html = ''
    else:
        try:
            titulo = str(pagina.title or '')
            url = str(pagina.url or '')
            html = (pagina.html or '')[:350000].lower()
            html_lido = bool(html.strip())
        except Exception:
            titulo, url, html = '', '', ''

    titulo_min = titulo.lower()
    sinais_bloqueio = ("error 1020", "access denied", "sorry, you have been blocked", "you have been blocked", "acesso negado")
    sinais_desafio = (
        "just a moment", "verificando seu navegador", "checking your browser",
        "verify you are human", "verifique se você é humano", "cf-challenge", 
        "challenges.cloudflare.com/turnstile", "/cdn-cgi/challenge-platform/",
    )
    if any(s in titulo_min or s in html for s in sinais_bloqueio):
        status = "BLOQUEIO_DETECTADO"
    elif any(s in titulo_min or s in html for s in sinais_desafio):
        status = "DESAFIO_DETECTADO"
    elif not url or url == "about:blank":
        status = "PAGINA_NAO_CARREGADA"
    elif not html_lido:
        # Uma URL alcancavel nao comprova que o desafio foi liberado.
        status = "PAGINA_NAO_VERIFICADA"
    else:
        status = "PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE"
    partes = urlsplit(url)
    url_segura = urlunsplit((partes.scheme, partes.netloc, partes.path.split(';', 1)[0], '', ''))
    return {
        "status": status,
        "titulo": titulo,
        "url_final": url_segura,
        "registrado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "nota": "Resultado heurístico: não comprova login nem autorização de acesso.",
    }


def aguardar_liberacao_portal(pagina, timeout: float = 120, intervalo: float = 1,
                             analisar=analisar_pagina, dormir=time.sleep,
                             relogio=time.monotonic) -> dict:
    """Aguarda o portal/desafio sem clicar, resolver CAPTCHA ou mudar a pagina.

    Se o desafio exigir validacao, a pessoa deve realiza-la no navegador aberto.
    Falha fechada: URL carregada com DOM indisponivel nao e considerada liberada.
    """
    if timeout < 0 or intervalo <= 0:
        raise ValueError('Tempo de espera ou intervalo invalido.')
    limite = relogio() + timeout
    avisou = False
    while True:
        estado = analisar(pagina)
        status = estado['status']
        if status in {'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE', 'BLOQUEIO_DETECTADO'}:
            return estado
        if status == 'DESAFIO_DETECTADO' and not avisou:
            print('Desafio de seguranca detectado. Aguardando validacao no navegador; a rotina nao interage com o desafio.', flush=True)
            avisou = True
        restante = limite - relogio()
        if restante <= 0:
            return estado
        dormir(min(intervalo, restante))


def salvar_evidencia(pagina, nome: str, capturar_tela: bool = True) -> dict:
    SAIDA.mkdir(exist_ok=True)
    info = analisar_pagina(pagina)
    destino = SAIDA / f"{nome}.json"
    destino.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    if capturar_tela:
        try:
            pagina.get_screenshot(path=str(SAIDA), name=f"{nome}.png")
            info["screenshot"] = str(SAIDA / f"{nome}.png")
        except Exception as exc:
            info["erro_screenshot"] = type(exc).__name__
    destino.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSTATUS: {info['status']}")
    print(f"Título: {info['titulo']}")
    print(f"URL final: {info['url_final']}")
    print(f"Evidências locais: {SAIDA}")
    return info


def aguardando_download(pasta: Path, inicio: float, timeout: int = 120) -> Path | None:
    extensoes = {".xlsx", ".xls", ".csv", ".txt", ".zip"}
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        arquivos = [p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in extensoes and p.stat().st_mtime >= inicio - 2]
        for arquivo in sorted(arquivos, key=lambda p: p.stat().st_mtime, reverse=True):
            # Download concluído quando tamanho não muda e não há .crdownload com o mesmo nome.
            t1 = arquivo.stat().st_size
            time.sleep(1.5)
            if not arquivo.exists():
                continue
            if arquivo.stat().st_size == t1 and t1 > 0 and not (pasta / (arquivo.name + ".crdownload")).exists():
                return arquivo
        time.sleep(1)
    return None


def criar_pasta_download_execucao(base: Path) -> Path:
    """Isola downloads desta tentativa dos arquivos de execuções anteriores."""
    base.mkdir(parents=True, exist_ok=True)
    pasta = base / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{secrets.token_hex(4)}"
    pasta.mkdir(exist_ok=False)
    return pasta


def executar(args) -> int:
    from DrissionPage import ChromiumOptions, ChromiumPage
    SAIDA.mkdir(exist_ok=True)
    pasta_download = criar_pasta_download_execucao(DOWNLOADS)
    perfil = criar_pasta_download_execucao(SAIDA / "perfis") if args.perfil_temporario else PERFIL
    perfil.mkdir(parents=True, exist_ok=True)

    opcoes = ChromiumOptions()
    if args.chrome:
        opcoes.set_browser_path(args.chrome)
    opcoes.set_local_port(args.porta)
    opcoes.set_argument(f"--user-data-dir={perfil}")
    opcoes.set_argument("--start-maximized")
    pagina = ChromiumPage(addr_or_opts=opcoes)
    pagina.set.download_path(str(pasta_download))

    try:
        print(f"Abrindo: {args.url}")
        try:
            pagina.get(args.url)
        except Exception as exc:
            print(f"Falha de navegação: {type(exc).__name__}: {exc}")
        time.sleep(args.aguardar)
        primeira = salvar_evidencia(pagina, "01_acesso_inicial")

        if args.etapa == "acesso":
            print("\nTeste de acesso concluído. Não foi realizado login ou download automaticamente.")
            return 0 if primeira["status"] == "PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE" else 2

        atual = aguardar_liberacao_portal(pagina, timeout=120)
        if atual['status'] != 'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE':
            print(f"Portal indisponivel ou nao verificado: {atual['status']}")
            return 2

        if args.login_automatico:
            from sefaz_login import autenticar_contribuinte
            try:
                tentativas_usadas = autenticar_contribuinte(
                    pagina, args.cnpj, args.ie, tentativas=args.tentativas_login
                )
            except Exception as exc:
                print(f"Login por A1 não confirmado: {type(exc).__name__}: {exc}")
                salvar_evidencia(pagina, "02_falha_login", capturar_tela=False)
                return 6
            print(f"Login confirmado após {tentativas_usadas} envio(s) do formulário.")
            salvar_evidencia(pagina, "02_login_contribuinte")
            if args.etapa == "login":
                print("Login de contribuinte confirmado pelo portal.")
                return 0

        if not args.login_automatico:
            print("\nNo Chrome aberto, acesse com sua própria credencial autorizada.")
        print("Navegue para NF-e Emitida/Recebida, selecione o período e consulte as notas.")
        input("Quando a tabela com os resultados estiver visível, pressione ENTER aqui... ")
        segunda = salvar_evidencia(pagina, "02_apos_navegacao")
        if segunda["status"] in {"BLOQUEIO_DETECTADO", "DESAFIO_DETECTADO"}:
            print("Ainda há bloqueio ou desafio. Encerrando sem tentar clicar/baixar.")
            return 2

        inicio_download = time.time()
        if args.seletor_exportacao:
            print(f"Procurando botão de exportação: {args.seletor_exportacao}")
            try:
                botao = pagina.ele(args.seletor_exportacao, timeout=7)
                if botao:
                    botao.click()
                    print("Clique realizado. Aguardando arquivo...")
                else:
                    print("Botão não encontrado. Clique manualmente em Exportar para Excel.")
            except Exception as exc:
                print(f"Clique não realizado ({type(exc).__name__}). Exporte manualmente.")
        else:
            print("Clique manualmente em 'Exportar para Excel' no Chrome agora.")

        print(f"Monitorando somente a pasta desta execução: {pasta_download}")
        arquivo = aguardando_download(pasta_download, inicio_download, args.timeout_download)
        if arquivo is None:
            print("Nenhuma nova planilha detectada. Confirme se o arquivo realmente foi baixado.")
            salvar_evidencia(pagina, "03_sem_download")
            return 3
        print(f"Planilha encontrada: {arquivo.name}")
        try:
            chaves, avisos = extrair_do_arquivo(arquivo)
        except Exception as exc:
            print(f"Erro ao interpretar arquivo: {type(exc).__name__}: {exc}")
            return 4
        destino = pasta_download / "chaves_extraidas.csv"
        salvar_csv(chaves, destino)
        for aviso in avisos:
            print(f"ATENÇÃO: {aviso}")
        qtd_nfe = sum(ch[20:22] == "55" for ch in chaves)
        qtd_nfce = sum(ch[20:22] == "65" for ch in chaves)
        print(f"Chaves válidas únicas encontradas: {len(chaves)} (NF-e: {qtd_nfe}; NFC-e: {qtd_nfce})")
        print(f"Arquivo gerado: {destino}")
        salvar_evidencia(pagina, "03_apos_download")
        return 0 if chaves else 5
    finally:
        try:
            pagina.quit()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste isolado de acesso à SEFAZ-MT + captura da planilha com chaves de NF-e")
    parser.add_argument("--url", default=PORTAL, help="URL exata do portal onde o robô fica bloqueado")
    parser.add_argument("--etapa", choices=["acesso", "login", "planilha"], default="acesso")
    parser.add_argument("--chrome", default="", help="Caminho do chrome.exe caso não seja detectado")
    parser.add_argument("--porta", type=int, default=9331, help="Porta local para controle do navegador")
    parser.add_argument("--aguardar", type=int, default=12, help="Segundos para a primeira análise após abrir")
    parser.add_argument("--timeout-download", type=int, default=120)
    parser.add_argument("--seletor-exportacao", default="", help="Seletor DrissionPage para clicar no exportador após chegar aos resultados")
    parser.add_argument("--login-automatico", action="store_true", help="Usa o A1 instalado no Windows para entrar como Contribuinte MT")
    parser.add_argument("--cnpj", default="", help="CNPJ do certificado A1 instalado no Windows")
    parser.add_argument("--ie", default="", help="Inscrição estadual da empresa autorizada")
    parser.add_argument("--perfil-temporario", action="store_true", help="Cria um perfil Chrome vazio e isolado nesta execução")
    parser.add_argument("--tentativas-login", type=int, default=8, help="Máximo de envios do login se o portal voltar ao formulário sem erro (1 a 12)")
    args = parser.parse_args()
    if args.login_automatico and (not args.cnpj or not args.ie):
        parser.error("--login-automatico requer --cnpj e --ie")
    if args.etapa == "login" and not args.login_automatico:
        parser.error("--etapa login requer --login-automatico")
    if not 1 <= args.tentativas_login <= 12:
        parser.error("--tentativas-login deve estar entre 1 e 12")
    try:
        return executar(args)
    except KeyboardInterrupt:
        print("\nCancelado pelo operador.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
