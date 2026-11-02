"""Modelos de dados do bot de estoque: só dataclasses e a exceção de banco inválido.

Este módulo não importa nenhum outro módulo do projeto (é a base do grafo de imports).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class BancoInvalido(Exception):
    """Banco ausente ou fora do formato esperado, com mensagem em linguagem simples."""


@dataclass
class Produto:
    """Dois papéis, com a mesma classe:

    - SKU (o que é VENDIDO): id = código do SKU ("A001_VE_G"), nome = "Blusa verde G", com o preço,
      o estoque e as imagens daquela variação. `atributos` = {"cor": "verde", "tamanho": "g"}.
    - produto-base (o que o cliente PROCURA pelo nome): id = id do produto ("A001"), nome = "Blusa";
      `variacoes` = seus SKUs; preço = o MENOR entre eles; quantidade = a soma dos SKUs.
    """
    id: str = ""
    nome: str = ""
    preco: float = 0.0
    quantidade: int = 0
    imagens: list = field(default_factory=list)
    ilimitado: bool = False  # True = estoque infinito (quantidade vira inf e nunca é descontada)
    atributos: dict = field(default_factory=dict)   # SKU: {"cor": "verde", "tamanho": "g"}; base: {}
    variacoes: list = field(default_factory=list)   # base: seus SKUs (Produto); SKU: []
    base_id: str = ""                               # SKU: id do produto-base
    nome_base: str = ""                             # SKU: nome do produto-base ("Blusa")


@dataclass
class Resposta:
    status: str
    mensagem: str
    produto: Optional[Produto] = None
    quantidade: int = 0                         # total de unidades separadas (status "ok")
    opcoes: list = field(default_factory=list)  # candidatos (status "reperguntar", item único)
    itens: list = field(default_factory=list)   # [(Produto, qtd)] separados (status "ok")
    a_confirmar: list = field(default_factory=list)  # [(Produto, qtd)] esperando o "sim" (status "reperguntar"); NÃO descontado
    codigo: bool = False                        # True = o pedido veio por CÓDIGO da landing page (já confirmado): o atendimento fecha direto

    def _pares(self) -> list:
        """[(Produto, qtd pedida)] do que foi realmente separado (só status "ok")."""
        return list(self.itens)

    # Listas paralelas: o índice i de todas elas é o mesmo item do pedido.
    @property
    def produtos(self) -> list:
        """Lista de Produto do pedido."""
        return [p for p, _ in self._pares()]

    @property
    def ids(self) -> list:
        return [p.id for p, _ in self._pares()]

    @property
    def nomes(self) -> list:
        return [p.nome for p, _ in self._pares()]

    @property
    def precos(self) -> list:
        """Preço unitário de cada item."""
        return [p.preco for p, _ in self._pares()]

    @property
    def quantidades(self) -> list:
        """Quantidade PEDIDA de cada item (a que vai para a comanda)."""
        return [q for _, q in self._pares()]

    @property
    def subtotais(self) -> list:
        """preço x quantidade pedida de cada item."""
        return [p.preco * q for p, q in self._pares()]

    @property
    def imagens(self) -> list:
        """Lista de listas: os links de imagem de cada item."""
        return [p.imagens for p, _ in self._pares()]

    @property
    def estoques(self) -> list:
        """Quanto sobrou no estoque de cada item (inf = estoque infinito)."""
        return [p.quantidade for p, _ in self._pares()]
