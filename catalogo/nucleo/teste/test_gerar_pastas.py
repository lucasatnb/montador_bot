"""Testes de nucleo/gerar_pastas.py: a camada de dados do catálogo."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _raiz():
    d = Path(__file__).resolve()
    for p in d.parents:
        if (p / "montador.py").exists():
            return p
    return d.parent


sys.path.insert(0, str(_raiz()))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta catalogo/

from testes_suporte import tmpdir  # noqa: E402
from nucleo import gerar_pastas as gp  # noqa: E402


class _Up:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


class TestTextos(unittest.TestCase):
    def test_sem_acento(self):
        self.assertEqual(gp.sem_acento("pão-de-queijo"), "pao-de-queijo")

    def test_nome_pasta(self):
        self.assertEqual(gp.nome_pasta("a/b:c"), "a_b_c")
        self.assertEqual(gp.nome_pasta("  x. "), "x")


class TestLoja(unittest.TestCase):
    def _loja(self, td):
        loja = gp.Loja(Path(td) / "minha-loja")
        loja.raiz.mkdir()
        return loja

    def test_caminhos(self):
        with tmpdir() as td:
            loja = self._loja(td)
            self.assertEqual(loja.slug, "minha-loja")
            self.assertEqual(loja.db, loja.raiz / "catalogo.db")
            self.assertEqual(loja.banco_estoque(gp.MODO_ESP), loja.raiz / "produtos_especializados.db")
            self.assertEqual(loja.banco_estoque(gp.MODO_SIMPLES), loja.raiz / "produtos.db")
            self.assertEqual(loja.imagens, loja.raiz / "imagens")

    def test_nome_e_modo(self):
        with tmpdir() as td:
            loja = self._loja(td)
            self.assertEqual(loja.nome, "minha-loja")  # sem config: usa o slug
            loja.definir_nome("  Pizzaria   do Zé ")
            self.assertEqual(loja.nome, "Pizzaria do Zé")
            loja.definir_modo(gp.MODO_ESP)
            self.assertEqual(loja.modo, gp.MODO_ESP)
            loja.definir_orcamento(True)
            self.assertTrue(loja.orcamento)

    def test_definir_modo_invalido(self):
        with tmpdir() as td:
            loja = self._loja(td)
            with self.assertRaises(ValueError):
                loja.definir_modo("x")

    def test_pasta_produto_e_atributo(self):
        with tmpdir() as td:
            loja = self._loja(td)
            self.assertEqual(loja.pasta_produto("A000"), loja.imagens / "A000")
            self.assertEqual(loja.pasta_atributo("A000", "cor", "Azul"),
                             loja.imagens / "A000" / "cor" / "Azul")
            self.assertEqual(loja.caminho_pasta("A000"), "imagens/A000/")
            self.assertIsNone(loja.pasta_produto(""))  # id vazio não vira pasta


class TestImagens(unittest.TestCase):
    def test_listar_imagens_ordem(self):
        with tmpdir() as td:
            p = Path(td)
            for name in ("10.jpg", "capa.jpg", "01.jpg", "02.png"):
                (p / name).write_bytes(b"x")
            self.assertEqual([f.name for f in gp.listar_imagens(p)],
                             ["01.jpg", "02.png", "10.jpg", "capa.jpg"])

    def test_salvar_imagens_deduplica(self):
        with tmpdir() as td:
            pasta = Path(td)
            novos, repetidos = gp.salvar_imagens(pasta, [_Up("a.jpg", b"1"), _Up("b.png", b"2")])
            self.assertEqual((novos, repetidos), (2, 0))
            self.assertEqual([f.name for f in gp.listar_imagens(pasta)], ["01.jpg", "02.png"])
            # as mesmas de novo -> repetidas
            novos, repetidos = gp.salvar_imagens(pasta, [_Up("a.jpg", b"1"), _Up("c.jpeg", b"3")])
            self.assertEqual((novos, repetidos), (1, 1))
            self.assertIn("03.jpg", [f.name for f in gp.listar_imagens(pasta)])


class TestPrecoEAprovado(unittest.TestCase):
    def test_preco_do_sku(self):
        acresc = {"cor": {"afeta": True, "opcoes": {"Azul": 5.0, "Verde": 0.0}}}
        self.assertEqual(gp.preco_do_sku(50.0, {"cor": "Azul"}, acresc), 55.0)
        self.assertEqual(gp.preco_do_sku(50.0, {"cor": "Verde"}, acresc), 50.0)

    def test_aprovado(self):
        self.assertTrue(gp.aprovado({"descricao": "x", "categoria": "y"}))
        self.assertFalse(gp.aprovado({"descricao": "", "categoria": "y"}))
        self.assertFalse(gp.aprovado({"descricao": "x", "categoria": ""}))


class TestCatalogo(unittest.TestCase):
    def _loja(self, td):
        loja = gp.Loja(Path(td) / "loja")
        loja.raiz.mkdir()
        loja.imagens.mkdir()
        return loja

    def test_ler_catalogo_vazio_levanta(self):
        with tmpdir() as td:
            with self.assertRaises(FileNotFoundError):
                gp.ler_catalogo(self._loja(td))

    def test_gravar_e_ler(self):
        with tmpdir() as td:
            loja = self._loja(td)
            gp.gravar_produto_catalogo(loja, "A000", "Blusa", 50.0, "Bonita", "Roupas")
            cat = gp.ler_catalogo(loja)
            self.assertEqual(len(cat), 1)
            self.assertEqual(cat[0]["nome"], "Blusa")
            self.assertTrue(gp.aprovado(cat[0]))

    def test_ids_em_uso(self):
        with tmpdir() as td:
            loja = self._loja(td)
            (loja.imagens / "A001").mkdir()
            gp.gravar_produto_catalogo(loja, "A000", "Blusa", 50.0, "B", "Roupas")
            self.assertEqual(gp.ids_em_uso(loja, []), {"A000", "A001"})


class TestAcrescimos(unittest.TestCase):
    def test_gravar_e_ler(self):
        with tmpdir() as td:
            loja = gp.Loja(Path(td) / "loja")
            loja.raiz.mkdir()
            gp.gravar_acrescimos_produto(loja, "a000",
                                         {"cor": {"afeta": True, "opcoes": {"Azul": 5.0}}})
            self.assertEqual(gp.acrescimos_do_produto(loja, "A000"),
                             {"cor": {"afeta": True, "opcoes": {"Azul": 5.0}}})
            gp.gravar_acrescimos_produto(loja, "A000", {})  # vazio remove
            self.assertEqual(gp.ler_acrescimos(loja), {})


class TestCriarLoja(unittest.TestCase):
    def test_criar_e_zerar(self):
        with tmpdir() as td:
            alvo = Path(td) / "loja"
            with patch.object(gp, "PASTA_LOJA", alvo):
                self.assertIsNone(gp.loja_atual())
                loja = gp.criar_loja("  Pizzaria   do Zé ", gp.MODO_ESP)
                self.assertEqual(loja.nome, "Pizzaria do Zé")
                self.assertEqual(loja.modo, gp.MODO_ESP)
                with self.assertRaises(gp.ErroDados):
                    gp.criar_loja("Outra")
                gp.gravar_produto_catalogo(loja, "A000", "Pizza", 40.0, "Boa", "Pizzas")
                destino = gp.zerar_loja(loja)
                self.assertTrue((destino / "catalogo.db").is_file())
                self.assertFalse(loja.db.exists())
                self.assertTrue(loja.imagens.is_dir())


if __name__ == "__main__":
    unittest.main()
