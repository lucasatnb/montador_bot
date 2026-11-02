"""Testes de estoque/utilidades.py: formatação e limpeza de texto (funções puras)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta modelo/

from estoque.modelos import Produto  # noqa: E402
from estoque.utilidades import (  # noqa: E402
    juntar,
    juntar_ou,
    nome_variacao,
    normalizar,
    preco_exibido,
    reais,
    rotulo_opcao,
)


class TestNormalizar(unittest.TestCase):
    def test_minusculas_sem_acento_sem_pontuacao(self):
        self.assertEqual(normalizar("  PÃO-de-Queijo!  "), "pao de queijo")

    def test_espacos_unicos(self):
        self.assertEqual(normalizar("a   b\n\tc"), "a b c")

    def test_vazio(self):
        self.assertEqual(normalizar(""), "")
        self.assertEqual(normalizar("!!!***"), "")


class TestJuntar(unittest.TestCase):
    def test_um(self):
        self.assertEqual(juntar(["a"]), "a")

    def test_dois(self):
        self.assertEqual(juntar(["a", "b"]), "a e b")

    def test_tres(self):
        self.assertEqual(juntar(["a", "b", "c"]), "a, b e c")


class TestJuntarOu(unittest.TestCase):
    def test_um(self):
        self.assertEqual(juntar_ou(["verde"]), "verde")

    def test_dois(self):
        self.assertEqual(juntar_ou(["verde", "preto"]), "verde ou preto")

    def test_tres(self):
        self.assertEqual(juntar_ou(["verde", "preto", "azul"]), "verde, preto ou azul")


class TestReais(unittest.TestCase):
    def test_formato_brasileiro(self):
        self.assertEqual(reais(1234.5), "R$ 1.234,50")
        self.assertEqual(reais(0), "R$ 0,00")
        self.assertEqual(reais(1000000), "R$ 1.000.000,00")


class TestPrecoExibido(unittest.TestCase):
    def test_sku(self):
        self.assertEqual(preco_exibido(Produto(preco=50.0)), "R$ 50,00")

    def test_base_com_precos_iguais(self):
        b = Produto(preco=50.0, variacoes=[Produto(preco=50.0), Produto(preco=50.0)])
        self.assertEqual(preco_exibido(b), "R$ 50,00")

    def test_base_com_precos_diferentes(self):
        b = Produto(preco=50.0, variacoes=[Produto(preco=50.0), Produto(preco=70.0)])
        self.assertEqual(preco_exibido(b), "a partir de R$ 50,00")


class TestRotuloOpcao(unittest.TestCase):
    def test_sigla_em_maiuscula(self):
        self.assertEqual(rotulo_opcao("g"), "G")
        self.assertEqual(rotulo_opcao("xg"), "XG")

    def test_palavra_long_preserva_caixa(self):
        self.assertEqual(rotulo_opcao("verde"), "verde")
        self.assertEqual(rotulo_opcao("42"), "42")


class TestNomeVariacao(unittest.TestCase):
    def test_monta_nome(self):
        self.assertEqual(nome_variacao("Blusa", {"cor": "verde", "tamanho": "g"}), "Blusa verde G")

    def test_sem_atributos(self):
        self.assertEqual(nome_variacao("Refri", {}), "Refri")


if __name__ == "__main__":
    unittest.main()
