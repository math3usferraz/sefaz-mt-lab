import unittest
from unittest.mock import Mock

from main import analisar_pagina, aguardar_liberacao_portal


class Pagina:
    def __init__(self, html, url='https://www.sefaz.mt.gov.br/acesso/x.xhtml'):
        self.url = url
        self.title = 'AcessoWeb'
        self.html = html


class TestDesafioPortal(unittest.TestCase):
    def test_dom_indisponivel_nao_e_liberacao(self):
        self.assertEqual(analisar_pagina(Pagina(''))['status'], 'PAGINA_NAO_VERIFICADA')

    def test_identifica_desafio_e_remove_sessao_dos_diagnosticos(self):
        estado = analisar_pagina(Pagina('<title>Just a moment</title>',
                            'https://www.sefaz.mt.gov.br/x;jsessionid=SEGREDO?token=SEGREDO'))
        self.assertEqual(estado['status'], 'DESAFIO_DETECTADO')
        self.assertEqual(estado['url_final'], 'https://www.sefaz.mt.gov.br/x')

    def test_aguarda_validacao_e_prossegue_somente_apos_html(self):
        analisar = Mock(side_effect=[{'status': 'DESAFIO_DETECTADO'},
                                    {'status': 'PAGINA_NAO_VERIFICADA'},
                                    {'status': 'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE'}])
        dormir = Mock()
        estado = aguardar_liberacao_portal(object(), timeout=10, analisar=analisar,
                                           dormir=dormir, relogio=lambda: 0)
        self.assertEqual(estado['status'], 'PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE')
        self.assertEqual(dormir.call_count, 2)

    def test_bloqueio_interrompe_sem_clicar(self):
        analisar = Mock(return_value={'status': 'BLOQUEIO_DETECTADO'})
        dormir = Mock()
        estado = aguardar_liberacao_portal(object(), analisar=analisar, dormir=dormir)
        self.assertEqual(estado['status'], 'BLOQUEIO_DETECTADO')
        dormir.assert_not_called()
