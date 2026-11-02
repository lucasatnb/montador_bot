"""Testes de variacoes/constantes_especializado.py: carregamento do vocabulário da loja."""
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

VOCAB = {
    "tipos": {
        "cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ", "Verde": "VD"}},
        "tamanho": {"rotulo": "Tamanho", "opcoes": {"P": "P", "M": "M"}},
    },
    "sinonimos": {"azulzinho": "Azul"},
}


class TestCarregar(unittest.TestCase):
    def test_carrega_de_arquivo(self):
        with tmpdir() as td:
            caminho = Path(td) / "atributos.json"
            caminho.write_text(json.dumps(VOCAB), encoding="utf-8")
            ce.carregar(caminho)
        self.assertEqual(ce.VARIANTES["cor"], ["Azul", "Verde"])
        self.assertEqual(ce.VARIANTES["tamanho"], ["P", "M"])
        self.assertEqual(ce.CODIGOS["tamanho"], {"P": "P", "M": "M"})
        self.assertEqual(ce.ROTULOS["cor"], "Cor")
        self.assertEqual(ce.SINONIMOS["azulzinho"], "Azul")

    def test_arquivo_ausente_deixa_vazio(self):
        with tmpdir() as td:
            ce.carregar(Path(td) / "nao_existe_abc123.json")
        self.assertEqual(ce.VARIANTES, {})
        self.assertEqual(ce.SINONIMOS, {})


if __name__ == "__main__":
    unittest.main()
