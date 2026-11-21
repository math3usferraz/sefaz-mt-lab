"""Login autorizado no Acesso Web com A1 instalado no Windows.

Caminho principal: o perfil Chrome recebe a preferencia auto_select_certificate
com o CN do A1, e o Chrome entrega o certificado sem abrir a janela nativa.
Fallback: a janela nativa e confirmada por UI Automation. Nenhum arquivo PFX
ou senha e lido por este modulo.
"""
from __future__ import annotations

from pathlib import Path
from itertools import count
import base64
import json
import os
import re
import subprocess
import time

from DrissionPage.errors import ContextLostError, ElementLostError, WaitTimeoutError

RAIZ = Path(__file__).resolve().parent
LOGIN = "https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml"
# Padrao de conteudo do Chrome: o host e todos os subdominios, so HTTPS.
PADRAO_SEFAZ = "https://[*.]sefaz.mt.gov.br"
# Bypass vale so para este processo. RemoteSigned recusa .ps1 extraido de um
# .zip baixado (marca "da internet"), e o erro ficava invisivel: o login
# parecia travado no certificado.
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]


def resumo_erro_powershell(resultado) -> str:
    """Primeiras linhas uteis do stderr/stdout do PowerShell, sem identificadores."""
    texto = (getattr(resultado, 'stderr', '') or '') + '\n' + (getattr(resultado, 'stdout', '') or '')
    linhas = [linha.strip() for linha in texto.splitlines()
              if linha.strip() and not linha.strip().startswith(('+', 'At ', 'No ', '~'))]
    if not linhas:
        return f'codigo {getattr(resultado, "returncode", "?")}, sem mensagem'
    erros = [linha[5:].strip() for linha in linhas if linha.startswith('ERRO:')]
    if erros:
        linhas = erros + [linha for linha in linhas if linha.startswith('Itens do dialogo')]
    return re.sub(r"\d{9,14}", "[identificador]", ' / '.join(linhas[:2])[:400])


def nome_certificado_a1(cnpj: str, executar=subprocess.run) -> str | None:
    """CN do A1 valido do CNPJ no repositorio pessoal do Windows, ou None.

    Somente leitura (nome_certificado.ps1); falha nao e fatal porque o fallback
    pela janela nativa continua disponivel.
    """
    if not re.fullmatch(r"\d{14}", cnpj):
        raise ValueError("CNPJ deve ter 14 digitos.")
    if os.name != 'nt':
        return None
    comando = POWERSHELL + [str(RAIZ / "nome_certificado.ps1"), "-Cnpj", cnpj]
    try:
        resultado = executar(comando, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'Nome do A1 nao lido ({type(exc).__name__}); usando a janela do Chrome.', flush=True)
        return None
    saida = getattr(resultado, 'stdout', '') or ''
    achado = re.search(r"CN_BASE64:([A-Za-z0-9+/=]+)", saida)
    if resultado.returncode != 0 or not achado:
        print(f'Nome do A1 nao lido: {resumo_erro_powershell(resultado)}', flush=True)
        return None
    for aviso in re.findall(r"AVISO_[A-Z0-9_]+", saida):
        print(f'Certificado: {aviso}', flush=True)
    nome = base64.b64decode(achado.group(1)).decode('utf-8')
    if not nome.endswith(f':{cnpj}'):
        raise RuntimeError('CN devolvido nao corresponde ao CNPJ pedido.')
    return nome


def preparar_perfil_certificado(perfil: Path, nome_certificado: str,
                                padrao: str = PADRAO_SEFAZ) -> Path:
    """Grava a auto-selecao do A1 nas preferencias do perfil Chrome.

    Equivale a politica AutoSelectCertificateForUrls, porem restrita ao perfil
    desta execucao: o Chrome entrega ao portal o certificado com esse CN sem
    abrir a janela "Selecione um certificado" (onde a execucao travava) e sem
    alterar o registro do Windows nem o Chrome do dia a dia. Deve ser chamada
    com o Chrome fechado para esse perfil.
    """
    if not nome_certificado or ':' not in nome_certificado:
        raise ValueError('Nome de certificado invalido.')
    arquivo = Path(perfil) / 'Default' / 'Preferences'
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    try:
        dados = json.loads(arquivo.read_text(encoding='utf-8')) if arquivo.exists() else {}
    except (OSError, ValueError) as exc:
        raise RuntimeError('Preferences do perfil Chrome ilegivel; use um perfil novo.') from exc
    if not isinstance(dados, dict):
        raise RuntimeError('Preferences do perfil Chrome em formato inesperado.')
    excecoes = (dados.setdefault('profile', {}).setdefault('content_settings', {})
                .setdefault('exceptions', {}))
    regras = excecoes.setdefault('auto_select_certificate', {})
    regras[f'{padrao},*'] = {'setting': {'filters': [{'SUBJECT': {'CN': nome_certificado}}]}}
    temporario = arquivo.with_name('Preferences.tmp')
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding='utf-8')
    os.replace(temporario, arquivo)
    return arquivo


def configurar_certificado_no_perfil(perfil: Path, cnpj: str, executar=subprocess.run) -> bool:
    """Le o CN do A1 e prepara o perfil. Retorna False se cair no fallback."""
    nome = nome_certificado_a1(cnpj, executar=executar)
    if not nome:
        return False
    preparar_perfil_certificado(perfil, nome)
    print('Auto-selecao do A1 gravada no perfil Chrome desta execucao.', flush=True)
    return True


def aguardar_saida_do_login(pagina, espera: float) -> str | None:
    """Espera a navegacao causada pelo clique no link do certificado.

    Retorna ``'certificado'``, ``'inicial'`` ou ``None`` se a pagina continuou
    no login (janela nativa aberta ou portal lento).
    """
    limite = time.monotonic() + espera
    while True:
        url = url_sem_espera(pagina)
        if "/acesso/pages/paginainicial.xhtml" in url:
            return 'inicial'
        if "login-certificado.xhtml" in url:
            return 'certificado'
        if "captcha" in titulo_sem_espera(pagina).lower():
            raise RuntimeError("Desafio de seguranca detectado apos selecionar certificado.")
        if time.monotonic() >= limite:
            return None
        time.sleep(0.5)


def url_sem_espera(pagina) -> str:
    """Lê a URL via CDP sem esperar o evento de carregamento da página.

    ``pagina.url`` no DrissionPage chama wait.doc_loaded(), que pode ficar
    preso quando o portal troca de tela ou mantém requisições pendentes.
    """
    if hasattr(pagina, 'run_cdp'):
        info = pagina.run_cdp('Target.getTargetInfo', _timeout=3)['targetInfo']
        return str(info.get('url') or '')
    return str(pagina.url)


def titulo_sem_espera(pagina) -> str:
    if hasattr(pagina, 'run_cdp'):
        info = pagina.run_cdp('Target.getTargetInfo', _timeout=3)['targetInfo']
        return str(info.get('title') or '')
    return str(pagina.title)


def elemento_css_sem_espera(pagina, seletor: str) -> int | None:
    """Consulta o DOM atual sem esperar doc_loaded()."""
    if not hasattr(pagina, 'run_cdp'):
        return None
    raiz = pagina.run_cdp('DOM.getDocument', depth=1, _timeout=3)['root']['nodeId']
    encontrados = pagina.run_cdp('DOM.querySelectorAll', nodeId=raiz,
                                selector=seletor, _timeout=3)['nodeIds']
    if len(encontrados) > 1:
        raise RuntimeError('Seletor encontrou mais de um elemento; clique interrompido.')
    return encontrados[0] if encontrados else None


def clicar_css_sem_espera(pagina, seletor: str) -> bool:
    node_id = elemento_css_sem_espera(pagina, seletor)
    if node_id is None:
        return False
    quad = pagina.run_cdp('DOM.getBoxModel', nodeId=node_id, _timeout=3)['model']['content']
    x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
    y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4
    for tipo in ('mousePressed', 'mouseReleased'):
        pagina.run_cdp('Input.dispatchMouseEvent', type=tipo, x=x, y=y,
                       button='left', clickCount=1, _timeout=3)
    return True


def formulario_certificado_visivel(pagina, espera: float = 10) -> bool:
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if '/acesso/pages/paginainicial.xhtml' in url_sem_espera(pagina):
            return True
        if 'login-certificado.xhtml' in url_sem_espera(pagina):
            try:
                if elemento_css_sem_espera(pagina, 'div[id="formCertificado:selectTipoUsuario"]'):
                    return True
            except Exception:
                pass  # O portal ainda desenha o formulário.
        time.sleep(0.5)
    return False


def estado_formulario_login_sem_espera(pagina) -> tuple[str | None, str]:
    """Le o formulario sem usar ``page.run_js`` durante um POST pendente.

    O AcessoWeb por vezes deixa o contexto JavaScript do DrissionPage preso
    entre dois envios do mesmo formulario. Nesse estado, falhar a leitura nao
    e motivo para interromper uma retentativa que o proprio portal exige.
    """
    if hasattr(pagina, 'run_cdp'):
        try:
            resposta = pagina.run_cdp(
                'Runtime.evaluate',
                expression="""(() => ({
                  valor: document.getElementById('formCertificado:inputLogin')?.value ?? null,
                  mensagem: document.getElementById('messages')?.innerText ?? ''
                }))()""",
                returnByValue=True,
                _timeout=2,
            )
            valor = resposta.get('result', {}).get('value', {})
            if isinstance(valor, dict):
                return valor.get('valor'), str(valor.get('mensagem') or '').strip()
        except Exception:
            return None, ''
        return None, ''
    valor = pagina.run_js('return document.getElementById("formCertificado:inputLogin")?.value')
    mensagem = pagina.ele('css:div[id="messages"]', timeout=1)
    return valor, mensagem.text.strip() if mensagem else ''


def botao_login_visivel(pagina):
    """Localiza o unico controle visivel com o rotulo do login.

    A SEFAZ alterna entre ``input[type=submit]`` e ``button`` ao redesenhar o
    formulario. O texto visivel, e nao a tag, e o contrato observado.
    """
    try:
        controles = pagina.eles('css:input[type="submit"],button', timeout=3)
        candidatos = [item for item in controles if
                      (item.text or '').strip() == 'Efetuar Login' or
                      str(item.attr('value') or '').strip() == 'Efetuar Login']
        if len(candidatos) == 1:
            return candidatos[0]
        if len(candidatos) > 1:
            raise RuntimeError('Mais de um botao Efetuar Login foi encontrado.')
    except AttributeError:
        pass
    return pagina.ele('css:input[type="submit"][value="Efetuar Login"]', timeout=3)


def enviar_login_com_retentativas(pagina, ie: str, tentativas: int = 8, intervalo: float = 10) -> int:
    """Repete o clique enquanto o portal mantiver o mesmo formulario.

    ``tentativas=0`` e intencionalmente sem limite: e o modo indicado para o
    AcessoWeb, que pode ignorar varios POSTs consecutivos sem informar erro.
    """
    if tentativas < 0 or intervalo < 0:
        raise ValueError("Limite de tentativas ou intervalo invalido.")

    numeros = count(1) if tentativas == 0 else range(1, tentativas + 1)
    for numero in numeros:
        if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
            return numero - 1
        if "login-certificado.xhtml" not in url_sem_espera(pagina):
            if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
                return numero - 1
            raise RuntimeError("Portal saiu do formulario de login sem confirmar a sessao.")
        if "captcha" in titulo_sem_espera(pagina).lower():
            raise RuntimeError("Desafio de seguranca detectado; login interrompido.")

        valor, detalhe = estado_formulario_login_sem_espera(pagina)
        if valor is not None and valor != ie:
            raise RuntimeError("IE no formulario mudou; login interrompido.")
        if detalhe:
            detalhe_seguro = re.sub(r"\d{9,14}", "[identificador]", detalhe[:180])
            raise RuntimeError(f"Login recusado pelo portal: {detalhe_seguro}")

        limite_texto = 'sem limite' if tentativas == 0 else str(tentativas)
        print(f'Enviando login: tentativa {numero}/{limite_texto}.', flush=True)
        clicou = False
        if hasattr(pagina, 'run_cdp'):
            try:
                clicou = clicar_css_sem_espera(pagina, 'input[type="submit"][value="Efetuar Login"]')
            except Exception:
                # Durante um POST pendente o CDP pode recusar a arvore DOM,
                # embora o botao continue clicavel pelo DrissionPage.
                clicou = False
        if not clicou:
            try:
                botao = botao_login_visivel(pagina)
                if botao:
                    botao.click()
                    clicou = True
            except (ContextLostError, ElementLostError, WaitTimeoutError, TimeoutError):
                # Navegacao ou uma atualizacao pode substituir o controle ao clicar.
                pass
            if not clicou:
                if '/acesso/pages/paginainicial.xhtml' in url_sem_espera(pagina):
                    return numero - 1
                # PrimeFaces pode remover o botao durante uma requisicao. Aguarde
                # sua volta ou a navegacao; nunca declare sucesso por sua ausencia.
                print('Botao de login ainda indisponivel; aguardando portal.', flush=True)
        limite = time.monotonic() + intervalo
        while time.monotonic() < limite:
            if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
                return numero
            time.sleep(min(0.5, max(0, limite - time.monotonic())))

    if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
        return tentativas
    raise RuntimeError(f"Portal nao confirmou o login apos {tentativas} envios limitados.")


def autenticar_contribuinte(pagina, cnpj: str, ie: str, timeout: int = 45,
                            tentativas: int = 8, tentativas_certificado: int = 5,
                            espera_politica: float = 8) -> int:
    """Autentica um contribuinte pelo formulario real observado em 13/11/2026."""
    if not re.fullmatch(r"\d{14}", cnpj):
        raise ValueError("CNPJ deve ter 14 digitos.")
    if not re.fullmatch(r"\d{8,14}", ie):
        raise ValueError("IE deve conter somente digitos (8 a 14).")
    if tentativas_certificado < 0:
        raise ValueError("Tentativas de certificado nao pode ser negativa.")
    try:
        browser_pid = int(pagina.process_id or 0)
    except (TypeError, ValueError):
        browser_pid = 0
    if browser_pid <= 0:
        raise RuntimeError('PID do Chrome não identificado; não é seguro escolher o certificado.')

    url_inicial = url_sem_espera(pagina)
    if "/acesso/pages/paginainicial.xhtml" in url_inicial:
        return 0
    if ("/acesso/pages/login/login.xhtml" not in url_inicial and
            "login-certificado.xhtml" not in url_inicial):
        pagina.get(LOGIN)
    helper = RAIZ / "certificado_chrome.ps1"
    formulario_pronto = False
    numeros_certificado = count(1) if tentativas_certificado == 0 else range(1, tentativas_certificado + 1)
    for numero in numeros_certificado:
        url_atual = url_sem_espera(pagina)
        if "login-certificado.xhtml" in url_atual:
            if formulario_certificado_visivel(pagina):
                formulario_pronto = True
                break
            limite_texto = 'sem limite' if tentativas_certificado == 0 else str(tentativas_certificado)
            print(f'Formulario do certificado vazio apos 10 s; mantendo a sessao {numero}/{limite_texto}.', flush=True)
            continue
        if "/acesso/pages/paginainicial.xhtml" in url_atual:
            return 0
        if "captcha" in titulo_sem_espera(pagina).lower():
            raise RuntimeError("Desafio de seguranca detectado antes do login por certificado.")
        if "/acesso/pages/login/login.xhtml" not in url_atual:
            # A navegacao pode ter concluido entre duas leituras do endereco.
            url_atual = url_sem_espera(pagina)
            if "login-certificado.xhtml" in url_atual:
                break
            if "/acesso/pages/paginainicial.xhtml" in url_atual:
                return 0
            raise RuntimeError("Portal saiu da pagina inicial sem abrir o login por certificado.")
        # O portal frequentemente demora para desenhar o link. Espera dez
        # segundos e relê o estado antes de considerar outra tentativa.
        limite_link = time.monotonic() + 10
        clicou = False
        erro_link = None
        while time.monotonic() < limite_link:
            try:
                clicou = clicar_css_sem_espera(pagina, 'a[title="Cetificado Digital"]')
            except RuntimeError:
                raise
            except Exception as exc:
                erro_link = type(exc).__name__
                clicou = False
            url_observada = url_sem_espera(pagina)
            if (clicou or 'login-certificado.xhtml' in url_observada or
                    '/acesso/pages/paginainicial.xhtml' in url_observada):
                break
            if 'captcha' in titulo_sem_espera(pagina).lower():
                raise RuntimeError('Desafio de seguranca detectado; aguardar validacao humana.')
            time.sleep(0.5)
        if not clicou and not hasattr(pagina, 'run_cdp'):
            try:
                link = pagina.ele('css:a[title="Cetificado Digital"]', timeout=2)
                if link:
                    link.click()
                    clicou = True
            except Exception:
                pass
        if not clicou:
            if 'login-certificado.xhtml' in url_sem_espera(pagina):
                if formulario_certificado_visivel(pagina):
                    formulario_pronto = True
                    break
                continue
            if '/acesso/pages/paginainicial.xhtml' in url_sem_espera(pagina):
                return 0
            if tentativas_certificado and numero == tentativas_certificado:
                if erro_link:
                    raise RuntimeError(f"Transicao do certificado nao confirmada: leitura da pagina falhou ({erro_link}).")
                raise RuntimeError("Link de certificado nao encontrado apos tentativas limitadas.")
            limite_texto = 'sem limite' if tentativas_certificado == 0 else str(tentativas_certificado)
            estado = 'Pagina nao respondeu' if erro_link else 'Link do certificado nao encontrado'
            print(f'{estado} por 10 s; mantendo a sessao {numero}/{limite_texto}.', flush=True)
            continue
        limite_texto = 'sem limite' if tentativas_certificado == 0 else str(tentativas_certificado)
        # Com a auto-selecao no perfil o Chrome nao abre a janela
        # do A1 e a navegacao segue sozinha; so recorre ao UI Automation se a
        # pagina continuar parada no login.
        destino = aguardar_saida_do_login(pagina, espera_politica)
        if destino == 'inicial':
            return 0
        if destino == 'certificado':
            print('A1 entregue pelo Chrome sem janela de selecao.', flush=True)
            if formulario_certificado_visivel(pagina):
                formulario_pronto = True
                break
            print(f'Formulario do certificado vazio apos 10 s; mantendo a sessao {numero}/{limite_texto}.', flush=True)
            continue
        print(f"Selecao do certificado pela janela do Chrome: tentativa {numero}/{limite_texto}.", flush=True)
        try:
            resultado = subprocess.run(
                POWERSHELL + [str(helper), "-Cnpj", cnpj, "-BrowserPid", str(browser_pid),
                              "-TimeoutSegundos", "20"],
                capture_output=True, text=True, timeout=35,
            )
        except subprocess.TimeoutExpired:
            resultado = None
        except OSError as exc:
            # powershell.exe ausente/bloqueado: registra e segue verificando a pagina.
            resultado = subprocess.CompletedProcess([], 1, '', f'PowerShell nao executou: {type(exc).__name__}')
        if (resultado is not None and resultado.returncode == 0 and
                'CERTIFICADO_CONFIRMADO' in (getattr(resultado, 'stdout', '') or '')):
            print('A1 selecionado; OK da janela do Chrome acionado.', flush=True)
        elif resultado is None:
            print('Seletor do A1 nao respondeu em 35 s; verificando navegacao antes de repetir.', flush=True)
        else:
            print(f'Janela do A1 nao confirmada: {resumo_erro_powershell(resultado)}', flush=True)
        limite_navegacao = time.monotonic() + (10 if resultado is not None and resultado.returncode == 0 else 1)
        while time.monotonic() < limite_navegacao:
            if "login-certificado.xhtml" in url_sem_espera(pagina):
                break
            if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
                return 0
            if "captcha" in titulo_sem_espera(pagina).lower():
                raise RuntimeError("Desafio de seguranca detectado apos selecionar certificado.")
            time.sleep(0.5)
        if 'login-certificado.xhtml' in url_sem_espera(pagina):
            if formulario_certificado_visivel(pagina):
                formulario_pronto = True
                break
            print(f'Formulario vazio apos OK do A1; repetindo selecao na mesma sessao {numero}/{limite_texto}.', flush=True)
            continue
        if resultado is not None and resultado.returncode != 0:
            detalhe = (getattr(resultado, 'stderr', '') or getattr(resultado, 'stdout', '') or '').lower()
            if 'nao encontrado de forma unica' in detalhe or 'mais de um' in detalhe:
                raise RuntimeError("Selecao de certificado ambigua; interrompida sem escolher outro A1.")
        # Mesmo que o helper tenha expirado, somente repetir se a pagina
        # ainda estiver no login inicial. Uma navegacao tardia e aceita.

    if "/acesso/pages/paginainicial.xhtml" in url_sem_espera(pagina):
        return 0
    if not formulario_pronto:
        raise RuntimeError("O portal nao exibiu o formulario por certificado apos as tentativas limitadas.")

    limite = time.monotonic() + timeout
    seletor = pagina.ele('css:div[id="formCertificado:selectTipoUsuario"]', timeout=8)
    opcao = pagina.ele('css:li[id="formCertificado:selectTipoUsuario_3"]', timeout=8)
    if not seletor or not opcao or opcao.text.strip() != "Contribuinte MT":
        raise RuntimeError("Opcao Contribuinte MT nao encontrada no formulario.")
    seletor.click()
    opcao.click()

    campo = None
    while time.monotonic() < limite:
        try:
            candidato = pagina.ele('css:input[id="formCertificado:inputLogin"]', timeout=2)
            if candidato and candidato.states.is_displayed:
                campo = candidato
                break
        except Exception:
            pass  # Atualizacao AJAX ainda em andamento.
        time.sleep(0.5)
    if campo is None:
        raise RuntimeError("Campo de inscricao estadual nao apareceu.")
    campo.input(ie)
    # O PrimeFaces pode substituir o formulario logo apos a escolha do perfil.
    # Aguarda a atualizacao antes de enviar, e confirma a navegacao de fato.
    time.sleep(1.5)
    try:
        return enviar_login_com_retentativas(pagina, ie, tentativas=tentativas)
    except ContextLostError:
        # O navegador destrói o contexto JavaScript ao concluir a navegação.
        # Confirme a URL diretamente antes de classificar a tentativa como falha.
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            if '/acesso/pages/paginainicial.xhtml' in url_sem_espera(pagina):
                return 0
            time.sleep(0.5)
        raise
