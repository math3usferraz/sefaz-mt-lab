import tempfile
from pathlib import Path
import unittest

from extrair_chaves import chave_fiscal_valida, chave_valida, extrair_do_arquivo, salvar_csv, _extrair_texto


def criar_chave_ficticia(modelo="55"):
    base = "51" + "2611" + "12345678000199" + modelo + "001" + "000123456" + "1" + "12345678"
    assert len(base) == 43
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
    dv = 11 - (soma % 11)
    return base + str(0 if dv >= 10 else dv)


class TestExtracao(unittest.TestCase):
    def test_chave_mod11(self):
        chave = criar_chave_ficticia()
        self.assertTrue(chave_valida(chave))
        self.assertFalse(chave_valida(chave[:-1] + str((int(chave[-1]) + 1) % 10)))

    def test_nfce_formatada(self):
        chave = criar_chave_ficticia("65")
        self.assertTrue(chave_valida(chave))
        cnpj = chave[6:20]
        formatada = (
            f"{chave[:2]}-{chave[2:6]}-{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/"
            f"{cnpj[8:12]}-{cnpj[12:14]}-{chave[20:22]}-{chave[22:25]}-"
            f"{chave[25:28]}.{chave[28:31]}.{chave[31:34]}-"
            f"{chave[34:37]}.{chave[37:40]}.{chave[40:43]}-{chave[43]}"
        )
        self.assertEqual(_extrair_texto(formatada), {chave})
        self.assertEqual(_extrair_texto(chave), {chave})

    def test_modelos_e_dv(self):
        nfe = criar_chave_ficticia("55")
        nfce = criar_chave_ficticia("65")
        self.assertTrue(chave_valida(nfe))
        self.assertTrue(chave_valida(nfce))
        self.assertFalse(chave_valida(nfce[:-1] + str((int(nfce[-1]) + 1) % 10)))

    def test_cte_e_cteos_sao_aceitos_somente_no_extrator_fiscal(self):
        cte = criar_chave_ficticia("57")
        cteos = criar_chave_ficticia("67")
        self.assertFalse(chave_valida(cte))
        self.assertTrue(chave_fiscal_valida(cte))
        self.assertTrue(chave_fiscal_valida(cteos))
        self.assertEqual(_extrair_texto(f'{cte};{cteos}', {"57", "67"}), {cte, cteos})

    def test_csv(self):
        chave = criar_chave_ficticia()
        with tempfile.TemporaryDirectory() as temp:
            arquivo = Path(temp) / "relatorio.csv"
            arquivo.write_text("Chave;Numero\n" + chave + ";123\n" + chave + ";124\n" + "0" * 44 + ";000\n", encoding="utf-8")
            chaves, avisos = extrair_do_arquivo(arquivo)
            self.assertEqual(chaves, [chave])
            self.assertEqual(avisos, [])
            destino = Path(temp) / "saida.csv"
            salvar_csv(chaves, destino)
            self.assertIn(chave, destino.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
