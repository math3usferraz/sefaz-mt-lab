import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sefaz_login import (autenticar_contribuinte, enviar_login_com_retentativas,
                         clicar_css_sem_espera, formulario_certificado_visivel,
                         estado_formulario_login_sem_espera, botao_login_visivel, url_sem_espera)


class PaginaFalsa:
    def __init__(self, confirmar_apos=None, mensagem=""):
        self.url = "https://www.sefaz.mt.gov.br/acesso/pages/login-certificado/login-certificado.xhtml"
        self.title = "AcessoWeb"
        self.confirmar_apos = confirmar_apos
        self.mensagem = mensagem
        self.cliques = 0

    def run_js(self, _):
        return "123456789"

    def ele(self, seletor, timeout=1):
        if seletor == 'css:div[id="messages"]':
            return type("Mensagem", (), {"text": self.mensagem})()
        if seletor == 'css:input[type="submit"][value="Efetuar Login"]':
            return self
        return None

    def click(self):
        self.cliques += 1
        if self.cliques == self.confirmar_apos:
            self.url = "https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml"


class TestLoginLimitado(unittest.TestCase):
    def test_clique_cdp_no_link_unico(self):
        class Pagina:
            def __init__(self):
                self.eventos = []

            def run_cdp(self, metodo, **kwargs):
                if metodo == 'DOM.getDocument':
                    return {'root': {'nodeId': 1}}
                if metodo == 'DOM.querySelectorAll':
                    self.seletor = kwargs['selector']
                    return {'nodeIds': [2]}
                if metodo == 'DOM.getBoxModel':
                    return {'model': {'content': [10, 20, 30, 20, 30, 40, 10, 40]}}
                self.eventos.append((kwargs['type'], kwargs['x'], kwargs['y']))
                return {}

        pagina = Pagina()
        self.assertTrue(clicar_css_sem_espera(pagina, 'a[title="Cetificado Digital"]'))
        self.assertEqual(pagina.seletor, 'a[title="Cetificado Digital"]')
        self.assertEqual(pagina.eventos, [('mousePressed', 20, 30),
                                         ('mouseReleased', 20, 30)])

    def test_formulario_em_branco_nao_e_tratado_como_login(self):
        class Pagina:
            url = 'https://www.sefaz.mt.gov.br/acesso/pages/login-certificado/login-certificado.xhtml'

            def ele(self, seletor, timeout=1):
                return None

        relogio = iter(range(20))
        with patch('sefaz_login.time.monotonic', side_effect=lambda: next(relogio)), \
                patch('sefaz_login.time.sleep'):
            self.assertFalse(formulario_certificado_visivel(Pagina(), espera=10))

    def test_url_cdp_nao_aguarda_carregamento(self):
        class Pagina:
            @property
            def url(self):
                raise AssertionError('Propriedade url aguardaria doc_loaded')

            def run_cdp(self, metodo, **kwargs):
                self.assertEqual(metodo, 'Target.getTargetInfo')
                return {'targetInfo': {'url': 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'}}

            def assertEqual(self, a, b):
                if a != b:
                    raise AssertionError()

        self.assertIn('paginainicial.xhtml', url_sem_espera(Pagina()))

    def test_certificado_repete_clique_ate_navegar(self):
        class Elemento:
            def __init__(self, pagina, nome=''):
                self.pagina = pagina
                self.text = nome
                self.states = SimpleNamespace(is_displayed=True)

            def click(self):
                if self.text == 'certificado':
                    self.pagina.cliques_certificado += 1
                    if self.pagina.cliques_certificado == 2:
                        self.pagina.url = 'https://www.sefaz.mt.gov.br/acesso/pages/login-certificado/login-certificado.xhtml'
                elif self.text == 'login':
                    self.pagina.url = 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'

            def input(self, valor):
                self.pagina.ie_digitada = valor

        class Pagina:
            url = 'https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml'
            title = 'AcessoWeb'
            cliques_certificado = 0
            process_id = 1234

            def ele(self, seletor, timeout=1):
                if 'Cetificado Digital' in seletor:
                    return Elemento(self, 'certificado')
                if 'selectTipoUsuario_3' in seletor:
                    return Elemento(self, 'Contribuinte MT')
                if 'selectTipoUsuario' in seletor or 'inputLogin' in seletor:
                    return Elemento(self)
                if 'Efetuar Login' in seletor:
                    return Elemento(self, 'login')
                return None

            def run_js(self, script):
                return 'CONTRIBUINTE_MT' if 'selectTipoUsuario_input' in script else self.ie_digitada

        pagina = Pagina()
        relogio = iter(range(0, 300, 11))
        with patch('sefaz_login.subprocess.run', return_value=SimpleNamespace(
                returncode=0, stdout='CERTIFICADO_CONFIRMADO')) as helper, \
                patch('sefaz_login.formulario_certificado_visivel', return_value=True), \
                patch('sefaz_login.time.monotonic', side_effect=lambda: next(relogio)), \
                patch('sefaz_login.time.sleep'):
            autenticar_contribuinte(pagina, '12345678000199', '123456789', tentativas_certificado=3)
        self.assertEqual(pagina.cliques_certificado, 2)
        self.assertEqual(helper.call_count, 2)
        self.assertIn('1234', helper.call_args.args[0])

    def test_redirecionamento_entre_duas_leituras_da_url(self):
        class PaginaComRedirecionamento:
            leituras = 0

            @property
            def url(self):
                self.leituras += 1
                if self.leituras == 1:
                    return 'https://www.sefaz.mt.gov.br/acesso/pages/login-certificado.xhtml'
                return 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'

        self.assertEqual(enviar_login_com_retentativas(
            PaginaComRedirecionamento(), '123456789', 8, 0), 0)

    def test_para_apos_login_confirmado(self):
        pagina = PaginaFalsa(confirmar_apos=3)
        self.assertEqual(enviar_login_com_retentativas(pagina, "123456789", 8, 0), 3)
        self.assertEqual(pagina.cliques, 3)

    def test_limite_sem_confirmacao(self):
        pagina = PaginaFalsa()
        with self.assertRaisesRegex(RuntimeError, "apos 4 envios"):
            enviar_login_com_retentativas(pagina, "123456789", 4, 0)
        self.assertEqual(pagina.cliques, 4)

    def test_erro_do_portal_interrompe(self):
        pagina = PaginaFalsa(mensagem="Acesso recusado")
        with self.assertRaisesRegex(RuntimeError, "Acesso recusado"):
            enviar_login_com_retentativas(pagina, "123456789", 8, 0)
        self.assertEqual(pagina.cliques, 0)

    def test_timeout_da_leitura_cdp_nao_cancela_retentativa(self):
        class PaginaComCdpLento(PaginaFalsa):
            def run_cdp(self, metodo, **_kwargs):
                if metodo == 'Target.getTargetInfo':
                    return {'targetInfo': {'url': self.url}}
                raise TimeoutError('portal ocupado')

        pagina = PaginaComCdpLento(confirmar_apos=2)
        self.assertEqual(enviar_login_com_retentativas(pagina, "123456789", 4, 0), 2)
        self.assertEqual(pagina.cliques, 2)

    def test_zero_repete_sem_limite_ate_portal_confirmar(self):
        pagina = PaginaFalsa(confirmar_apos=14)
        self.assertEqual(enviar_login_com_retentativas(pagina, "123456789", 0, 0), 14)
        self.assertEqual(pagina.cliques, 14)

    def test_formulario_vazio_nao_recarrega_o_portal(self):
        class Pagina:
            url = 'https://www.sefaz.mt.gov.br/acesso/pages/login-certificado/login-certificado.xhtml'
            title = 'AcessoWeb'
            process_id = 1234

            def get(self, *_args, **_kwargs):
                raise AssertionError('A sessao nao deve ser recarregada')

        relogio = iter(range(0, 300, 11))
        with patch('sefaz_login.formulario_certificado_visivel', return_value=False), \
                patch('sefaz_login.time.monotonic', side_effect=lambda: next(relogio)), \
                patch('sefaz_login.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'nao exibiu o formulario'):
                autenticar_contribuinte(Pagina(), '12345678000199', '123456789',
                                        tentativas_certificado=2)

    def test_estado_cdp_le_dados_sem_expor_estrutura_do_documento(self):
        class Pagina:
            def run_cdp(self, metodo, **kwargs):
                self.metodo, self.timeout = metodo, kwargs['_timeout']
                return {'result': {'value': {'valor': '123456789', 'mensagem': 'erro'}}}

        pagina = Pagina()
        self.assertEqual(estado_formulario_login_sem_espera(pagina), ('123456789', 'erro'))
        self.assertEqual((pagina.metodo, pagina.timeout), ('Runtime.evaluate', 2))

    def test_botao_login_aceita_button_quando_portal_troca_a_tag(self):
        class Botao:
            text = 'Efetuar Login'

            def attr(self, _):
                return ''

        class Pagina:
            def eles(self, *_args, **_kwargs):
                return [Botao()]

        self.assertEqual(botao_login_visivel(Pagina()).text, 'Efetuar Login')

    def test_botao_temporariamente_ausente_nao_aborta_login(self):
        pagina = PaginaFalsa(confirmar_apos=1)
        with patch('sefaz_login.botao_login_visivel', side_effect=[None, pagina]):
            self.assertEqual(enviar_login_com_retentativas(pagina, '123456789', 3, 0), 2)
        self.assertEqual(pagina.cliques, 1)

    def test_contexto_perdido_no_clique_so_confirma_com_url_de_sucesso(self):
        from DrissionPage.errors import ContextLostError

        class Botao:
            def click(self):
                pagina.url = 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'
                raise ContextLostError()

        pagina = PaginaFalsa()
        with patch('sefaz_login.botao_login_visivel', return_value=Botao()):
            self.assertEqual(enviar_login_com_retentativas(pagina, '123456789', 3, 0), 0)


if __name__ == "__main__":
    unittest.main()
