import unittest
from extrair_chaves import chave_valida
from validar_xml import validar_xml


def chave_ficticia(modelo='55'):
    base='51'+'2611'+'12345678000199'+modelo+'001'+'000123456'+'1'+'12345678'
    soma=sum(int(d)*(2+i%8) for i,d in enumerate(reversed(base)))
    dv=11-(soma%11)
    return base+str(0 if dv>=10 else dv)


def fixture_xml(chave, assinatura=True, cstat='100', tipo='nfeProc'):
    sig='<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"/>' if assinatura else ''
    if tipo!='nfeProc':
        return f'<resNFe><chNFe>{chave}</chNFe></resNFe>'.encode()
    return f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe{chave}"><ide><mod>{chave[20:22]}</mod></ide></infNFe>{sig}</NFe><protNFe><infProt><chNFe>{chave}</chNFe><nProt>123456</nProt><cStat>{cstat}</cStat></infProt></protNFe></nfeProc>""".encode()


class TestXML(unittest.TestCase):
    def test_estrutura_nfe(self):
        c=chave_ficticia()
        r=validar_xml(fixture_xml(c), c)
        self.assertEqual(r.status,'VALIDO_ESTRUTURAL')
        self.assertFalse(r.assinatura_verificada)
    def test_estrutura_nfce(self):
        c=chave_ficticia('65')
        self.assertEqual(validar_xml(fixture_xml(c), c).status,'VALIDO_ESTRUTURAL')
    def test_resumo_nao_e_xml_completo(self):
        c=chave_ficticia()
        self.assertEqual(validar_xml(fixture_xml(c,tipo='resNFe'), c).status,'INCOMPLETO')
    def test_inconsistencia_chave(self):
        c=chave_ficticia()
        outra=chave_ficticia('65')
        self.assertEqual(validar_xml(fixture_xml(c), outra).status,'INCONSISTENTE')
    def test_sem_assinatura_nao_impede_conferencia_basica(self):
        c=chave_ficticia()
        r=validar_xml(fixture_xml(c,assinatura=False), c)
        self.assertEqual(r.status,'VALIDO_ESTRUTURAL')
        self.assertFalse(r.assinatura_presente)
        self.assertFalse(r.assinatura_verificada)
    def test_xml_malformado(self):
        c=chave_ficticia()
        self.assertEqual(validar_xml(b'<html>oops',c).status,'INVALIDO')
    def test_sem_autorizacao(self):
        c=chave_ficticia()
        self.assertEqual(validar_xml(fixture_xml(c,cstat='101'),c).status,'INCOMPLETO')

if __name__=='__main__':
    unittest.main()
