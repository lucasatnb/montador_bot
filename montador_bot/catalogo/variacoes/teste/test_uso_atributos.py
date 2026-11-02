"""Testes de variacoes/uso_atributos.py: o que a loja já usa não pode ser excluído."""
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
from variacoes import uso_atributos as ua  # noqa: E402
from nucleo import gerar_pastas as gp  # noqa: E402
from nucleo import banco_loja as bl  # noqa: E402

VOCAB = {
    "tipos": {"cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ", "Verde": "VD"}}},
    "sinonimos": {},
}


class Base(unittest.TestCase):
    def _loja(self, td):
        loja = gp.Loja(Path(td) / "loja")
        loja.raiz.mkdir()
        loja.imagens.mkdir()
        loja.definir_modo(gp.MODO_ESP)
        (loja.raiz / "atributos.json").write_text(json.dumps(VOCAB), encoding="utf-8")
        ce.carregar(loja.arquivo_atributos)
        return loja

    def test_loja_vazia(self):
        with tmpdir() as td:
            self.assertEqual(ua.levantar(self._loja(td), VOCAB), {})

    def test_sku_em_uso(self):
        with tmpdir() as td:
            loja = self._loja(td)
            db = loja.banco_estoque(gp.MODO_ESP)
            bl.gravar_esp(db, "A000", "Blusa",
                          [{"atributos": {"cor": "Azul"}, "preco": 50.0,
                            "quantidade": 2, "ilimitado": False, "imagem": ""}])
            self.assertEqual(ua.levantar(loja, VOCAB), {"cor": {"Azul": ["A000"]}})

    def test_acrescimo_em_uso(self):
        with tmpdir() as td:
            loja = self._loja(td)
            gp.gravar_acrescimos_produto(loja, "A000",
                                         {"cor": {"afeta": True, "opcoes": {"Verde": 5.0}}})
            self.assertEqual(ua.levantar(loja, VOCAB), {"cor": {"Verde": ["A000"]}})


if __name__ == "__main__":
    unittest.main()
