"""Extrai e valida chaves de acesso de NF-e (44 dígitos) de planilhas locais.

Não acessa a SEFAZ, não contorna proteções e não envia dados a terceiros.
"""
from __future__ import annotations

import csv
from io import BytesIO
from pathlib import Path
import re
import zipfile

_CHAVE = re.compile(r"(?<!\d)\d[\d./-]{42,78}\d(?!\d)")
_EXTENSOES = {".xlsx", ".xls", ".csv", ".txt", ".zip"}
_MODELOS_FISCAIS = {"55", "57", "65", "67"}
_MODELOS_NFE = {"55", "65"}
_UFS = {"11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50", "51", "52", "53"}


def chave_valida(chave: str) -> bool:
    if not re.fullmatch(r"\d{44}", chave):
        return False
    # Validar modelos NF-e (55) e NFC-e (65), sem aceitar chaves artificiais.
    ufs = {"11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50", "51", "52", "53"}
    if len(set(chave)) == 1 or chave[:2] not in ufs or chave[20:22] not in {"55", "65"}:
        return False
    # NF-e: DV do módulo 11, pesos 2 a 9 da direita para a esquerda.
    soma = sum(int(digito) * (2 + i % 8) for i, digito in enumerate(reversed(chave[:43])))
    dv = 11 - (soma % 11)
    if dv >= 10:
        dv = 0
    return int(chave[-1]) == dv


def chave_fiscal_valida(chave: str, modelos: set[str] | None = None) -> bool:
    """Valida chave de NF-e, CT-e, NFC-e ou CT-e OS sem restringir o modelo."""
    if not re.fullmatch(r"\d{44}", chave):
        return False
    aceitos = _MODELOS_FISCAIS if modelos is None else set(modelos)
    if len(set(chave)) == 1 or chave[:2] not in _UFS or chave[20:22] not in aceitos:
        return False
    soma = sum(int(digito) * (2 + i % 8) for i, digito in enumerate(reversed(chave[:43])))
    dv = 11 - (soma % 11)
    return int(chave[-1]) == (0 if dv >= 10 else dv)


def _extrair_texto(texto: str, modelos: set[str] | None = _MODELOS_NFE) -> set[str]:
    """Aceita chaves de 44 dígitos e a máscara de NFC-e fornecida pela SEFAZ-MT.

    Exemplo fictício do formato: 51-2608-12.345.678/0001-99-65-001-000.000.001-123.456.781-0.
    O DV é validado APÓS remover pontuação. Nunca converte a chave em número.
    """
    chaves = set()
    for match in _CHAVE.finditer(texto):
        candidata = re.sub(r"\D", "", match.group())
        if chave_fiscal_valida(candidata, modelos):
            chaves.add(candidata)
    return chaves


def _conteudo(dados: bytes, sufixo: str, modelos: set[str] | None = _MODELOS_NFE) -> tuple[set[str], list[str]]:
    avisos: list[str] = []
    chaves: set[str] = set()
    if sufixo in {".csv", ".txt"}:
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return _extrair_texto(dados.decode(enc), modelos), avisos
            except UnicodeDecodeError:
                pass
        return set(), ["Não foi possível decodificar texto."]

    if sufixo == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(dados), read_only=True, data_only=True)
        try:
            for aba in wb.worksheets:
                for linha in aba.iter_rows(values_only=True):
                    for valor in linha:
                        if valor is None:
                            continue
                        if isinstance(valor, (float, int)) and len(str(int(valor))) > 15:
                            avisos.append("Há valores numéricos longos: o Excel pode ter perdido dígitos. Exporte a chave como texto.")
                            continue
                        chaves.update(_extrair_texto(str(valor), modelos))
        finally:
            wb.close()
        return chaves, sorted(set(avisos))

    if sufixo == ".xls":
        # Algumas exportações antigas rotulam HTML como .xls.
        if dados.lstrip()[:200].lower().startswith((b"<html", b"<!doctype html", b"<table")):
            return _extrair_texto(dados.decode("latin-1", errors="replace"), modelos), avisos
        import xlrd
        wb = xlrd.open_workbook(file_contents=dados)
        for aba in wb.sheets():
            for i in range(aba.nrows):
                for valor in aba.row_values(i):
                    if isinstance(valor, float) and len(str(int(valor))) > 15:
                        avisos.append("Valores numéricos longos do Excel podem perder precisão. Chaves devem ser texto.")
                    chaves.update(_extrair_texto(str(valor), modelos))
        return chaves, sorted(set(avisos))

    if sufixo == ".zip":
        with zipfile.ZipFile(BytesIO(dados)) as z:
            for membro in z.infolist():
                ext = Path(membro.filename).suffix.lower()
                if membro.is_dir() or ext not in _EXTENSOES - {".zip"}:
                    continue
                if membro.file_size > 30 * 1024 * 1024:
                    avisos.append(f"Arquivo muito grande ignorado: {Path(membro.filename).name}")
                    continue
                extraidas, novos_avisos = _conteudo(z.read(membro), ext, modelos)
                chaves.update(extraidas)
                avisos.extend(novos_avisos)
        return chaves, sorted(set(avisos))

    return set(), [f"Formato não suportado: {sufixo}"]


def extrair_do_arquivo(caminho: Path, modelos: set[str] | None = _MODELOS_NFE) -> tuple[list[str], list[str]]:
    caminho = Path(caminho)
    if caminho.suffix.lower() not in _EXTENSOES:
        raise ValueError("Formatos aceitos: .xlsx, .xls, .csv, .txt e .zip")
    if caminho.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Arquivo acima de 50 MB: confira antes de processar")
    chaves, avisos = _conteudo(caminho.read_bytes(), caminho.suffix.lower(), modelos)
    return sorted(chaves), avisos


def salvar_csv(chaves: list[str], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.writer(arquivo, delimiter=";")
        writer.writerow(["chave_acesso"])
        for chave in chaves:
            # Aspas e coluna textual: não inventar nem formatar como número.
            writer.writerow([chave])
