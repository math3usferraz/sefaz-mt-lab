from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook

from relatorio_mensal import ABAS, CABECALHOS_NFSE, gerar_mensal
from test_meu_danfe import criar_chave_ficticia, xml_ficticio


class TestRelatorioMensal(unittest.TestCase):
    def test_seis_abas_sem_inventar_documentos_pendentes(self):
        chave = criar_chave_ficticia()
        cnpj = chave[6:20]
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            origem = raiz / 'xmls' / cnpj / '2026' / '11' / 'nfe_emitidas'
            origem.mkdir(parents=True)
            (origem / f'{chave}.xml').write_bytes(xml_ficticio(chave))
            destino = raiz / 'mensal.xlsx'
            resumo = gerar_mensal(raiz / 'xmls', cnpj, '2026-11', destino)
            livro = load_workbook(destino, read_only=True, data_only=True)
            self.assertEqual(tuple(livro.sheetnames), ABAS)
            self.assertEqual(livro['NF-e saída'].max_row, 2)
            self.assertEqual(livro['NF-e saída']['D2'].value, chave)
            self.assertEqual(resumo['abas']['NF-e saída']['xmls'], 1)
            self.assertIn('ainda não recuperado', livro['NF-e entrada']['A2'].value)
            self.assertEqual(livro['NFS-e entrada'].max_column, len(CABECALHOS_NFSE))
            self.assertEqual(resumo['abas']['CT-e saída']['xmls'], 0)
            livro.close()


if __name__ == '__main__':
    unittest.main()
