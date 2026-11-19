from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook

from relatorio_nfe import CABECALHOS, extrair_linhas, salvar_xlsx
from test_meu_danfe import criar_chave_ficticia


class TestRelatorioNFe(unittest.TestCase):
    def test_um_registro_por_item_e_campos_ausentes_vazios(self):
        chave = criar_chave_ficticia()
        itens = ''
        for n, valor in ((1, '10.00'), (2, '20.00')):
            itens += (f'<det><nItem>{n}</nItem><prod><cProd>SKU{n}</cProd>'
                      f'<xProd>=SUM(1,2)</xProd><qCom>{n}</qCom><vUnCom>10.00</vUnCom>'
                      f'<vProd>{valor}</vProd><NCM>01012100</NCM><CFOP>5102</CFOP></prod>'
                      '<imposto><ICMS><ICMS00><CST>00</CST><vICMSST>0.00</vICMSST>'
                      '</ICMS00></ICMS></imposto></det>')
        xml = (f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe>'
               f'<infNFe Id="NFe{chave}"><ide><mod>55</mod><nNF>7</nNF>'
               '<dhEmi>2026-11-01T12:00:00-04:00</dhEmi><tpNF>1</tpNF></ide>'
               f'<emit><CNPJ>{chave[6:20]}</CNPJ><xNome>Emitente</xNome>'
               '<enderEmit><UF>MT</UF></enderEmit></emit>'
               '<dest><CNPJ>11222333000144</CNPJ><xNome>Destinatário</xNome>'
               '<enderDest><UF>MT</UF></enderDest></dest>'
               f'{itens}<total><ICMSTot><vNF>30.00</vNF></ICMSTot></total>'
               '</infNFe></NFe><protNFe><infProt>'
               f'<chNFe>{chave}</chNFe><nProt>123</nProt><cStat>100</cStat>'
               '</infProt></protNFe></nfeProc>').encode()
        linhas = extrair_linhas(xml, chave, chave[6:20], 'emitidas')
        self.assertEqual(len(CABECALHOS), 54)
        self.assertEqual(len(linhas), 2)
        self.assertEqual([linha[14] for linha in linhas], ['1', '2'])
        self.assertEqual([linha[29] for linha in linhas], [Decimal('10.00'), Decimal('20.00')])
        self.assertEqual(linhas[0][2], Decimal('30.00'))
        self.assertIsNone(linhas[0][20])  # Não deduzir uma alíquota única de IBS.
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / 'relatorio.xlsx'
            salvar_xlsx(linhas, destino)
            folha = load_workbook(destino, data_only=False).active
            self.assertEqual(folha.max_row, 3)
            self.assertEqual(folha.max_column, 54)
            self.assertEqual(folha['D2'].value, chave)
            self.assertEqual(folha['P2'].value, '=SUM(1,2)')
            self.assertEqual(folha['P2'].data_type, 's')


if __name__ == '__main__':
    unittest.main()
