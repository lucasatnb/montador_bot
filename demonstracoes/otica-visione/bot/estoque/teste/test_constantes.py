"""Testes de estoque/constantes.py: status, vocabulário e regex pré-compiladas."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta modelo/

from estoque import constantes as c  # noqa: E402


class TestStatus(unittest.TestCase):
    def test_status_distintos(self):
        status = {c.OK, c.REPERGUNTAR, c.SEM_ESTOQUE, c.NAO_ENCONTRADO, c.CANCELADO, c.ERRO}
        self.assertEqual(len(status), 6)


class TestVocabulario(unittest.TestCase):
    def test_negacao_tem_nao(self):
        self.assertIn("nao", c._NEGACAO)

    def test_numeros_extensos(self):
        self.assertEqual(c._NUM_EXT["vinte"], 20)
        self.assertEqual(c._NUM_EXT["cem"], 100)

    def test_db_por_modo(self):
        self.assertEqual(c.DB_POR_MODO["especializado"], "produtos_especializados.db")

    def test_limite_codigo(self):
        self.assertEqual(c.MAX_QTD_CODIGO, 999)


class TestRegex(unittest.TestCase):
    def test_qtd_inicio(self):
        self.assertEqual(c.RE_QTD_INICIO.match("40 blusas").group(1), "40")
        self.assertEqual(c.RE_QTD_INICIO.match("x40 blusas").group(1), "40")

    def test_e_mais_palavra(self):
        self.assertTrue(c.RE_E_MAIS_PALAVRA.search("peito e frango"))
        self.assertFalse(c.RE_E_MAIS_PALAVRA.search("queijo"))

    def test_hex(self):
        self.assertTrue(c.RE_HEX.fullmatch("1a2B"))


if __name__ == "__main__":
    unittest.main()
