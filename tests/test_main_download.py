import tempfile
from pathlib import Path
import time
import unittest

from main import aguardando_download, criar_pasta_download_execucao


class TestDownloadIsolado(unittest.TestCase):
    def test_ignora_arquivo_anterior_e_aceita_apenas_novo(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / 'relatorio_antigo.xls').write_bytes(b'antigo')
            pasta = criar_pasta_download_execucao(base)
            self.assertEqual(list(pasta.iterdir()), [])
            self.assertIsNone(aguardando_download(pasta, time.time() - 1, timeout=0))

            novo = pasta / 'relatorio_novo.xls'
            novo.write_bytes(b'novo')
            self.assertEqual(aguardando_download(pasta, time.time() - 1, timeout=3), novo)


if __name__ == '__main__':
    unittest.main()
