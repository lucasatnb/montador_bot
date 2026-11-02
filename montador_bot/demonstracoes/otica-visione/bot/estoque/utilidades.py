"""Funções puras de formatação e limpeza de texto (sem estado, sem I/O)."""
import unicodedata

from .constantes import RE_NAO_ALFANUM


def normalizar(texto: str) -> str:
    """minúsculas, sem acento, sem pontuação, espaços únicos."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = RE_NAO_ALFANUM.sub(" ", texto.lower())
    return " ".join(texto.split())


def juntar(partes: list) -> str:
    """['a', 'b', 'c'] -> 'a, b e c'"""
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def juntar_ou(partes: list) -> str:
    """['verde', 'preto'] -> 'verde ou preto'"""
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " ou " + partes[-1]


def reais(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50'"""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def preco_exibido(p) -> str:
    """Preço para o cliente. Produto-base cujas variações têm preços diferentes vira
    'a partir de R$ 50,00' (o preço do produto-base é o menor entre os SKUs)."""
    if p.variacoes and len({v.preco for v in p.variacoes}) > 1:
        return "a partir de " + reais(p.preco)
    return reais(p.preco)


def rotulo_opcao(valor) -> str:
    """Como a opção de um atributo aparece para o cliente: siglas curtas (tamanhos) em maiúsculas.
    'g' -> 'G', 'xg' -> 'XG', 'verde' -> 'verde', '42' -> '42'."""
    v = str(valor).strip()
    return v.upper() if len(v) <= 2 else v


def nome_variacao(nome_base: str, atributos: dict) -> str:
    """('Blusa', {'cor': 'verde', 'tamanho': 'g'}) -> 'Blusa verde G'."""
    return " ".join([nome_base] + [rotulo_opcao(v) for v in atributos.values()])


# Nomes originais (com underscore), mantidos para compatibilidade.
_juntar = juntar
_reais = reais
