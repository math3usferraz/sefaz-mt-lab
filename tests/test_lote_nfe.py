from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lote_nfe import carregar_empresas, executar_lote, preparar_checkpoint, _relatorio_novo


class TestLote(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.arquivo = self.base / 'empresas.csv'
        self.arquivo.write_text('cnpj;ie\n12.345.678/0001-99;123456789\n', encoding='utf-8-sig')
        self.empresas = carregar_empresas(self.arquivo)
        self.checkpoint = self.base / 'lote' / 'checkpoint.json'

    def test_le_csv_textual_e_rejeita_duplicacao(self):
        self.assertEqual(self.empresas, [{'cnpj': '12345678000199', 'ie': '123456789'}])
        self.arquivo.write_text('cnpj;ie\n12345678000199;123456789\n12345678000199;123456789\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicado'):
            carregar_empresas(self.arquivo)

    def test_retorno_falha_nao_impede_proxima_empresa_e_concluida_nao_repete(self):
        empresas = self.empresas + [{'cnpj': '12345678000199', 'ie': '123456789'}]
        dados = preparar_checkpoint(self.checkpoint, empresas, '01/09/2026', '30/09/2026')
        chamadas = []

        def executar(empresa, *_args):
            chamadas.append(empresa['cnpj'])
            return {'status': 'FALHA' if len(chamadas) == 1 else 'CONCLUIDO'}

        executar_lote(dados, self.checkpoint, executar)
        self.assertEqual([x['status'] for x in dados['empresas']], ['FALHA', 'CONCLUIDO'])
        restaurado = preparar_checkpoint(self.checkpoint, empresas, '01/09/2026', '30/09/2026')
        executar_lote(restaurado, self.checkpoint, executar)
        self.assertEqual(chamadas, ['12345678000199', '12345678000199', '12345678000199'])

    def test_interrupcao_nao_gera_reenvio_automatico(self):
        dados = preparar_checkpoint(self.checkpoint, self.empresas, '01/09/2026', '30/09/2026')
        dados['empresas'][0]['status'] = 'EM_ANDAMENTO'
        with patch('lote_nfe.executar_empresa') as executar:
            executar_lote(dados, self.checkpoint, executar)
        executar.assert_not_called()
        self.assertEqual(dados['empresas'][0]['status'], 'INTERROMPIDO_VERIFICAR')

    def test_sucesso_exige_relatorio_novo_e_ambas_as_operacoes(self):
        pasta = self.base / 'coletas'
        nova = pasta / 'nova'
        for tipo in ('recebidas', 'emitidas'):
            (nova / tipo).mkdir(parents=True, exist_ok=True)
            (nova / tipo / 'chaves_extraidas.csv').write_text('chave_acesso\n', encoding='utf-8')
        resultado = {'periodo_inicial': '2026-09-01', 'periodo_final': '2026-09-30',
                     'csv_chaves': 'chaves_extraidas.csv', 'chaves_unicas': 0}
        arquivo = nova / 'relatorio.json'
        arquivo.write_text(json.dumps({'status': 'CONCLUIDO', 'tipos': {'recebidas': resultado}}))
        self.assertIsNone(_relatorio_novo(pasta, set(), '01/09/2026', '30/09/2026'))
        arquivo.write_text(json.dumps({'status': 'CONCLUIDO', 'tipos': {'recebidas': resultado, 'emitidas': resultado}}))
        self.assertIsNotNone(_relatorio_novo(pasta, set(), '01/09/2026', '30/09/2026'))
        self.assertIsNone(_relatorio_novo(pasta, {'nova'}, '01/09/2026', '30/09/2026'))


if __name__ == '__main__':
    unittest.main()
