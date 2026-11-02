"""Testes de nucleo/banco_loja.py: gravação direta nos bancos da loja."""
import json
import sys
import unittest
from pathlib import Path


def _raiz():
    d = Path(__file__).resolve()
    for p in d.parents:
        if (p / "montador.py").exists():
            return p
    return d.parent


sys.path.insert(0, str(_raiz()))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta catalogo/

from testes_suporte import tmpdir  # noqa: E402
from variacoes import constantes_especializado as ce  # noqa: E402
from nucleo import banco_loja as bl  # noqa: E402

VOCAB = {
    "tipos": {
        "tamanho": {"rotulo": "Tamanho", "opcoes": {"M": "M", "G": "G"}},
        "cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ"}},
    },
    "sinonimos": {},
}


class Base(unittest.TestCase):
    def setUp(self):
        with tmpdir() as td:
            self.caminho_vocab = Path(td) / "atributos.json"
            self.caminho_vocab.write_text(json.dumps(VOCAB), encoding="utf-8")
            ce.carregar(self.caminho_vocab)

    def _linhas(self):
        return [
            {"atributos": {"tamanho": "M", "cor": "Azul"}, "preco": 50.0,
             "quantidade": 5, "ilimitado": False, "imagem": ""},
            {"atributos": {"tamanho": "G", "cor": "Azul"}, "preco": 55.0,
             "quantidade": 3, "ilimitado": False, "imagem": ""},
        ]


class TestImagensComuns(unittest.TestCase):
    def test_comuns_a_todas(self):
        self.assertEqual(bl._imagens_comuns([["a", "b"], ["a", "c"]]), ["a"])

    def test_vazio(self):
        self.assertEqual(bl._imagens_comuns([]), [])


class TestModoSimples(Base):
    def test_gravar_novo_depois_manter_quantidade(self):
        with tmpdir() as td:
            db = Path(td) / "produtos.db"
            self.assertIsNone(bl.ler_estoque_simples_db(db, "A002"))
            self.assertTrue(bl.gravar_simples_db(db, "A002", "Suco", 4.5, 10, False))
            self.assertFalse(bl.gravar_simples_db(db, "A002", "Suco 2", 5.0, 999, False))
            self.assertEqual(bl.ler_estoque_simples_db(db, "A002"),
                             {"preco": 5.0, "quantidade": 10, "ilimitado": False})


class TestModoEspecializado(Base):
    def test_gravar_novo(self):
        with tmpdir() as td:
            db = Path(td) / "esp.db"
            r = bl.gravar_esp(db, "A000", "Blusa", self._linhas())
            self.assertEqual(sorted(r["novos"]), ["A000_G_AZ", "A000_M_AZ"])

    def test_regravar_mantem_quantidade(self):
        with tmpdir() as td:
            db = Path(td) / "esp.db"
            bl.gravar_esp(db, "A000", "Blusa", self._linhas())
            linhas2 = [dict(l, preco=60.0, quantidade=99) for l in self._linhas()]
            r = bl.gravar_esp(db, "A000", "Blusa Nova", linhas2)
            self.assertEqual(len(r["atualizados"]), 2)
            self.assertFalse(r["novos"])
            carregado = bl.carregar_produto_esp(db, "A000")
            self.assertEqual(carregado["valores"][("cor", "Azul"), ("tamanho", "M")]["preco"], 60.0)
            self.assertEqual(carregado["valores"][("cor", "Azul"), ("tamanho", "M")]["quantidade"], 5)

    def test_desativa_sku_removido(self):
        with tmpdir() as td:
            db = Path(td) / "esp.db"
            bl.gravar_esp(db, "A000", "Blusa", self._linhas())
            so_m = [self._linhas()[0]]
            r = bl.gravar_esp(db, "A000", "Blusa", so_m)
            self.assertEqual(r["desativados"], ["A000_G_AZ"])

    def test_validar_antes_de_gravar(self):
        with tmpdir() as td:
            db = Path(td) / "esp.db"
            self.assertEqual(bl.validar_antes_de_gravar(db, "A000", "Blusa", self._linhas(), bl.MODO_ESP), [])
            ruim = [{"atributos": {"tamanho": "XXL"}, "preco": 1, "quantidade": 1,
                     "ilimitado": False, "imagem": ""}]
            erros = bl.validar_antes_de_gravar(db, "A000", "Blusa", ruim, bl.MODO_ESP)
            self.assertTrue(erros and "XXL" in erros[0])
            erros = bl.validar_antes_de_gravar(db, "camiseta1", "X", self._linhas(), bl.MODO_ESP)
            self.assertTrue(erros and "ID inválido" in erros[0])


if __name__ == "__main__":
    unittest.main()
