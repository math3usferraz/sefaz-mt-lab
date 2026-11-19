import unittest

from seguranca_rae import ExecucaoRaeBloqueada, resumo_abas_dedicadas, validar_abas_para_rae


class TestSegurancaRae(unittest.TestCase):
    def test_resumo_nao_expoe_sessao_ou_query(self):
        abas = [{"type": "page", "url": "https://www.sefaz.mt.gov.br/nfe/x.xhtml;jsessionid=SEGREDO?a=1#b"}]
        self.assertEqual(
            resumo_abas_dedicadas(abas),
            [{"origin": "https://www.sefaz.mt.gov.br", "path": "/nfe/x.xhtml"}],
        )

    def test_sefaz_e_bloqueada_antes_do_agente(self):
        with self.assertRaisesRegex(ExecucaoRaeBloqueada, "SEFAZ-MT"):
            validar_abas_para_rae([
                {"type": "page", "url": "https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml"}
            ])

    def test_apenas_demonstracao_publica_e_aceita(self):
        resultado = validar_abas_para_rae([
            {"type": "page", "url": "https://jsonplaceholder.typicode.com/todos/1"}
        ])
        self.assertEqual(resultado[0]["origin"], "https://jsonplaceholder.typicode.com")
