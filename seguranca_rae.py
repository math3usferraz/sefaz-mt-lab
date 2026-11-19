"""Limites de seguranca para a prova de conceito reverse-api-engineer.

O reverse-api-engineer foi avaliado apenas contra uma API publica. Ele instrui
o agente gerador a reter cookies/tokens e a contornar protecoes quando possivel;
isso e incompativel com sessoes fiscais. Este modulo impede que o involucro de
teste seja apontado para a SEFAZ-MT, mesmo em um Chrome dedicado.
"""
from __future__ import annotations

from urllib.parse import urlsplit


class ExecucaoRaeBloqueada(RuntimeError):
    """O alvo contem uma sessao fiscal ou outra aba fora do escopo seguro."""


def resumo_abas_dedicadas(abas: list[dict]) -> list[dict[str, str]]:
    """Retorna somente metadados nao sensiveis das abas abertas.

    Nunca retorna query string, fragmento, cookies, identificador ``;jsessionid``
    ou titulo da pagina.
    """
    resultado: list[dict[str, str]] = []
    for aba in abas:
        if aba.get("type") != "page":
            continue
        partes = urlsplit(str(aba.get("url") or ""))
        resultado.append({
            "origin": f"{partes.scheme}://{partes.netloc}",
            "path": partes.path.split(";", 1)[0],
        })
    return resultado


def validar_abas_para_rae(abas: list[dict]) -> list[dict[str, str]]:
    """Permite apenas a demonstracao publica, nunca um portal da SEFAZ."""
    resumo = resumo_abas_dedicadas(abas)
    if not resumo:
        raise ExecucaoRaeBloqueada("Chrome dedicado sem aba de demonstracao.")
    if any(item["origin"] == "https://www.sefaz.mt.gov.br" for item in resumo):
        raise ExecucaoRaeBloqueada(
            "reverse-api-engineer bloqueado para a SEFAZ-MT: ele pode reter "
            "cookies, sessao e dados fiscais. Use o coletor DrissionPage local."
        )
    permitidas = {"https://jsonplaceholder.typicode.com"}
    if any(item["origin"] not in permitidas for item in resumo):
        raise ExecucaoRaeBloqueada("Chrome dedicado contem origem fora da demonstracao publica.")
    return resumo
