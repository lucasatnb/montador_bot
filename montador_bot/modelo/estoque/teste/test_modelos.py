"""Testes de estoque/modelos.py: as dataclasses Produto e Resposta."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta modelo/

from estoque.modelos import BancoInvalido, Produto, Resposta  # noqa: E402


class TestProduto(unittest.TestCase):
    def test_valores_padrao(self):
        p = Produto()
        self.assertEqual(p.id, "")
        self.assertEqual(p.nome, "")
        self.assertEqual(p.preco, 0.0)
        self.assertEqual(p.quantidade, 0)
        self.assertEqual(p.imagens, [])
        self.assertFalse(p.ilimitado)
        self.assertEqual(p.atributos, {})
        self.assertEqual(p.variacoes, [])

    def test_cada_instancia_tem_suas_listas(self):
        a, b = Produto(), Produto()
        a.imagens.append("x")
        self.assertEqual(b.imagens, [])


class TestResposta(unittest.TestCase):
    def _resposta_ok(self):
        p1 = Produto(id="A001", nome="Blusa", preco=10.0)
        p2 = Produto(id="A002", nome="Calça", preco=20.0, quantidade=7)
        return Resposta("ok", "mensagem", itens=[(p1, 2), (p2, 3)]), p1, p2

    def test_listas_paralelas(self):
        r, p1, p2 = self._resposta_ok()
        self.assertEqual(r.produtos, [p1, p2])
        self.assertEqual(r.ids, ["A001", "A002"])
        self.assertEqual(r.nomes, ["Blusa", "Calça"])
        self.assertEqual(r.precos, [10.0, 20.0])
        self.assertEqual(r.quantidades, [2, 3])
        self.assertEqual(r.subtotais, [20.0, 60.0])
        self.assertEqual(r.estoques, [0, 7])

    def test_sem_itens(self):
        r = Resposta("reperguntar", "qual cor?")
        self.assertEqual(r.produtos, [])
        self.assertEqual(r.subtotais, [])

    def test_codigo_flag(self):
        self.assertFalse(Resposta("ok", "").codigo)
        self.assertTrue(Resposta("ok", "", codigo=True).codigo)


class TestBancoInvalido(unittest.TestCase):
    def test_e_exception(self):
        with self.assertRaises(BancoInvalido):
            raise BancoInvalido("banco ausente")


if __name__ == "__main__":
    unittest.main()
