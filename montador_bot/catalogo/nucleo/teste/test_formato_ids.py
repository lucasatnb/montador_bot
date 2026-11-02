"""Testes de nucleo/formato_ids.py: IDs, SKUs e itens de carrinho do modo especializado."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # pasta catalogo/

from nucleo.formato_ids import (  # noqa: E402
    FormatoInvalido,
    decodificar_item,
    montar_item_carrinho,
    montar_sku,
    proximo_id,
    validar_codigos,
    validar_id,
)


class TestValidarId(unittest.TestCase):
    def test_aceita_e_normaliza(self):
        self.assertEqual(validar_id("  p001 "), "P001")

    def test_recusa_formato_invalido(self):
        for ruim in ("", "1", "P1", "PP001", "P0000", "camiseta", "p01"):
            with self.assertRaises(FormatoInvalido):
                validar_id(ruim)


class TestProximoId(unittest.TestCase):
    def test_primeiro_livre(self):
        self.assertEqual(proximo_id([]), "A000")

    def test_pula_usados_e_ignora_invalidos(self):
        self.assertEqual(proximo_id(["A000", "A001", "xxxx", ""]), "A002")

    def test_vira_para_a_proxima_letra(self):
        usados = {f"A{i:03d}" for i in range(1000)}
        self.assertEqual(proximo_id(usados), "B000")

    def test_esgotou_todos(self):
        todos = {f"{chr(65 + l)}{n:03d}" for l in range(26) for n in range(1000)}
        with self.assertRaises(FormatoInvalido):
            proximo_id(todos)


class TestValidarCodigos(unittest.TestCase):
    def test_aceita(self):
        validar_codigos({"cor": {"Azul": "AZ", "Verde": "VD"}})  # não deve levantar

    def test_codigo_com_caractere_invalido(self):
        with self.assertRaises(FormatoInvalido):
            validar_codigos({"cor": {"Azul": "A_Z"}})

    def test_codigo_repetido_no_mesmo_tipo(self):
        with self.assertRaises(FormatoInvalido):
            validar_codigos({"cor": {"Azul": "X", "Verde": "X"}})


class TestMontarSku(unittest.TestCase):
    def setUp(self):
        self.variantes = {"tamanho": ["M", "G"], "cor": ["Azul", "Verde"]}
        self.codigos = {"tamanho": {"M": "M", "G": "G"}, "cor": {"Azul": "AZ", "Verde": "VD"}}

    def test_sem_atributos(self):
        self.assertEqual(montar_sku("P001", {}, self.variantes, self.codigos), "P001")

    def test_segue_a_ordem_das_variantes(self):
        sku = montar_sku("P001", {"tamanho": "G", "cor": "Azul"}, self.variantes, self.codigos)
        self.assertEqual(sku, "P001_G_AZ")

    def test_tipo_desconhecido(self):
        with self.assertRaises(FormatoInvalido):
            montar_sku("P001", {"peso": "Leve"}, self.variantes, self.codigos)

    def test_opcao_inexistente(self):
        with self.assertRaises(FormatoInvalido):
            montar_sku("P001", {"cor": "Roxo"}, self.variantes, self.codigos)

    def test_falta_codigo_da_opcao(self):
        codigos = {"cor": {}, "tamanho": {}}
        with self.assertRaises(FormatoInvalido):
            montar_sku("P001", {"cor": "Azul"}, self.variantes, codigos)


class TestMontarItemCarrinho(unittest.TestCase):
    def test_sem_variacao(self):
        self.assertEqual(montar_item_carrinho("P001", 3), "P001_3")

    def test_com_variacao(self):
        self.assertEqual(montar_item_carrinho("P001_G_AZ", 2), "P001_2_G_AZ")

    def test_quantidade_invalida(self):
        for q in (0, 1000, -1, True, 1.5, "2"):
            with self.assertRaises(FormatoInvalido):
                montar_item_carrinho("P001", q)

    def test_sku_invalida(self):
        with self.assertRaises(FormatoInvalido):
            montar_item_carrinho("camiseta", 1)


class TestDecodificarItem(unittest.TestCase):
    def test_sem_variacao(self):
        self.assertEqual(decodificar_item("P001_3", ["P001"]),
                         {"id": "P001", "quantidade": 3, "sku": "P001"})

    def test_com_variacao(self):
        skus = ["P001_G_AZ", "P001_M_AZ"]
        self.assertEqual(decodificar_item("P001_2_G_AZ", skus),
                         {"id": "P001", "quantidade": 2, "sku": "P001_G_AZ"})

    def test_sku_inexistente(self):
        with self.assertRaises(FormatoInvalido):
            decodificar_item("P001_2_G_AZ", ["P001_M_AZ"])

    def test_aceita_mapping(self):
        self.assertEqual(decodificar_item("P001_1", {"P001": None})["sku"], "P001")

    def test_quantidade_fora_da_faixa(self):
        with self.assertRaises(FormatoInvalido):
            decodificar_item("P001_0", ["P001"])


if __name__ == "__main__":
    unittest.main()
