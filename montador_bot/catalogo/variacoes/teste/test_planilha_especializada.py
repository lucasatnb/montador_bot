"""Testes de variacoes/planilha_especializada.py: combinações, validação e estado da grade."""
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
from variacoes import planilha_especializada as pe  # noqa: E402

VOCAB = {
    "tipos": {
        "tamanho": {"rotulo": "Tamanho", "opcoes": {"P": "P", "M": "M", "G": "G"}},
        "cor": {"rotulo": "Cor", "opcoes": {"Azul": "AZ", "Verde": "VD"}},
    },
    "sinonimos": {},
}


class Base(unittest.TestCase):
    def setUp(self):
        with tmpdir() as td:
            caminho = Path(td) / "atributos.json"
            caminho.write_text(json.dumps(VOCAB), encoding="utf-8")
            ce.carregar(caminho)


class TestGerarCombinacoes(Base):
    def test_vazio(self):
        self.assertEqual(pe.gerar_combinacoes({}), [{}])

    def test_segue_ordem_das_variantes(self):
        r = pe.gerar_combinacoes({"tamanho": ["M", "G"], "cor": ["Azul"]})
        self.assertEqual(r, [{"tamanho": "M", "cor": "Azul"}, {"tamanho": "G", "cor": "Azul"}])

    def test_tipo_desconhecido(self):
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.gerar_combinacoes({"peso": ["Leve"]})

    def test_opcoes_repetidas(self):
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.gerar_combinacoes({"tamanho": ["M", "M"]})


class TestPrecoNumerico(unittest.TestCase):
    def test_converte(self):
        self.assertEqual(pe.preco_numerico("49,90"), 49.9)
        self.assertEqual(pe.preco_numerico("R$ 10,50"), 10.5)
        self.assertEqual(pe.preco_numerico(10), 10.0)

    def test_invalido_devolve_padrao(self):
        self.assertEqual(pe.preco_numerico("abc"), 0.0)
        self.assertEqual(pe.preco_numerico("abc", 7.0), 7.0)


class TestChaveAtributos(unittest.TestCase):
    def test_ordem_nao_importa(self):
        a = pe.chave_atributos({"cor": "Azul", "tamanho": "M"})
        b = pe.chave_atributos({"tamanho": "M", "cor": "Azul"})
        self.assertEqual(a, b)
        self.assertEqual(a, (("cor", "Azul"), ("tamanho", "M")))


class TestValidar(Base):
    def _linha(self, **muda):
        linha = {"id": "P001", "nome": "Blusa", "sku": "P001_M_AZ", "preco": "50,00",
                 "quantidade": 5, "tamanho": "M", "cor": "Azul"}
        linha.update(muda)
        return linha

    def test_aceita_valida(self):
        self.assertTrue(pe.validar([self._linha()]))

    def test_recusa_id_invalido(self):
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.validar([self._linha(id="camiseta1")])

    def test_recusa_sku_repetida(self):
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.validar([self._linha(), self._linha()])

    def test_recusa_opcao_inexistente(self):
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.validar([self._linha(cor="Roxo")])

    def test_recusa_conjuntos_diferentes_de_tipos(self):
        outra = self._linha(sku="P001_M", cor=None)
        with self.assertRaises(pe.PlanilhaInvalida):
            pe.validar([self._linha(), outra])


class TestEstado(Base):
    def test_nenhum_salvo(self):
        est = pe.estado_a_partir_do_salvo(None, 40.0)
        self.assertFalse(est["tem_variacoes"])
        self.assertEqual(est["simples"]["preco"], 40.0)

    def test_a_partir_do_salvo(self):
        salvo = {"tipos": {"tamanho": ["M", "G"]},
                 "valores": {("tamanho", "M"): {"sku": "P001_M", "preco": 50.0,
                                                 "quantidade": 5, "ilimitado": False}}}
        est = pe.estado_a_partir_do_salvo(salvo, 40.0)
        self.assertTrue(est["tem_variacoes"])
        self.assertEqual(est["tipos"], {"tamanho": ["M", "G"]})


class TestMesclarValores(unittest.TestCase):
    def test_mescla(self):
        self.assertEqual(pe.mesclar_valores({"a": {"x": 1}}, {"a": {"y": 2}, "b": {"z": 3}}),
                         {"a": {"x": 1, "y": 2}, "b": {"z": 3}})


class TestMontarDadosGrade(Base):
    def test_combina_salvo_com_padrao(self):
        combos = [{"tamanho": "M"}, {"tamanho": "G"}]
        valores = {pe.chave_atributos({"tamanho": "M"}): {"sku": "P001_M", "preco": 50.0,
                                                          "quantidade": 3, "ilimitado": False}}
        dados = pe.montar_dados_grade("P001", combos, valores, 40.0)
        self.assertEqual(dados[0]["SKU"], "P001_M")
        self.assertEqual(dados[0]["preco"], 50.0)
        self.assertEqual(dados[1]["SKU"], "P001_G")
        self.assertEqual(dados[1]["preco"], 40.0)
        self.assertEqual(dados[1]["quantidade"], 0)


class TestChaveGrade(Base):
    def test_determinista(self):
        a = pe.chave_grade("P001", "v1", {"tamanho": ["M", "G"]})
        b = pe.chave_grade("P001", "v1", {"tamanho": ["M", "G"]})
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("grade_estoque_P001_v1_"))


if __name__ == "__main__":
    unittest.main()
