import unittest

from coletar_cte import CONSULTAS, validar_schema


def schema(tipo_opcoes):
    return {
        'inputs': [{'name': 'dataInicial'}, {'name': 'dataFinal'}, {'name': 'btnConsultar'}],
        'selects': [{'name': 'tipoConsulta', 'options': tipo_opcoes}],
    }


class TestFormularioCte(unittest.TestCase):
    def test_escopo_solicitado_pelo_usuario(self):
        self.assertEqual(CONSULTAS['cte']['tipos'], ('Emissor', 'Tomador'))
        self.assertEqual(CONSULTAS['cteos']['tipos'], ('Emissor',))
        self.assertEqual(CONSULTAS['cte']['modelos'], {'57'})
        self.assertEqual(CONSULTAS['cteos']['modelos'], {'67'})

    def test_usa_valor_real_da_opcao(self):
        dados = schema([{'text': 'Emissor', 'value': '1'}, {'text': 'Tomador', 'value': '3'}])
        self.assertEqual(validar_schema(dados, 'Tomador'), '3')

    def test_nao_inventa_tipo_ausente(self):
        dados = schema([{'text': 'Emissor', 'value': '1'}])
        with self.assertRaisesRegex(RuntimeError, 'Tomador'):
            validar_schema(dados, 'Tomador')

    def test_exige_campos_observados(self):
        with self.assertRaisesRegex(RuntimeError, 'Campos'):
            validar_schema({'inputs': [], 'selects': []}, 'Emissor')
