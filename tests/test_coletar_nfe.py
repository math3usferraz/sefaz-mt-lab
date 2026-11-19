from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coletar_nfe import coletar_tipo, consultar, validar_planilha


def chave_ficticia():
    base = "51" + "2610" + "12345678000199" + "55" + "001" + "000123456" + "1" + "12345678"
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
    dv = 11 - (soma % 11)
    return base + str(0 if dv >= 10 else dv)


class AbaFalsa:
    nrows = 8
    ncols = 26

    def __init__(self, linha):
        self.linha = linha

    def row_values(self, indice):
        if indice == 6:
            cab = [""] * 26
            cab[3], cab[9], cab[11] = "CHAVE DE ACESSO", "CNPJ/CPF", "INSCRICAO ESTADUAL"
            cab[14], cab[15] = "CNPJ/CPF", "INSCRICAO ESTADUAL"
            return cab
        if indice == 7:
            return self.linha
        return [""] * 26


class LivroFalso:
    def __init__(self, linha):
        self.aba = AbaFalsa(linha)

    def sheet_by_index(self, indice):
        return self.aba


class TestValidacaoRelatorio(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.arquivo = Path(self.temp.name) / "novo.xls"
        self.arquivo.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"teste")
        self.chave = chave_ficticia()
        self.linha = [""] * 26
        self.linha[0], self.linha[3], self.linha[8] = "05/10/2026 10:00:00", self.chave, "AUTORIZADA"
        self.linha[9], self.linha[11] = "12.345.678/0001-99", "123456789"
        self.linha[14], self.linha[15] = "98.765.432/0001-00", "987654321"
        self.inicio, self.fim = datetime(2026, 10, 1), datetime(2026, 10, 31)

    def validar(self, tipo):
        with patch("coletar_nfe.xlrd.open_workbook", return_value=LivroFalso(self.linha)), \
             patch("coletar_nfe.extrair_do_arquivo", return_value=([self.chave], [])):
            return validar_planilha(self.arquivo, "12345678000199", "123456789",
                                    self.inicio, self.fim, tipo)

    def test_emitida_corresponde_ao_emissor(self):
        resultado = self.validar("emitidas")
        self.assertEqual(resultado["chaves_unicas"], 1)

    def test_recebida_exige_destinatario_correto(self):
        with self.assertRaisesRegex(ValueError, "Empresa divergente"):
            self.validar("recebidas")

    def test_periodo_fora_da_consulta_e_rejeitado(self):
        self.linha[0] = "05/09/2026 10:00:00"
        with self.assertRaisesRegex(ValueError, "fora do periodo"):
            self.validar("emitidas")

    def test_consulta_repete_quando_nao_ha_resultado(self):
        class Elemento:
            clicks = 0

            def input(self, valor):
                pass

            def click(self):
                self.clicks += 1

        botao = Elemento()

        class Frame:
            def ele(self, seletor, timeout=8):
                return botao if 'btnConsEmitReceb' in seletor else Elemento()

            def run_js(self, script):
                if script.startswith('return ['):
                    return ['01/10/2026', '31/10/2026', True, 'Todas', 'Todas']
                return 'Resultado da Consulta' if botao.clicks >= 2 else 'Dados para Consulta'

        relogio = iter(range(0, 200, 5))
        with patch('coletar_nfe.time.monotonic', side_effect=lambda: next(relogio)), \
                patch('coletar_nfe.time.sleep'):
            consultar(Frame(), 'recebidas', self.inicio, self.fim)
        self.assertEqual(botao.clicks, 2)

    def test_consulta_rejeita_resultado_antes_de_enviar(self):
        class Frame:
            def run_js(self, script):
                return 'Resultado da Consulta'

            def ele(self, *args, **kwargs):
                raise AssertionError('Consulta antiga nao pode ser exportada')

        with self.assertRaisesRegex(RuntimeError, 'resultado anterior'):
            consultar(Frame(), 'emitidas', self.inicio, self.fim)

    def test_sem_registros_nao_exporta_relatorio_anterior(self):
        base = Path(self.temp.name) / 'execucao'
        with patch('coletar_nfe.abrir_consulta', return_value=object()), \
             patch('coletar_nfe.consultar', return_value='VAZIO'), \
             patch('coletar_nfe.exportar') as exportar:
            resultado = coletar_tipo(object(), base, '12345678000199', '123456789',
                                     self.inicio, self.fim, 'emitidas', 30)
        exportar.assert_not_called()
        self.assertEqual(resultado['chaves_unicas'], 0)
        self.assertTrue((base / 'emitidas' / 'chaves_extraidas.csv').exists())


if __name__ == "__main__":
    unittest.main()
