"""Verificação ESTRUTURAL offline de XML NF-e; não valida assinatura XMLDSig."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from extrair_chaves import chave_valida


def local_name(tag: str) -> str:
    return tag.split('}', 1)[-1]


def child(elem: ET.Element, name: str) -> ET.Element | None:
    return next((x for x in elem if local_name(x.tag) == name), None)


def path_text(elem: ET.Element, *names: str) -> str:
    now = elem
    for name in names:
        now = child(now, name)
        if now is None:
            return ''
    return (now.text or '').strip()


@dataclass
class ResultadoXML:
    status: str
    motivo: str
    chave: str = ''
    modelo: str = ''
    protocolo: str = ''
    cstat: str = ''
    assinatura_presente: bool = False
    assinatura_verificada: bool = False
    estrutura_transformada: bool = False


def validar_xml(dados: bytes, chave_esperada: str) -> ResultadoXML:
    if not chave_valida(chave_esperada):
        return ResultadoXML('INVALIDO', 'Chave esperada inválida')
    if len(dados) > 20 * 1024 * 1024:
        return ResultadoXML('INVALIDO', 'XML acima do limite de 20 MB')
    if b'<!DOCTYPE' in dados.upper() or b'<!ENTITY' in dados.upper():
        return ResultadoXML('INVALIDO', 'Declarações DTD/ENTITY rejeitadas')
    try:
        raiz = ET.fromstring(dados)
    except ET.ParseError:
        return ResultadoXML('INVALIDO', 'Conteúdo não é XML bem-formado')
    if local_name(raiz.tag) != 'nfeProc':
        return ResultadoXML('INCOMPLETO', 'Documento não é nfeProc completo (pode ser resNFe ou NFe isolada)')
    nota = child(raiz, 'NFe')
    prot = child(raiz, 'protNFe')
    if nota is None or prot is None:
        return ResultadoXML('INCOMPLETO', 'Falta NFe ou protNFe')
    inf = child(nota, 'infNFe')
    inf_prot = child(prot, 'infProt')
    if inf is None or inf_prot is None:
        return ResultadoXML('INCOMPLETO', 'Falta infNFe ou infProt')
    chave_nota = (inf.attrib.get('Id') or '').removeprefix('NFe')
    chave_prot = path_text(inf_prot, 'chNFe')
    modelo = path_text(inf, 'ide', 'mod')
    cstat = path_text(inf_prot, 'cStat')
    protocolo = path_text(inf_prot, 'nProt')
    assinatura = any(local_name(elem.tag) == 'Signature' for elem in nota.iter())
    if chave_nota != chave_esperada or chave_prot != chave_esperada:
        return ResultadoXML('INCONSISTENTE', 'Chave não coincide no documento e no protocolo', chave_nota, modelo, protocolo, cstat, assinatura)
    if modelo != chave_esperada[20:22]:
        return ResultadoXML('INCONSISTENTE', 'Modelo do XML diferente do modelo da chave', chave_nota, modelo, protocolo, cstat, assinatura)
    if not protocolo or cstat not in ('100', '150'):
        return ResultadoXML('INCOMPLETO', 'Protocolo de autorização ausente ou situação não reconhecida', chave_nota, modelo, protocolo, cstat, assinatura)
    return ResultadoXML('VALIDO_ESTRUTURAL', 'Chave, modelo e protocolo coerentes; autenticidade não verificada',
                        chave_nota, modelo, protocolo, cstat, assinatura, False)


def validar_nfe_completa(dados: bytes, chave_esperada: str, *,
                        cnpj_empresa: str | None = None, tipo: str | None = None) -> ResultadoXML:
    """Exige os campos essenciais de uma NF-e 55 autorizada, sem atestar a assinatura."""
    resultado = validar_xml(dados, chave_esperada)
    if resultado.status != 'VALIDO_ESTRUTURAL':
        return resultado
    if resultado.modelo != '55' or chave_esperada[20:22] != '55':
        return ResultadoXML('INCONSISTENTE', 'Somente NF-e modelo 55 é aceita nesta etapa')
    raiz = ET.fromstring(dados)
    nota = child(raiz, 'NFe')
    inf = child(nota, 'infNFe')
    namespace = '{http://www.portalfiscal.inf.br/nfe}'
    if any(not elem.tag.startswith(namespace) for elem in (raiz, nota, inf, child(raiz, 'protNFe'))):
        return ResultadoXML('INCONSISTENTE', 'Namespace fiscal NF-e ausente ou incorreto')
    obrigatorios = {
        'número da nota': ('ide', 'nNF'),
        'data de emissão': ('ide', 'dhEmi'),
        'emitente': ('emit', 'CNPJ'),
        'destinatário': ('dest', 'CNPJ'),
        'valor total': ('total', 'ICMSTot', 'vNF'),
    }
    if not path_text(inf, 'ide', 'dhEmi') and path_text(inf, 'ide', 'dEmi'):
        obrigatorios['data de emissão'] = ('ide', 'dEmi')
    if not path_text(inf, 'dest', 'CNPJ') and path_text(inf, 'dest', 'CPF'):
        obrigatorios['destinatário'] = ('dest', 'CPF')
    for nome, caminho in obrigatorios.items():
        if not path_text(inf, *caminho):
            return ResultadoXML('INCOMPLETO', f'Campo fiscal ausente: {nome}')
    try:
        total = Decimal(path_text(inf, 'total', 'ICMSTot', 'vNF'))
        if not total.is_finite() or total < 0:
            raise InvalidOperation
    except InvalidOperation:
        return ResultadoXML('INCONSISTENTE', 'Valor total inválido')
    if path_text(inf, 'emit', 'CNPJ') != chave_esperada[6:20]:
        return ResultadoXML('INCONSISTENTE', 'CNPJ do emitente difere da chave')
    if cnpj_empresa is not None:
        if tipo == 'emitidas' and path_text(inf, 'emit', 'CNPJ') != cnpj_empresa:
            return ResultadoXML('INCONSISTENTE', 'Emitente difere da empresa consultada')
        if tipo == 'recebidas' and path_text(inf, 'dest', 'CNPJ') != cnpj_empresa:
            return ResultadoXML('INCONSISTENTE', 'Destinatário difere da empresa consultada')
    itens = [item for item in inf if local_name(item.tag) == 'det']
    if not itens:
        return ResultadoXML('INCOMPLETO', 'NF-e sem itens')
    numeros_itens = set()
    for item in itens:
        numero_atributo = item.attrib.get('nItem', '')
        numero_elemento = path_text(item, 'nItem')
        if numero_atributo and numero_elemento and numero_atributo != numero_elemento:
            return ResultadoXML('INCONSISTENTE', 'Números do item divergentes')
        numero = numero_atributo or numero_elemento
        if not numero.isdigit() or int(numero) < 1 or numero in numeros_itens:
            return ResultadoXML('INCOMPLETO', 'Item sem número válido e único')
        numeros_itens.add(numero)
        if numero_elemento:
            resultado.estrutura_transformada = True
        imposto = child(item, 'imposto')
        if imposto is None or not list(imposto):
            return ResultadoXML('INCOMPLETO', 'Item sem grupo de impostos')
        for campo in ('cProd', 'xProd', 'qCom', 'vProd'):
            if not path_text(item, 'prod', campo):
                return ResultadoXML('INCOMPLETO', f'Item sem {campo}')
    if not resultado.assinatura_presente or resultado.estrutura_transformada:
        resultado.status = 'DADOS_FISCAIS_CONFERIDOS'
        resultado.motivo = ('Dados fiscais, itens e protocolo conferidos; XML transformado ou sem assinatura, '
                            'sem atestar conformidade ao leiaute oficial')
    return resultado


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description='Verifica estrutura de nfeProc (NÃO verifica criptograficamente assinatura)')
    cli.add_argument('arquivo', type=Path)
    cli.add_argument('--chave', required=True)
    args = cli.parse_args()
    try:
        result = validar_xml(args.arquivo.read_bytes(), args.chave)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    except OSError as e:
        cli.error(f'Não foi possível ler o XML: {type(e).__name__}')
