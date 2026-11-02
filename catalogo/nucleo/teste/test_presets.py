"""Testes de nucleo/presets.py: listas prontas de grupos/categorias/atributos."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz (montador.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta catalogo/

from nucleo import presets  # noqa: E402


class TestListar(unittest.TestCase):
    def test_tem_listas(self):
        lista = presets.listar()
        nomes = [p["nome"] for p in lista]
        self.assertIn("Moda masculina", nomes)
        self.assertIn("Ótica", nomes)

    def test_cada_lista_tem_grupos_e_categorias(self):
        for p in presets.listar():
            self.assertTrue(p["grupos"], p["nome"])
            self.assertTrue(p["categorias"], p["nome"])
            for item in p["categorias"]:
                self.assertTrue(item["nome"].strip())
                # toda categoria da lista está em algum grupo da própria lista
                self.assertIn(item["grupo"], p["grupos"], (p["nome"], item["nome"]))


class TestPlano(unittest.TestCase):
    def setUp(self):
        self.preset = presets.obter("moda_masculina")

    def test_loja_vazia_cria_tudo(self):
        plano = presets.plano(self.preset, [], {}, set())
        self.assertEqual(len(plano["categorias_novas"]), len(self.preset["categorias"]))
        self.assertEqual(set(plano["grupos_novos"]), set(self.preset["grupos"]))

    def test_categoria_existente_e_ignorada(self):
        plano = presets.plano(self.preset, ["Camisetas"], {}, set())
        self.assertNotIn("Camisetas", plano["categorias_novas"])
        self.assertIn("Camisetas", plano["categorias_ignoradas"])

    def test_atributos_faltantes(self):
        plano = presets.plano(self.preset, [], {}, {"tamanho"})
        self.assertIn("cor", plano["atributos_faltantes"])
        self.assertNotIn("tamanho", plano["atributos_faltantes"])

    def test_categoria_ja_em_outro_grupo_avisa(self):
        plano = presets.plano(self.preset, ["Camisetas"], {"Outro": ["Camisetas"]}, set())
        self.assertIn(("Camisetas", "Outro"), plano["categorias_em_grupo"])


if __name__ == "__main__":
    unittest.main()
