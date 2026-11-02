"""Testes de variacoes/criar_banco_especializado.py: criação e validação do banco."""
import sqlite3
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
from variacoes import criar_banco_especializado as banco  # noqa: E402


class TestAtributosJson(unittest.TestCase):
    def test_canonico_ordenado(self):
        self.assertEqual(banco.atributos_json({"cor": "Azul", "tamanho": "M"}),
                         '{"cor":"Azul","tamanho":"M"}')

    def test_vazio(self):
        self.assertEqual(banco.atributos_json({}), "{}")


class TestCriar(unittest.TestCase):
    def test_cria_tabelas(self):
        with tmpdir() as td:
            caminho = str(Path(td) / "esp.db")
            banco.criar(caminho)
            con = sqlite3.connect(caminho)
            tabelas = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            self.assertTrue({"produtos", "skus", "imagens"} <= tabelas)


class TestValidar(unittest.TestCase):
    def test_banco_vazio_e_valido(self):
        with tmpdir() as td:
            caminho = str(Path(td) / "esp.db")
            banco.criar(caminho)
            self.assertEqual(banco.validar(caminho), [])

    def test_detecta_sku_orfa(self):
        with tmpdir() as td:
            caminho = str(Path(td) / "esp.db")
            banco.criar(caminho)
            con = sqlite3.connect(caminho)
            con.execute("INSERT INTO skus(sku, produto_id, atributos, preco) VALUES ('X001', 'X001', '{}', 10)")
            con.commit()
            con.close()
            problemas = banco.validar(caminho)
            self.assertTrue(any("produto dela não existe" in p for p in problemas))


class TestPreencherExemplo(unittest.TestCase):
    def test_preenche(self):
        with tmpdir() as td:
            caminho = str(Path(td) / "esp.db")
            banco.criar(caminho)
            banco.preencher_exemplo(caminho)
            con = sqlite3.connect(caminho)
            n_produtos = con.execute("SELECT COUNT(*) FROM produtos").fetchone()[0]
            n_skus = con.execute("SELECT COUNT(*) FROM skus").fetchone()[0]
            con.close()
            self.assertEqual(n_produtos, 4)
            self.assertEqual(n_skus, 13)


if __name__ == "__main__":
    unittest.main()
