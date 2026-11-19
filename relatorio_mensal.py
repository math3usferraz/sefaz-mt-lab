"""Consolida os documentos de uma empresa/competência em seis abas.

Uma aba vazia indica fonte ainda não coletada ou XML ainda não recuperado;
jamais significa que o portal confirmou ausência de documentos.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import tempfile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from relatorio_nfe import preencher_aba_nfe, reunir_xmls


ABAS = ('NF-e entrada', 'NF-e saída', 'NFS-e entrada', 'NFS-e saída',
        'CT-e entrada', 'CT-e saída')

# Colunas do relatório de NFS-e fornecido como referência; ainda sem linhas
# porque a distribuição ADN não foi concluída para esta empresa.
CABECALHOS_NFSE = (
    'Data de Emissão', 'Competência', 'Série', 'Número RPS', 'Número NFSe',
    'Chave de Acesso', 'CNPJ Prestador', 'Razão Social do Prestador',
    'Município Prestador', 'UF Prestador', 'CNPJ Tomador', 'Razão Social Tomador',
    'Município Tomador', 'UF Tomador', 'Município Prestação Serviço',
    'UF Prestação Serviço', 'Item Lista Serviço', 'Discriminação',
    'Valor Serviço', 'PIS', 'COFINS', 'INSS', 'Valor IR', 'Valor CSLL',
    'Valor ISS', 'Valor Retido ISS', 'Valor IBS', 'Valor CBS',
    'Valor Contribuições Sociais Retidas', 'Outras Retenções',
    'Desconto Condicionado', 'Desconto Incondicionado', 'Valor Líquido',
    'Tipo de Emissão', 'Situação', 'CTN', 'DANFS-E', 'Download XML',
)

# Campos iniciais do relatório de CT-e. Serão confrontados com um CT-e real
# antes de receber linhas de dados.
CABECALHOS_CTE = (
    'DATA CT-e', 'NÚMERO', 'SÉRIE', 'CHAVE CT-e', 'CNPJ EMITENTE', 'EMITENTE',
    'CNPJ REMETENTE', 'REMETENTE', 'CNPJ DESTINATÁRIO', 'DESTINATÁRIO',
    'CNPJ TOMADOR', 'TOMADOR', 'VALOR PRESTAÇÃO', 'VALOR ICMS', 'SITUAÇÃO',
)


def _aba_pendente(folha, cabecalhos: tuple[str, ...], mensagem: str) -> None:
    folha.append(cabecalhos)
    for coluna, celula in enumerate(folha[1], 1):
        celula.font = Font(bold=True)
        celula.fill = PatternFill('solid', fgColor='BFBFBF')
        celula.alignment = Alignment(vertical='center')
        folha.column_dimensions[get_column_letter(coluna)].width = (
            49 if 'CHAVE' in celula.value.upper() else min(42, max(17, len(celula.value) + 2)))
    folha['A2'] = mensagem
    folha['A2'].font = Font(italic=True, color='7A5B00')
    folha.column_dimensions['A'].width = max(folha.column_dimensions['A'].width, 35)
    folha.freeze_panes = 'A2'


def gerar_mensal(raiz_xml: Path, cnpj: str, competencia: str, destino: Path,
                 coleta: Path | None = None) -> dict:
    if not re.fullmatch(r'\d{14}', cnpj):
        raise ValueError('CNPJ deve ter 14 dígitos')
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', competencia):
        raise ValueError('Competência deve estar em AAAA-MM')
    if destino.suffix.lower() != '.xlsx':
        raise ValueError('Destino deve terminar em .xlsx')
    ano, mes = competencia.split('-')
    pasta_xml = raiz_xml / cnpj / ano / mes
    conferencia = {}
    if coleta is not None:
        conferencia = json.loads((coleta / 'conferencia.json').read_text(encoding='utf-8'))
        if conferencia.get('cnpj') != cnpj or conferencia.get('competencia') != competencia:
            raise ValueError('Conferência de chaves não corresponde à empresa/competência')

    livro = Workbook()
    livro.remove(livro.active)
    resumo = {'empresa': cnpj, 'competencia': competencia, 'abas': {}}
    for nome, tipo in (('NF-e entrada', 'recebidas'), ('NF-e saída', 'emitidas')):
        folha = livro.create_sheet(nome)
        linhas, contagem = reunir_xmls(pasta_xml, cnpj, tipo_filtro=tipo, permitir_vazio=True)
        for linha in linhas:
            emissao = linha[0]
            if not isinstance(emissao, date) or emissao.strftime('%Y-%m') != competencia:
                raise ValueError('XML recuperado tem emissão fora da competência')
        preencher_aba_nfe(folha, linhas)
        chaves_coletadas = conferencia.get(tipo, {}).get('chaves_unicas')
        if not linhas:
            mensagem = ('XML ainda não recuperado' if chaves_coletadas is None else
                        f'{chaves_coletadas} chaves coletadas; XMLs pendentes')
            folha['A2'] = mensagem
            folha['A2'].font = Font(italic=True, color='7A5B00')
        resumo['abas'][nome] = {'xmls': contagem['notas'], 'linhas': len(linhas),
                                'chaves_coletadas': chaves_coletadas}

    for nome in ('NFS-e entrada', 'NFS-e saída', 'CT-e entrada', 'CT-e saída'):
        folha = livro.create_sheet(nome)
        cabecalhos = CABECALHOS_NFSE if nome.startswith('NFS-e') else CABECALHOS_CTE
        _aba_pendente(folha, cabecalhos, 'Coleta de XML ainda não confirmada')
        resumo['abas'][nome] = {'xmls': 0, 'linhas': 0, 'status': 'COLETA_NAO_CONFIRMADA'}

    if tuple(livro.sheetnames) != ABAS:
        raise RuntimeError('Ordem das abas divergente')
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=destino.stem + '.', suffix='.xlsx',
                                     dir=destino.parent, delete=False) as temporario_aberto:
        temporario = Path(temporario_aberto.name)
    try:
        livro.save(temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
    return resumo


def main() -> int:
    cli = argparse.ArgumentParser(description='Relatório mensal de NF-e, NFS-e e CT-e por operação')
    cli.add_argument('--cnpj', required=True)
    cli.add_argument('--competencia', required=True, help='AAAA-MM')
    cli.add_argument('--xml-raiz', type=Path, default=Path(__file__).resolve().parent / 'saida' / 'xmls')
    cli.add_argument('--coleta', type=Path, help='Pasta de coleta da competência com conferencia.json')
    cli.add_argument('--saida', type=Path, required=True)
    args = cli.parse_args()
    try:
        resumo = gerar_mensal(args.xml_raiz, args.cnpj, args.competencia, args.saida, args.coleta)
    except (OSError, ValueError) as erro:
        cli.error(str(erro))
    print(json.dumps({'status': 'GERADO', **resumo}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
