"""Coleta CT-e e CT-e OS no portal ja autenticado da SEFAZ-MT.

Este modulo nao abre navegador nem seleciona certificado. Ele foi feito para
ser chamado na mesma ``ChromiumPage`` que ja coletou NF-e, evitando um novo
login para cada tipo de documento.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from extrair_chaves import extrair_do_arquivo, salvar_csv
from main import aguardando_download


CONSULTAS = {
    'cte': {
        'menu': 'Consulta CT-e Emitidos/Recebidos',
        'modelos': {'57'},
        'tipos': ('Emissor', 'Tomador'),
    },
    'cteos': {
        'menu': 'Consulta Emitidos/Recebidos CTe-OS',
        'modelos': {'67'},
        'tipos': ('Emissor',),
    },
}


def schema_formulario(frame) -> dict:
    """Le somente nomes e opcoes do formulario realmente aberto."""
    dados = frame.run_js("""return {
      selects: [...document.querySelectorAll('select')].map(s => ({
        name: s.name, id: s.id,
        options: [...s.options].map(o => ({value: o.value, text: o.text.trim()}))
      })),
      inputs: [...document.querySelectorAll('input')].map(i => ({
        name: i.name, id: i.id, type: i.type, value: i.type === 'submit' ? i.value : ''
      }))
    }""")
    if not isinstance(dados, dict):
        raise RuntimeError('Formulario CT-e nao retornou estrutura legivel.')
    return dados


def validar_schema(schema: dict, tipo: str) -> str:
    """Valida campos observados e devolve o valor real da opcao solicitada."""
    selects = {str(item.get('name') or item.get('id')): item
               for item in schema.get('selects', []) if isinstance(item, dict)}
    entradas = {str(item.get('name') or item.get('id')): item
                for item in schema.get('inputs', []) if isinstance(item, dict)}
    if not {'dataInicial', 'dataFinal', 'btnConsultar'} <= set(entradas):
        raise RuntimeError('Campos de data ou botao CT-e mudaram no portal.')
    consulta = selects.get('tipoConsulta')
    if not consulta:
        raise RuntimeError('Campo tipoConsulta CT-e nao encontrado no portal.')
    opcoes = {str(opcao.get('text') or '').strip(): str(opcao.get('value') or '')
              for opcao in consulta.get('options', []) if isinstance(opcao, dict)}
    valor = opcoes.get(tipo)
    if not valor or valor == '-1':
        raise RuntimeError(f'Tipo CT-e {tipo!r} nao disponivel no formulario aberto.')
    return valor


def abrir_consulta(pagina, consulta: str):
    if consulta not in CONSULTAS:
        raise ValueError('Consulta CT-e invalida.')
    alvo = CONSULTAS[consulta]['menu']
    limite = time.monotonic() + 30
    while time.monotonic() < limite:
        try:
            menu = pagina.get_frame('iframeMenu')
            opcoes = [a for a in menu.eles('tag:a') if a.text.strip() == alvo]
            if len(opcoes) != 1:
                raise RuntimeError(f'Menu {alvo!r} nao apareceu de forma unica.')
            opcoes[0].click(by_js=True)
            break
        except RuntimeError:
            raise
        except Exception:
            time.sleep(.5)
    else:
        raise RuntimeError(f'Menu {alvo!r} nao carregou.')

    limite = time.monotonic() + 30
    while time.monotonic() < limite:
        try:
            frame = pagina.get_frame('iframeCenter')
            schema = schema_formulario(frame)
            if any(item.get('name') == 'tipoConsulta' for item in schema.get('selects', [])):
                return frame
        except Exception:
            pass
        time.sleep(.5)
    raise RuntimeError(f'Formulario {alvo!r} nao carregou no iframe.')


def consultar(frame, tipo: str, inicio: datetime, fim: datetime) -> None:
    valor_tipo = validar_schema(schema_formulario(frame), tipo)
    inicio_ele = frame.ele('css:input[name="dataInicial"]', timeout=5)
    fim_ele = frame.ele('css:input[name="dataFinal"]', timeout=5)
    tipo_ele = frame.ele('css:select[name="tipoConsulta"]', timeout=5)
    botao = frame.ele('css:input[name="btnConsultar"]', timeout=5)
    if not all((inicio_ele, fim_ele, tipo_ele, botao)):
        raise RuntimeError('Elementos CT-e observados desapareceram antes da consulta.')
    inicio_ele.input(inicio.strftime('%d/%m/%Y'))
    fim_ele.input(fim.strftime('%d/%m/%Y'))
    tipo_ele.select.by_value(valor_tipo)
    botao.click()

    limite = time.monotonic() + 30
    while time.monotonic() < limite:
        try:
            texto = frame.run_js('return document.body.innerText') or ''
            if 'captcha' in texto.lower() or 'acesso negado' in texto.lower():
                raise RuntimeError('Desafio ou bloqueio no portal; consulta CT-e interrompida.')
            if any(termo in texto.lower() for termo in ('resultado', 'nenhum registro', 'exportar')):
                return
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(.5)
    raise RuntimeError('Consulta CT-e nao confirmou resultado em 30 segundos.')


def _controle_exportacao(frame):
    candidatos = []
    for elemento in [*frame.eles('tag:a'), *frame.eles('tag:input'), *frame.eles('tag:button')]:
        texto = ' '.join(filter(None, [elemento.text.strip(), str(elemento.attr('value') or '').strip()])).lower()
        if 'excel' in texto or '.xls' in texto:
            candidatos.append(elemento)
    if len(candidatos) != 1:
        raise RuntimeError('Controle de exportacao CT-e nao encontrado de forma unica.')
    return candidatos[0]


def exportar(frame, pagina, pasta: Path, timeout: int = 180) -> Path:
    controle = _controle_exportacao(frame)
    pasta.mkdir(parents=True, exist_ok=False)
    pagina.set.download_path(str(pasta))
    inicio = time.time()
    controle.click()
    arquivo = aguardando_download(pasta, inicio, timeout)
    if arquivo is None:
        raise RuntimeError('Exportacao CT-e nao produziu arquivo novo no prazo.')
    return arquivo


def coletar_tipo(pagina, base: Path, consulta: str, tipo: str,
                 inicio: datetime, fim: datetime) -> dict:
    if consulta not in CONSULTAS or tipo not in CONSULTAS[consulta]['tipos']:
        raise ValueError('Consulta ou tipo CT-e fora do escopo autorizado.')
    frame = abrir_consulta(pagina, consulta)
    consultar(frame, tipo, inicio, fim)
    pasta = base / consulta / tipo.lower()
    arquivo = exportar(frame, pagina, pasta)
    chaves, avisos = extrair_do_arquivo(arquivo, CONSULTAS[consulta]['modelos'])
    if not chaves:
        raise RuntimeError('Exportacao CT-e sem chaves validas do modelo esperado.')
    salvar_csv(chaves, pasta / 'chaves_extraidas.csv')
    dados = {
        'consulta': consulta, 'tipo': tipo, 'modelo': next(iter(CONSULTAS[consulta]['modelos'])),
        'periodo_inicial': inicio.date().isoformat(), 'periodo_final': fim.date().isoformat(),
        'chaves_unicas': len(chaves), 'arquivo_original': arquivo.name,
        'sha256_original': hashlib.sha256(arquivo.read_bytes()).hexdigest(), 'avisos': avisos,
    }
    (pasta / 'manifesto.json').write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
    return dados
