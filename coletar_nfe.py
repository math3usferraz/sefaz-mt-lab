"""Coleta NF-e modelo 55 no Acesso Web da SEFAZ-MT.

Seletores observados no portal autenticado em 13/11/2026. A rotina cria uma
pasta vazia por execucao e so aceita arquivos exportados durante essa execucao.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import socket
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import xlrd
from DrissionPage import ChromiumOptions, ChromiumPage

from extrair_chaves import chave_valida, extrair_do_arquivo, salvar_csv
from main import aguardar_liberacao_portal, aguardando_download
from sefaz_login import LOGIN, autenticar_contribuinte, titulo_sem_espera, url_sem_espera


RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "saida" / "coletas"
ROTA_CONSULTA = "/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml"
TIPOS = {"emitidas": 0, "recebidas": 1}


def _digitos(valor: object) -> str:
    return re.sub(r"\D", "", str(valor))


def validar_planilha(arquivo: Path, cnpj: str, ie: str, inicio: datetime,
                     fim: datetime, tipo: str) -> dict:
    """Confere formato, empresa, periodo, modelo, DV e linhas do XLS original."""
    if tipo not in TIPOS:
        raise ValueError('Tipo de consulta NF-e invalido.')
    dados = arquivo.read_bytes()
    if arquivo.suffix.lower() != ".xls" or not dados.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise ValueError("Exportacao nao e uma planilha XLS binaria original.")
    aba = xlrd.open_workbook(file_contents=dados).sheet_by_index(0)
    if aba.nrows < 8 or aba.ncols < 18:
        raise ValueError("Planilha sem a estrutura esperada da consulta de NF-e.")
    cabecalho = [str(v).strip().upper() for v in aba.row_values(6)]
    if not (cabecalho[3].startswith("CHAVE DE ACESSO") and
            cabecalho[9] == "CNPJ/CPF" and cabecalho[14] == "CNPJ/CPF" and
            cabecalho[11].startswith("INSCRI") and cabecalho[15].startswith("INSCRI")):
        raise ValueError("Colunas da planilha nao correspondem ao relatorio observado.")

    indice_cnpj, indice_ie = (9, 11) if tipo == "emitidas" else (14, 15)
    chaves: list[str] = []
    situacoes: Counter[str] = Counter()
    datas: list[datetime] = []
    for numero_linha in range(7, aba.nrows):
        linha = aba.row_values(numero_linha)
        chave = str(linha[3]).strip()
        if not chave:
            continue
        if not chave_valida(chave) or chave[20:22] != "55":
            raise ValueError(f"Chave NF-e invalida na linha {numero_linha + 1}.")
        if chave[6:20] != _digitos(linha[9]):
            raise ValueError(f"Emitente da chave diverge na linha {numero_linha + 1}.")
        if _digitos(linha[indice_cnpj]) != cnpj or _digitos(linha[indice_ie]) != ie:
            raise ValueError(f"Empresa divergente na linha {numero_linha + 1}.")
        try:
            emissao = datetime.strptime(str(linha[0]).strip()[:10], "%d/%m/%Y")
        except ValueError as exc:
            raise ValueError(f"Data de emissao invalida na linha {numero_linha + 1}.") from exc
        if not inicio.date() <= emissao.date() <= fim.date():
            raise ValueError(f"Nota fora do periodo na linha {numero_linha + 1}.")
        if chave[2:6] != emissao.strftime("%y%m"):
            raise ValueError(f"Mes da chave diverge da emissao na linha {numero_linha + 1}.")
        chaves.append(chave)
        datas.append(emissao)
        situacoes[str(linha[8]).strip().upper()] += 1

    if not chaves:
        raise ValueError("Planilha exportada sem linhas de NF-e.")
    extraidas, avisos = extrair_do_arquivo(arquivo)
    if avisos or set(extraidas) != set(chaves):
        raise ValueError("Extrator generico divergiu das chaves da coluna fiscal.")
    return {
        "tipo": tipo,
        "periodo_inicial": inicio.date().isoformat(),
        "periodo_final": fim.date().isoformat(),
        "linhas": len(chaves),
        "chaves_unicas": len(set(chaves)),
        "duplicadas": len(chaves) - len(set(chaves)),
        "situacoes": dict(situacoes),
        "primeira_emissao": min(datas).date().isoformat(),
        "ultima_emissao": max(datas).date().isoformat(),
        "sha256_original": hashlib.sha256(dados).hexdigest(),
        "chaves": sorted(set(chaves)),
    }


def _frame_consulta(pagina, timeout: int = 30):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            frame = pagina.get_frame("iframeCenter")
            if ROTA_CONSULTA.lower() in frame.url.lower():
                return frame
        except Exception:
            pass  # O iframe e substituido durante a navegacao.
        time.sleep(0.5)
    raise RuntimeError("A pagina de consulta de NF-e nao carregou no iframe.")


def abrir_consulta(pagina, ie: str):
    limite = time.monotonic() + 30
    opcoes = []
    while time.monotonic() < limite:
        try:
            menu = pagina.get_frame("iframeMenu")
            opcoes = [a for a in menu.eles("tag:a")
                      if a.text.strip() == "Consulta de NF-e Emitida/Recebida"
                      and ROTA_CONSULTA in (a.attr("onclick") or "")]
            if len(opcoes) == 1:
                break
        except Exception:
            pass  # O menu e refeito pelo portal apos o login.
        time.sleep(0.5)
    if len(opcoes) != 1:
        raise RuntimeError("Item de consulta de NF-e nao apareceu de forma unica no menu.")
    frame = None
    for tentativa in range(1, 6):
        opcoes[0].click(by_js=True)
        try:
            limite_tela = time.monotonic() + 10
            while time.monotonic() < limite_tela:
                frame = _frame_consulta(pagina, timeout=2)
                try:
                    texto = frame.run_js("return document.body ? document.body.innerText : ''") or ''
                except Exception:
                    # O iframe pode trocar de contexto antes de montar o body.
                    time.sleep(0.5)
                    continue
                if not _estado_resultado(texto) and 'Dados para Consulta' in texto:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Tela anterior da consulta permaneceu aberta.')
            break
        except RuntimeError:
            if tentativa == 5:
                raise RuntimeError('Consulta NF-e nao abriu apos 5 cliques limitados no menu.')
            print(f'Menu NF-e sem navegacao em 10 s; tentativa {tentativa}/5.', flush=True)
            menu = pagina.get_frame('iframeMenu')
            opcoes = [a for a in menu.eles('tag:a')
                      if a.text.strip() == 'Consulta de NF-e Emitida/Recebida'
                      and ROTA_CONSULTA in (a.attr('onclick') or '')]
            if len(opcoes) != 1:
                raise RuntimeError('Item de consulta de NF-e mudou durante retentativa.')
    texto = frame.run_js("return document.body.innerText")
    if f"{ie} - " not in texto or "Dados para Consulta" not in texto:
        raise RuntimeError("Consulta nao identifica a IE autenticada.")
    return frame


def _estado_resultado(texto: str) -> str | None:
    if 'Nenhum registro encontrado' in texto or 'Nenhuma NF-e encontrada' in texto:
        return 'VAZIO'
    if 'Resultado da Consulta' in texto:
        return 'RESULTADO'
    return None


def consultar(frame, tipo: str, inicio: datetime, fim: datetime) -> str:
    if tipo not in TIPOS:
        raise ValueError('Tipo de consulta NF-e invalido.')
    # Uma tela antiga pode continuar no iframe mesmo apos clicar no menu.
    # Nao aceitar esse resultado como resposta aos novos filtros.
    if _estado_resultado(frame.run_js('return document.body.innerText') or ''):
        raise RuntimeError('Consulta NF-e contem resultado anterior; reabra a tela antes de consultar.')
    campo_inicio = frame.ele('css:input[id="j_idt14:dataInicial_input"]', timeout=8)
    campo_fim = frame.ele('css:input[id="j_idt14:dataFinal_input"]', timeout=8)
    rotulo = frame.ele(f'css:label[for="j_idt14:tipoCons:{TIPOS[tipo]}"]', timeout=8)
    if not campo_inicio or not campo_fim or not rotulo:
        raise RuntimeError("Filtros da consulta mudaram no portal.")
    rotulo.click()
    time.sleep(1.5)  # O radio pode substituir os campos durante o AJAX.
    campo_inicio = frame.ele('css:input[id="j_idt14:dataInicial_input"]', timeout=8)
    campo_fim = frame.ele('css:input[id="j_idt14:dataFinal_input"]', timeout=8)
    if not campo_inicio or not campo_fim:
        raise RuntimeError('Campos de data desapareceram apos selecionar o tipo de consulta.')
    campo_inicio.input(inicio.strftime("%d/%m/%Y"))
    campo_fim.input(fim.strftime("%d/%m/%Y"))
    valores = frame.run_js("""return [
      document.getElementById('j_idt14:dataInicial_input').value,
      document.getElementById('j_idt14:dataFinal_input').value,
      document.getElementById('j_idt14:tipoCons:%s').checked,
      document.getElementById('j_idt14:siglaUF_input').selectedOptions[0].text,
      document.getElementById('j_idt14:sitcNFe_input').selectedOptions[0].text
    ]""" % TIPOS[tipo])
    if valores != [inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y"), True, "Todas", "Todas"]:
        raise RuntimeError("Filtros nao correspondem ao periodo, tipo ou situacao solicitados.")
    if _estado_resultado(frame.run_js('return document.body.innerText') or ''):
        raise RuntimeError('Resultado NF-e apareceu antes do envio da consulta; execucao interrompida.')
    for tentativa in range(1, 6):
        botao = frame.ele('css:button[id="j_idt14:btnConsEmitReceb"]', timeout=3)
        if not botao:
            raise RuntimeError('Botao Consultar desapareceu sem resultado confirmado.')
        botao.click()
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            try:
                texto = frame.run_js('return document.body.innerText') or ''
                if 'captcha' in texto.lower() or 'acesso negado' in texto.lower():
                    raise RuntimeError('Desafio ou bloqueio no portal; consulta interrompida.')
                estado = _estado_resultado(texto)
                if estado:
                    return estado
            except RuntimeError:
                raise
            except Exception:
                pass  # O AJAX substitui o iframe durante o processamento.
            time.sleep(0.5)
        print(f'Consulta {tipo}: sem resultado em 10 s; tentativa {tentativa}/5.', flush=True)
    raise RuntimeError('Consulta sem resultado apos 5 envios limitados.')


def exportar(pagina, pasta: Path, timeout_download: int) -> Path:
    limite = time.monotonic() + 60
    while time.monotonic() < limite:
        try:
            frame = _frame_consulta(pagina, timeout=3)
            texto = frame.run_js("return document.body.innerText")
            links = [a for a in frame.eles("tag:a") if a.text.strip() == "Exportar para Excel"]
            if "Resultado da Consulta" in texto and len(links) == 1:
                pasta.mkdir(parents=True, exist_ok=False)
                pagina.set.download_path(str(pasta))
                inicio_download = time.time()
                for tentativa in range(1, 4):
                    links[0].click()
                    arquivo = aguardando_download(pasta, inicio_download, min(10, timeout_download))
                    if arquivo is not None:
                        return arquivo
                    # Um download em curso nao deve receber segundo clique.
                    if list(pasta.glob('*.crdownload')):
                        arquivo = aguardando_download(pasta, inicio_download, timeout_download)
                        if arquivo is not None:
                            return arquivo
                        raise RuntimeError('Download iniciado mas nao concluido no prazo.')
                    frame = _frame_consulta(pagina, timeout=3)
                    texto = frame.run_js('return document.body.innerText') or ''
                    if 'Resultado da Consulta' not in texto:
                        raise RuntimeError('Resultado desapareceu durante a exportacao.')
                    links = [a for a in frame.eles('tag:a') if a.text.strip() == 'Exportar para Excel']
                    if len(links) != 1:
                        raise RuntimeError('Link de exportacao nao esta mais disponivel de forma unica.')
                    print(f'Excel sem download em 10 s; tentativa {tentativa}/3.', flush=True)
                raise RuntimeError('Exportacao clicada 3 vezes sem arquivo novo.')
            if "Nenhum registro encontrado" in texto or "Nenhuma NF-e encontrada" in texto:
                raise RuntimeError("Portal informou ausencia de notas; nao ha XLS para exportar.")
        except RuntimeError:
            raise
        except Exception:
            pass  # Resultado AJAX ainda em carregamento.
        time.sleep(0.7)
    raise RuntimeError("Resultado e botao Exportar para Excel nao apareceram.")


def coletar_tipo(pagina, base: Path, cnpj: str, ie: str, inicio: datetime,
                 fim: datetime, tipo: str, timeout_download: int) -> dict:
    frame = abrir_consulta(pagina, ie)
    estado = consultar(frame, tipo, inicio, fim)
    if estado == 'VAZIO':
        pasta = base / tipo
        pasta.mkdir(parents=True, exist_ok=False)
        salvar_csv([], pasta / 'chaves_extraidas.csv')
        resultado = {
            'tipo': tipo, 'periodo_inicial': inicio.date().isoformat(),
            'periodo_final': fim.date().isoformat(), 'linhas': 0,
            'chaves_unicas': 0, 'duplicadas': 0, 'situacoes': {},
            'status': 'SEM_REGISTROS', 'csv_chaves': 'chaves_extraidas.csv',
        }
        (pasta / 'manifesto.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                               encoding='utf-8')
        return resultado
    arquivo = exportar(pagina, base / tipo, timeout_download)
    resultado = validar_planilha(arquivo, cnpj, ie, inicio, fim, tipo)
    chaves = resultado.pop("chaves")
    csv = arquivo.parent / "chaves_extraidas.csv"
    salvar_csv(chaves, csv)
    resultado["arquivo_original"] = arquivo.name
    resultado["csv_chaves"] = csv.name
    (arquivo.parent / "manifesto.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta automatica de NF-e 55 na SEFAZ-MT")
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--ie", required=True)
    parser.add_argument("--inicio", required=True, help="DD/MM/AAAA")
    parser.add_argument("--fim", required=True, help="DD/MM/AAAA")
    parser.add_argument("--tipo", choices=["emitidas", "recebidas", "ambas"], default="ambas")
    parser.add_argument("--tentativas-login", type=int, default=0,
                        help="0 repete ate o portal responder; outro valor limita os envios")
    parser.add_argument("--tentativas-certificado", type=int, default=0,
                        help="0 repete a selecao do A1 ate o formulario abrir")
    parser.add_argument("--timeout-download", type=int, default=180)
    parser.add_argument("--porta", type=int, default=9331)
    parser.add_argument("--perfil", default="", help="Perfil Chrome existente dentro de saida/perfis")
    args = parser.parse_args()
    try:
        inicio = datetime.strptime(args.inicio, "%d/%m/%Y")
        fim = datetime.strptime(args.fim, "%d/%m/%Y")
    except ValueError:
        parser.error("Datas devem estar em DD/MM/AAAA")
    if inicio > fim or (inicio.year, inicio.month) != (fim.year, fim.month):
        parser.error("Informe um periodo dentro de uma unica competencia mensal")
    if not re.fullmatch(r"\d{14}", args.cnpj) or not re.fullmatch(r"\d{9}", args.ie):
        parser.error("CNPJ deve ter 14 digitos e IE de MT deve ter 9 digitos")
    if args.tentativas_login < 0 or args.tentativas_certificado < 0 or args.timeout_download < 1:
        parser.error("Limites de tentativas ou download invalidos")

    base_empresa = SAIDA / args.cnpj / f"{inicio:%Y-%m}"
    base_empresa.mkdir(parents=True, exist_ok=True)
    base = base_empresa / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{secrets.token_hex(4)}"
    base.mkdir(exist_ok=False)
    perfis = (RAIZ / "saida" / "perfis").resolve()
    perfis.mkdir(parents=True, exist_ok=True)
    if args.perfil:
        perfil = Path(args.perfil).resolve()
        if not perfil.is_relative_to(perfis) or not perfil.is_dir():
            parser.error("--perfil deve apontar para um perfil existente em saida/perfis")
    else:
        # Um perfil novo evita reutilizar estado de autenticacao anterior.
        # O perfil anterior permanece intacto; toda a coleta usa esta sessao.
        perfil = perfis / f'empresa_{args.cnpj}_{base.name}'
        perfil.mkdir(exist_ok=False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste_porta:
        teste_porta.settimeout(1)
        if teste_porta.connect_ex(('127.0.0.1', args.porta)) == 0:
            parser.error('Porta de depuracao ja esta em uso; escolha outra com --porta')
    opcoes = ChromiumOptions()
    opcoes.set_timeouts(base=10, page_load=10, script=10)
    opcoes.set_local_port(args.porta)
    opcoes.set_argument(f"--user-data-dir={perfil}")
    opcoes.set_argument("--start-maximized")
    pagina = ChromiumPage(addr_or_opts=opcoes)
    relatorio: dict = {"status": "EM_ANDAMENTO", "tipos": {}, "pasta": str(base)}
    try:
        pagina.get(LOGIN, timeout=10)
        estado = aguardar_liberacao_portal(pagina, timeout=120)
        if estado["status"] != "PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE":
            raise RuntimeError(f"Portal indisponivel ou desafio de seguranca: {estado['status']}")
        envios = autenticar_contribuinte(
            pagina, args.cnpj, args.ie, tentativas=args.tentativas_login,
            tentativas_certificado=args.tentativas_certificado,
        )
        print(f"Login confirmado apos {envios} envio(s).", flush=True)
        tipos = ["recebidas", "emitidas"] if args.tipo == "ambas" else [args.tipo]
        for tipo in tipos:
            resultado = coletar_tipo(pagina, base, args.cnpj, args.ie, inicio, fim,
                                    tipo, args.timeout_download)
            relatorio["tipos"][tipo] = resultado
            print(f"{tipo}: {resultado['chaves_unicas']} chaves NF-e; original preservado.", flush=True)
        relatorio["status"] = "CONCLUIDO"
        return 0
    except Exception as exc:
        relatorio["status"] = "FALHA"
        relatorio["motivo"] = f"{type(exc).__name__}: {exc}"
        try:
            url = urlsplit(url_sem_espera(pagina))
            relatorio["pagina_final"] = {
                "titulo": titulo_sem_espera(pagina),
                "url_final": urlunsplit((url.scheme, url.netloc, url.path.split(';', 1)[0], '', '')),
            }
        except Exception:
            pass
        print(f"FALHA: {relatorio['motivo']}", file=sys.stderr, flush=True)
        return 1
    finally:
        (base / "relatorio.json").write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            pagina.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
