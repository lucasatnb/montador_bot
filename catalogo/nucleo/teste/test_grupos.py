"""Testes de nucleo/grupos.py: grupos (subcategorias) de uma loja."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz (montador.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta catalogo/

from testes_suporte import tmpdir  # noqa: E402
from nucleo import grupos  # noqa: E402


class TestLerGravar(unittest.TestCase):
    def test_roundtrip(self):
        with tmpdir() as td:
            raiz = Path(td)
            grupos.gravar(raiz, {"Roupas Masculinas": ["Camisetas", "Calças"]})
            self.assertEqual(grupos.ler(raiz), {"Roupas Masculinas": ["Camisetas", "Calças"]})

    def test_ausente_vira_vazio(self):
        with tmpdir() as td:
            self.assertEqual(grupos.ler(Path(td)), {})

    def test_json_quebrado_vira_vazio(self):
        with tmpdir() as td:
            raiz = Path(td)
            (raiz / grupos.NOME).write_text("não é json", encoding="utf-8")
            self.assertEqual(grupos.ler(raiz), {})

    def test_categoria_em_dois_grupos_recusa(self):
        with tmpdir() as td:
            with self.assertRaises(grupos.GruposInvalidos):
                grupos.gravar(Path(td), {"A": ["X"], "B": ["X"]})

    def test_limpa_espacos_e_duplicados(self):
        with tmpdir() as td:
            grupos.gravar(Path(td), {"  Roupas  ": ["  Camisetas ", "Camisetas", ""]})
            self.assertEqual(grupos.ler(Path(td)), {"Roupas": ["Camisetas"]})


class TestConsultas(unittest.TestCase):
    def setUp(self):
        self.dados = {"Roupas": ["Camisetas", "Calças"], "Calçados": ["Tênis"]}

    def test_grupo_da_categoria(self):
        self.assertEqual(grupos.grupo_da_categoria(self.dados, "calças"), "Roupas")
        self.assertIsNone(grupos.grupo_da_categoria(self.dados, "Bonés"))

    def test_categorias_do_grupo(self):
        self.assertEqual(grupos.categorias_do_grupo(self.dados, "roupas"), ["Camisetas", "Calças"])

    def test_sem_grupo(self):
        self.assertEqual(grupos.sem_grupo(["Camisetas", "Bonés", "Calças"], self.dados), ["Bonés"])


class TestEdicoes(unittest.TestCase):
    def setUp(self):
        self.dados = {"Roupas": ["Camisetas", "Calças"], "Calçados": ["Tênis"]}

    def test_adicionar_grupo(self):
        novo = grupos.adicionar_grupo(self.dados, "Acessórios", ["Bonés", "Camisetas"])
        self.assertEqual(novo["Acessórios"], ["Bonés", "Camisetas"])
        self.assertEqual(novo["Roupas"], ["Camisetas", "Calças"])

    def test_gravar_recusa_categoria_em_dois_grupos(self):
        with tmpdir() as td:
            com_dup = {"Roupas": ["Camisetas"], "Calçados": ["Tênis", "Camisetas"]}
            with self.assertRaises(grupos.GruposInvalidos):
                grupos.gravar(Path(td), com_dup)

    def test_renomear(self):
        novo = grupos.renomear_grupo(self.dados, "Roupas", "Vestuário")
        self.assertEqual(novo, {"Vestuário": ["Camisetas", "Calças"], "Calçados": ["Tênis"]})

    def test_remover_grupo(self):
        novo = grupos.remover_grupo(self.dados, "Roupas")
        self.assertEqual(novo, {"Calçados": ["Tênis"]})

    def test_mover_categoria(self):
        novo = grupos.mover_categoria(self.dados, "Camisetas", "Calçados")
        self.assertEqual(novo["Roupas"], ["Calças"])
        self.assertEqual(novo["Calçados"], ["Tênis", "Camisetas"])

    def test_mover_para_sem_grupo(self):
        novo = grupos.mover_categoria(self.dados, "Tênis", "")
        self.assertNotIn("Tênis", novo["Calçados"])


if __name__ == "__main__":
    unittest.main()
