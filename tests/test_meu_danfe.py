from pathlib import Path
import tempfile
import unittest

from meu_danfe import escolher_chave, executar
from validar_xml import validar_nfe_completa


def criar_chave_ficticia(numero='000123456'):
    base = '51' + '2611' + '12345678000199' + '55' + '001' + numero + '1' + '12345678'
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
    dv = 11 - soma % 11
    return base + str(0 if dv >= 10 else dv)


def xml_ficticio(chave, com_itens=True):
    itens = ("<det nItem='1'><prod><cProd>1</cProd><xProd>Teste</xProd>"
             "<qCom>1</qCom><vProd>1.00</vProd></prod>"
             "<imposto><ICMS><ICMS00><vICMS>0</vICMS></ICMS00></ICMS></imposto>"
             "</det>") if com_itens else ''
    return (f"<?xml version='1.0' encoding='UTF-8'?>\n"
            f"<nfeProc xmlns='http://www.portalfiscal.inf.br/nfe'>"
            f"<NFe><infNFe Id='NFe{chave}'><ide><mod>55</mod><nNF>1</nNF>"
            f"<dhEmi>2026-11-01T10:00:00-04:00</dhEmi></ide>"
            f"<emit><CNPJ>{chave[6:20]}</CNPJ></emit>"
            f"<dest><CNPJ>11222333000144</CNPJ></dest>{itens}"
            f"<total><ICMSTot><vNF>1.00</vNF></ICMSTot></total></infNFe>"
            f"<Signature xmlns='http://www.w3.org/2000/09/xmldsig#'/></NFe>"
            f"<protNFe><infProt><chNFe>{chave}</chNFe><nProt>123</nProt>"
            f"<cStat>100</cStat></infProt></protNFe></nfeProc>").encode()


class TestMeuDanfe(unittest.TestCase):
    def setUp(self):
        self.chave = criar_chave_ficticia()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.cnpj = '11222333000144'

    def executar(self, request, autorizar=False):
        return executar(self.chave, 'chave_de_teste', self.raiz, self.cnpj,
                        'recebidas', autorizar, pausa=lambda _: None, request=request)

    def test_download_gratuito_preserva_xml(self):
        xml = xml_ficticio(self.chave)
        chamadas = []
        def request(metodo, rota, chave_api):
            chamadas.append(metodo)
            return 200, {'type': 'NFE', 'format': 'XML', 'data': xml.decode()}
        resultado = self.executar(request)
        self.assertEqual(resultado['status'], 'XML_VALIDADO_ESTRUTURALMENTE')
        self.assertEqual(Path(resultado['xml']).read_bytes(), xml)
        self.assertEqual(chamadas, ['GET'])
        self.assertFalse(resultado['assinatura_verificada'])

    def test_indice_escolhe_uma_chave_distinta(self):
        segunda = criar_chave_ficticia('000123457')
        planilha = self.raiz / 'chaves.csv'
        planilha.write_text('chave\n' + self.chave + '\n' + segunda + '\n', encoding='utf-8')
        self.assertNotEqual(escolher_chave(None, planilha, 0),
                            escolher_chave(None, planilha, 1))
        with self.assertRaises(ValueError):
            escolher_chave(None, planilha, 2)

    def test_404_sem_autorizacao_nao_envia_put(self):
        chamadas = []
        def request(metodo, rota, chave_api):
            chamadas.append(metodo)
            return 404, None
        resultado = self.executar(request)
        self.assertEqual(resultado['status'], 'AGUARDANDO_APROVACAO_CUSTO')
        self.assertEqual(chamadas, ['GET'])

    def test_put_pendente_nao_repete_apos_reinicio(self):
        chamadas = []
        def request(metodo, rota, chave_api):
            chamadas.append(metodo)
            if metodo == 'GET':
                return 404, None
            return 200, {'value': self.chave, 'type': 'NFE', 'status': 'WAITING'}
        primeiro = self.executar(request, autorizar=True)
        self.assertEqual(primeiro['status'], 'CONSULTA_PENDENTE')
        antes = chamadas.count('PUT')
        segundo = self.executar(request, autorizar=True)
        self.assertEqual(segundo['status'], 'CONSULTA_PENDENTE')
        self.assertEqual(chamadas.count('PUT'), antes)

    def test_put_autorizado_baixa_apos_busca(self):
        xml = xml_ficticio(self.chave)
        chamadas = []
        def request(metodo, rota, chave_api):
            chamadas.append(metodo)
            if chamadas == ['GET']:
                return 404, None
            if metodo == 'PUT':
                return 200, {'value': self.chave, 'type': 'NFE', 'status': 'WAITING'}
            return 200, {'type': 'NFE', 'format': 'XML', 'data': xml.decode()}
        resultado = self.executar(request, autorizar=True)
        self.assertEqual(resultado['status'], 'XML_VALIDADO_ESTRUTURALMENTE')
        self.assertEqual(chamadas, ['GET', 'PUT', 'GET'])
        self.assertEqual(Path(resultado['xml']).read_bytes(), xml)

    def test_resumo_e_pdf_rejeitados(self):
        def request(metodo, rota, chave_api):
            return 200, {'type': 'NFE', 'format': 'BASE64', 'data': 'JVBERi0x'}
        resultado = self.executar(request)
        self.assertEqual(resultado['status'], 'RESPOSTA_INESPERADA')

    def test_xml_sem_assinatura_fica_em_pasta_de_dados(self):
        xml = xml_ficticio(self.chave).replace(
            b"<Signature xmlns='http://www.w3.org/2000/09/xmldsig#'/>", b'')
        def request(metodo, rota, chave_api):
            return 200, {'type': 'NFE', 'format': 'XML', 'data': xml.decode()}
        resultado = self.executar(request)
        self.assertEqual(resultado['status'], 'XML_DADOS_FISCAIS_CONFERIDOS')
        self.assertEqual(Path(resultado['xml']).read_bytes(), xml)
        self.assertIn('dados_meudanfe', resultado['xml'])
        self.assertFalse(resultado['assinatura_presente'])
        self.assertFalse(list(self.raiz.glob('**/nfe_recebidas/*.xml')))

    def test_sem_itens_nao_e_completo(self):
        self.assertEqual(validar_nfe_completa(xml_ficticio(self.chave, False), self.chave).status,
                         'INCOMPLETO')

    def test_nitem_como_elemento_e_dado_transformado(self):
        xml = xml_ficticio(self.chave).replace(
            b"<det nItem='1'>", b'<det><nItem>1</nItem>')
        resultado = validar_nfe_completa(xml, self.chave)
        self.assertEqual(resultado.status, 'DADOS_FISCAIS_CONFERIDOS')
        self.assertTrue(resultado.estrutura_transformada)

    def test_nitem_divergente_e_rejeitado(self):
        xml = xml_ficticio(self.chave).replace(
            b"<det nItem='1'>", b"<det nItem='1'><nItem>2</nItem>")
        self.assertEqual(validar_nfe_completa(xml, self.chave).status, 'INCONSISTENTE')

    def test_destinatario_de_outra_empresa_e_rejeitado(self):
        xml = xml_ficticio(self.chave).replace(
            b'<CNPJ>11222333000144</CNPJ>', b'<CNPJ>99888777000166</CNPJ>')
        def request(metodo, rota, chave_api):
            return 200, {'type': 'NFE', 'format': 'XML', 'data': xml.decode()}
        resultado = self.executar(request)
        self.assertEqual(resultado['status'], 'XML_INVALIDO')
        self.assertFalse(list(self.raiz.glob('**/nfe_recebidas*/*.xml')))


if __name__ == '__main__':
    unittest.main()
