"""Testes de variacoes/atributos_loja.py: vocabulário de variações (regras de edição)."""
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
from variacoes import atributos_loja as al  # noqa: E402

VOCAB = {
    "tipos": {
        "cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ", "Verde": "VD"}},
    },
    "sinonimos": {"azulzinho": "Azul"},
}


class TestTextos(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(al.normalizar("  PÃO de Queijo! "), "pao de queijo")

    def test_chave_do_tipo(self):
        self.assertEqual(al.chave_do_tipo("Numeração"), "numeracao")
        self.assertEqual(al.chave_do_tipo("Cor"), "cor")

    def test_decodificar_texto(self):
        self.assertEqual(al.decodificar_texto("abc"), "abc")
        self.assertEqual(al.decodificar_texto("café".encode("utf-8")), "café")
        self.assertEqual(al.decodificar_texto("café".encode("cp1252")), "café")


class TestSugerirCodigo(unittest.TestCase):
    def test_primeiras_letras(self):
        self.assertEqual(al.sugerir_codigo("Verde", set()), "VE")
        self.assertEqual(al.sugerir_codigo("P", set()), "P")

    def test_alonga_se_usado(self):
        self.assertEqual(al.sugerir_codigo("Verde", {"VE"}), "VER")
        self.assertEqual(al.sugerir_codigo("Verde", {"VE", "VER", "VERD", "VERDE"}), "VERDE2")

    def test_sem_letras_levanta(self):
        with self.assertRaises(al.VocabularioInvalido):
            al.sugerir_codigo("!!!", set())


class TestVazioELer(unittest.TestCase):
    def test_vazio(self):
        self.assertEqual(al.vazio(), {"tipos": {}, "sinonimos": {}})

    def test_ler_ausente(self):
        with tmpdir() as td:
            self.assertEqual(al.ler(Path(td) / "nada.json"), al.vazio())

    def test_ler_json_invalido(self):
        with tmpdir() as td:
            p = Path(td) / "a.json"
            p.write_text("não é json", encoding="utf-8")
            with self.assertRaises(al.VocabularioInvalido):
                al.ler(p)


class TestComTipo(unittest.TestCase):
    def test_adiciona(self):
        self.assertEqual(al.com_tipo(al.vazio(), "Cor")["tipos"]["cor"],
                         {"rotulo": "Cor", "opcoes": {}})

    def test_duplicado(self):
        with self.assertRaises(al.VocabularioInvalido):
            al.com_tipo(al.com_tipo(al.vazio(), "Cor"), "Côr")


class TestComOpcao(unittest.TestCase):
    def test_adiciona_com_codigo_auto(self):
        d = al.com_opcao(al.com_tipo(al.vazio(), "Cor"), "cor", "Azul")
        self.assertEqual(d["tipos"]["cor"]["opcoes"], {"Azul": "AZ"})

    def test_opcao_duplicada_ignora_caixa(self):
        d = al.com_opcao(al.com_tipo(al.vazio(), "Cor"), "cor", "Azul")
        with self.assertRaises(al.VocabularioInvalido):
            al.com_opcao(d, "cor", "azul")

    def test_opcao_com_caractere_proibido(self):
        d = al.com_tipo(al.vazio(), "Cor")
        with self.assertRaises(al.VocabularioInvalido):
            al.com_opcao(d, "cor", "Az;ul")


class TestComSinonimo(unittest.TestCase):
    def test_adiciona(self):
        d = al.com_opcao(al.com_tipo(al.vazio(), "Cor"), "cor", "Azul")
        self.assertEqual(al.com_sinonimo(d, "Azulzinho", "Azul")["sinonimos"],
                         {"azulzinho": "Azul"})

    def test_aponta_para_opcao_inexistente(self):
        with self.assertRaises(al.VocabularioInvalido):
            al.com_sinonimo(al.vazio(), "azulzinho", "Azul")


class TestSalvar(unittest.TestCase):
    def test_grava_e_rele(self):
        with tmpdir() as td:
            caminho = Path(td) / "atributos.json"
            al.salvar(caminho, VOCAB)
            self.assertEqual(al.ler(caminho), VOCAB)

    def test_nao_remove_sem_uso(self):
        with tmpdir() as td:
            caminho = Path(td) / "atributos.json"
            al.salvar(caminho, VOCAB)
            removido = {"tipos": {"cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ"}}},
                        "sinonimos": {}}
            with self.assertRaises(al.VocabularioInvalido):
                al.salvar(caminho, removido)  # uso=None: nada pode sair

    def test_remove_com_uso_vazio(self):
        with tmpdir() as td:
            caminho = Path(td) / "atributos.json"
            al.salvar(caminho, VOCAB)
            removido = {"tipos": {"cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ"}}},
                        "sinonimos": {}}
            al.salvar(caminho, removido, uso={})
            self.assertNotIn("Verde", al.ler(caminho)["tipos"]["cor"]["opcoes"])


class TestSinonimosDoTexto(unittest.TestCase):
    def test_por_linha(self):
        novo, rel = al.com_sinonimos_do_texto(VOCAB, "Azul: azulzinho, azulado\nVerde: verdinho", None)
        self.assertEqual(rel["novos"], [("azulado", "Azul"), ("verdinho", "Verde")])
        self.assertEqual(rel["repetidos"], ["azulzinho"])

    def test_linha_sem_opcao_nem_padrao(self):
        _, rel = al.com_sinonimos_do_texto(VOCAB, "azulzinho", None)
        self.assertEqual(rel["novos"], [])
        self.assertTrue(rel["problemas"])


class TestComPadrao(unittest.TestCase):
    def test_soma_o_que_falta(self):
        with tmpdir() as td:
            padrao = Path(td) / "padrao.json"
            padrao.write_text(json.dumps({
                "tipos": {"cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ", "Roxo": "RX"}}},
                "sinonimos": {"roxinho": "Roxo"},
            }), encoding="utf-8")
            d = al.com_padrao(al.vazio(), padrao)
            self.assertEqual(d["tipos"]["cor"]["opcoes"], {"Azul": "AZ", "Roxo": "RX"})
            self.assertEqual(d["sinonimos"], {"roxinho": "Roxo"})


class TestRemoviveis(unittest.TestCase):
    def test_opcoes_removiveis(self):
        self.assertEqual(al.opcoes_removiveis(VOCAB, {"cor": {"Azul": ["A000"]}}),
                         [("cor", "Verde")])

    def test_tipos_removiveis(self):
        self.assertEqual(al.tipos_removiveis(VOCAB, {}), ["cor"])

    def test_sinonimos_removiveis(self):
        self.assertEqual(al.sinonimos_removiveis(VOCAB, {"cor": {}}), ["azulzinho"])

    def test_com_opcao_removida(self):
        d = al.com_opcao_removida(VOCAB, "cor", "Verde", {"cor": {"Azul": ["A000"]}})
        self.assertEqual(d["tipos"]["cor"]["opcoes"], {"Azul": "AZ"})

    def test_com_opcao_removida_recusa_em_uso(self):
        with self.assertRaises(al.VocabularioInvalido):
            al.com_opcao_removida(VOCAB, "cor", "Verde", {"cor": {"Verde": ["A000"]}})

    def test_com_tipo_removido_limpa_orfas(self):
        d = al.com_tipo_removido(VOCAB, "cor", {})
        self.assertEqual(d["tipos"], {})
        self.assertEqual(d["sinonimos"], {})

    def test_com_sinonimos_removidos(self):
        d = al.com_sinonimos_removidos(VOCAB, ["azulzinho"], {"cor": {}})
        self.assertEqual(d["sinonimos"], {})


if __name__ == "__main__":
    unittest.main()
