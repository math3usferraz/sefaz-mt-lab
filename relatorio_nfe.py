"""Gera relatório por produto a partir dos XMLs de NF-e já recuperados.

As colunas seguem a planilha de referência. Nenhuma linha da referência é usada
como fonte de notas; campos ausentes no XML permanecem vazios.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from validar_xml import child, local_name, path_text, validar_nfe_completa


CABECALHOS = (
    'DATA NF', 'NÚMERO', 'TOTAL NF', 'CHAVE NFe', 'CNPJ REMET.', 'REMETENTE',
    'CNPJ/CPF DEST.', 'DESTINATÁRIO', 'TOTAL ICMS ST', 'UF DESTINATARIO',
    'UF EMITENTE', 'IND_OP', 'COD_NCM', 'CÓDIGO PRODUTO', 'N_ITEM', 'DESCRIÇÃO',
    'CFOP', 'CST IBS CBS', 'cClassTrib', 'BC IBS', '%IBS', 'Vlr.IBS', 'BC CBS',
    '%CBS', 'Vlr.CBS', 'CST ICMS', 'CSOSN', 'QUANTIDADE', 'P UND', 'TOTAL',
    'DESCONTO', 'MVA', 'PERC. REDUCAO', 'BASE CALCULO ICMS ST', 'ALIQ. ICMSST',
    'ICMS ST', 'BC FCP ST', 'ALIQ. FCP ST', 'VL. ICMS FCP ST', 'V. TOTAL TRIB.',
    'ICMS DA OP.', 'V_BC_ICMSST_RET', 'V_ICMSST_RET', 'PERC. ICMS DIF.',
    'VL ICMS DIF', 'V. ICMS SIMPLES NAC.', 'BASE FCP', 'ALIQ. FCP', 'V. FCP',
    'V. IPI', 'FRETE', 'V. OUTRAS DESP. ACESSÓRIAS',
    'CRT (REGIME TRIBUTÁRIO)', 'CEST',
)
NUMERICAS = {3, 9, 20, 21, 22, 23, 24, 25, 28, 29, 30, 31, 32, 33, 34,
             35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
             50, 51, 52}


def _num(texto: str) -> Decimal | None:
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation as erro:
        raise ValueError('Valor numérico inválido no XML') from erro
    if not valor.is_finite():
        raise ValueError('Valor numérico não finito no XML')
    return valor


def _data(texto: str) -> date | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError as erro:
        raise ValueError('Data de emissão inválida no XML') from erro


def _primeiro_texto(elemento: ET.Element, *caminhos: tuple[str, ...]) -> str:
    return next((valor for caminho in caminhos if (valor := path_text(elemento, *caminho))), '')


def _item_numero(item: ET.Element) -> str:
    return item.attrib.get('nItem') or path_text(item, 'nItem')


def extrair_linhas(dados: bytes, chave: str, cnpj_empresa: str, tipo: str) -> list[list]:
    validacao = validar_nfe_completa(dados, chave, cnpj_empresa=cnpj_empresa, tipo=tipo)
    if validacao.status not in {'VALIDO_ESTRUTURAL', 'DADOS_FISCAIS_CONFERIDOS'}:
        raise ValueError(f'XML recusado: {validacao.status}: {validacao.motivo}')
    raiz = ET.fromstring(dados)
    nota = child(raiz, 'NFe')
    inf = child(nota, 'infNFe')
    linhas = []
    for item in inf:
        if local_name(item.tag) != 'det':
            continue
        imposto = child(item, 'imposto')
        icms = child(imposto, 'ICMS')
        grupo_icms = next(iter(icms), None) if icms is not None else None
        ibs = child(imposto, 'IBSCBS')
        grupo_ibs = child(ibs, 'gIBSCBS') if ibs is not None else None
        ipi = child(imposto, 'IPI')
        grupo_ipi = next((grupo for grupo in ipi if path_text(grupo, 'vIPI')), None) if ipi is not None else None
        linha = [None] * len(CABECALHOS)

        def por_coluna(coluna: int, valor):
            linha[coluna - 1] = valor

        def texto(coluna: int, elemento: ET.Element, *caminho: str):
            por_coluna(coluna, path_text(elemento, *caminho) or None)

        def numero(coluna: int, elemento: ET.Element, *caminho: str):
            por_coluna(coluna, _num(path_text(elemento, *caminho)))

        por_coluna(1, _data(_primeiro_texto(inf, ('ide', 'dhEmi'), ('ide', 'dEmi'))))
        texto(2, inf, 'ide', 'nNF')
        numero(3, inf, 'total', 'ICMSTot', 'vNF')
        por_coluna(4, chave)
        texto(5, inf, 'emit', 'CNPJ')
        texto(6, inf, 'emit', 'xNome')
        por_coluna(7, _primeiro_texto(inf, ('dest', 'CNPJ'), ('dest', 'CPF')) or None)
        texto(8, inf, 'dest', 'xNome')
        numero(9, inf, 'total', 'ICMSTot', 'vST')
        texto(10, inf, 'dest', 'enderDest', 'UF')
        texto(11, inf, 'emit', 'enderEmit', 'UF')
        texto(12, inf, 'ide', 'tpNF')
        texto(13, item, 'prod', 'NCM')
        texto(14, item, 'prod', 'cProd')
        por_coluna(15, _item_numero(item))
        texto(16, item, 'prod', 'xProd')
        texto(17, item, 'prod', 'CFOP')
        if ibs is not None:
            texto(18, ibs, 'CST')
            texto(19, ibs, 'cClassTrib')
        if grupo_ibs is not None:
            numero(20, grupo_ibs, 'vBC')
            # A nota pode ter alíquotas estaduais e municipais diferentes;
            # não inventar uma alíquota única para a coluna %IBS.
            numero(22, grupo_ibs, 'vIBS')
            numero(23, grupo_ibs, 'vBC')
            numero(24, grupo_ibs, 'gCBS', 'pCBS')
            numero(25, grupo_ibs, 'gCBS', 'vCBS')
        if grupo_icms is not None:
            texto(26, grupo_icms, 'CST')
            texto(27, grupo_icms, 'CSOSN')
        numero(28, item, 'prod', 'qCom')
        numero(29, item, 'prod', 'vUnCom')
        numero(30, item, 'prod', 'vProd')
        numero(31, item, 'prod', 'vDesc')
        if grupo_icms is not None:
            for coluna, campo in ((32, 'pMVAST'), (33, 'pRedBCST'),
                                  (34, 'vBCST'), (35, 'pICMSST'), (36, 'vICMSST'),
                                  (37, 'vBCFCPST'), (38, 'pFCPST'), (39, 'vFCPST'),
                                  (41, 'vICMSOp'), (42, 'vBCSTRet'), (43, 'vICMSSTRet'),
                                  (44, 'pDif'), (45, 'vICMSDif'), (46, 'vCredICMSSN'),
                                  (47, 'vBCFCP'), (48, 'pFCP'), (49, 'vFCP')):
                numero(coluna, grupo_icms, campo)
        numero(40, imposto, 'vTotTrib')
        if grupo_ipi is not None:
            numero(50, grupo_ipi, 'vIPI')
        numero(51, item, 'prod', 'vFrete')
        numero(52, item, 'prod', 'vOutro')
        texto(53, inf, 'emit', 'CRT')
        texto(54, item, 'prod', 'CEST')
        linhas.append(linha)
    return linhas


def reunir_xmls(diretorio: Path, cnpj_empresa: str, *, tipo_filtro: str | None = None,
                permitir_vazio: bool = False) -> tuple[list[list], dict]:
    if not re.fullmatch(r'\d{14}', cnpj_empresa):
        raise ValueError('CNPJ da empresa deve conter 14 dígitos')
    if tipo_filtro not in (None, 'emitidas', 'recebidas'):
        raise ValueError('Tipo de operação inválido')
    arquivos = sorted(diretorio.rglob('*.xml'))
    if not arquivos and not permitir_vazio:
        raise ValueError('Nenhum XML encontrado no diretório informado')
    linhas = []
    vistos = {}
    por_tipo = {'recebidas': 0, 'emitidas': 0}
    for arquivo in arquivos:
        nome_pasta = arquivo.parent.name
        if not nome_pasta.startswith('nfe_'):
            continue
        tipo = 'emitidas' if nome_pasta.startswith('nfe_emitidas') else (
            'recebidas' if nome_pasta.startswith('nfe_recebidas') else None)
        if tipo is None:
            continue
        if tipo_filtro and tipo != tipo_filtro:
            continue
        chave = arquivo.stem
        dados = arquivo.read_bytes()
        digest = hashlib.sha256(dados).hexdigest()
        if chave in vistos:
            if vistos[chave] != digest:
                raise ValueError('Duas versões diferentes para a mesma chave; conferir antes de gerar relatório')
            continue
        novas = extrair_linhas(dados, chave, cnpj_empresa, tipo)
        vistos[chave] = digest
        por_tipo[tipo] += 1
        linhas.extend(novas)
    if not linhas and not permitir_vazio:
        raise ValueError('Nenhuma NF-e modelo 55 conferida no diretório')
    return linhas, {'notas': len(vistos), 'itens': len(linhas), 'por_tipo': por_tipo}


def preencher_aba_nfe(folha, linhas: list[list]) -> None:
    folha.append(CABECALHOS)
    cinza = PatternFill('solid', fgColor='BFBFBF')
    for celula in folha[1]:
        celula.font = Font(bold=True)
        celula.fill = cinza
        celula.alignment = Alignment(vertical='center')
    folha.freeze_panes = 'A2'
    larguras = {1: 13, 2: 11, 4: 49, 5: 20, 6: 42, 7: 21, 8: 42,
                14: 21, 16: 48, 53: 30}
    for indice in range(1, len(CABECALHOS) + 1):
        folha.column_dimensions[get_column_letter(indice)].width = larguras.get(indice, 19)
    for linha in linhas:
        folha.append([float(valor) if isinstance(valor, Decimal) else valor for valor in linha])
        for indice, valor in enumerate(linha, 1):
            celula = folha.cell(folha.max_row, indice)
            if isinstance(valor, date):
                celula.number_format = 'dd/mm/yyyy'
            elif indice in NUMERICAS and valor is not None:
                celula.number_format = '#,##0.##########'
            elif isinstance(valor, str):
                celula.data_type = 's'  # Campos do XML nunca viram fórmulas do Excel.
                celula.number_format = '@'
    folha.auto_filter.ref = f'A1:BB{folha.max_row}'


def salvar_xlsx(linhas: list[list], destino: Path) -> None:
    if destino.suffix.lower() != '.xlsx':
        raise ValueError('O relatório deve ter extensão .xlsx')
    livro = Workbook()
    folha = livro.active
    folha.title = 'RELATÓRIO POR PRODUTO'
    preencher_aba_nfe(folha, linhas)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=destino.stem + '.', suffix='.xlsx',
                                     dir=destino.parent, delete=False) as temporario_aberto:
        temporario = Path(temporario_aberto.name)
    try:
        livro.save(temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def main() -> int:
    cli = argparse.ArgumentParser(description='Relatório por produto dos XMLs de NF-e já recuperados')
    cli.add_argument('--xml-dir', type=Path, required=True)
    cli.add_argument('--cnpj-empresa', required=True)
    cli.add_argument('--saida', type=Path, required=True)
    args = cli.parse_args()
    if args.saida.suffix.lower() != '.xlsx':
        cli.error('--saida deve terminar em .xlsx')
    try:
        linhas, resumo = reunir_xmls(args.xml_dir, args.cnpj_empresa)
        salvar_xlsx(linhas, args.saida)
    except (OSError, ValueError) as erro:
        cli.error(str(erro))
    print(json.dumps({'status': 'GERADO', **resumo, 'arquivo': str(args.saida)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
