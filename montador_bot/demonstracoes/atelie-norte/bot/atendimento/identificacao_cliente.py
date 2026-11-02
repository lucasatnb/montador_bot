"""Intenções do cliente que NÃO são pedido de produto: nome e cumprimento.

Funções puras (sem estado e sem tocar no estoque): o que precisa do catálogo recebe a lista
de produtos como argumento. Vocabulário em configuracao.py; normalização vem de utilidades.py.
"""
import re

from rapidfuzz import fuzz

from .configuracao import _NAO_E_NOME, _PARTICULAS, _PREFIXOS_NOME, _SAUDACOES
from estoque.utilidades import normalizar

# compiladas uma vez, na importação
_RE_PONTUACAO = re.compile(r"[^\w\s'-]")
_RE_PALAVRA_NOME = re.compile(r"[^\W\d_]+(?:['-][^\W\d_]+)*")   # Jean-Luc, D'Ávila
_PREFIXOS_ORDENADOS = sorted(_PREFIXOS_NOME, key=len, reverse=True)   # o prefixo mais longo vence


def _extrair_nome(texto: str):
    """Tira o nome de frases como 'Lucas', 'meu nome é lucas aguiar', 'oi, sou a ana'.
    Devolve (nome ou None, tirou_prefixo). None = não parece um nome."""
    palavras = _RE_PONTUACAO.sub(" ", texto).split()
    tirou = False
    mudou = True
    while mudou and palavras:
        mudou = False
        norm = [normalizar(p) for p in palavras]
        for pre in _PREFIXOS_ORDENADOS:
            if len(palavras) > len(pre) and tuple(norm[:len(pre)]) == pre:
                palavras, tirou, mudou = palavras[len(pre):], True, True
                break
    if not palavras or len(palavras) > 4:
        return None, tirou
    if any(len(p) < 2 or not _RE_PALAVRA_NOME.fullmatch(p)
           for p in palavras if p.lower() not in _PARTICULAS):
        return None, tirou        # tem número, letra solta, símbolo...
    if normalizar(palavras[0]) in _NAO_E_NOME:
        return None, tirou        # "quero uma camiseta", "sim", "oi"...
    nome = " ".join(p.lower() if p.lower() in _PARTICULAS and i else p.title()   # Jean-Luc, D'Ávila
                    for i, p in enumerate(palavras))
    return (nome if len(nome) <= 40 else None), tirou


def _eh_saudacao(texto: str) -> bool:
    """True para mensagens que são SÓ um cumprimento ('oi', 'bom dia', 'e aí'). 'Bom dia, quero uma
    camiseta' não é: tem pedido junto."""
    t = normalizar(texto).split()
    return bool(t) and all(p in _SAUDACOES for p in t)


def _parece_produto(texto: str, produtos) -> bool:
    """A resposta é o nome de um produto ('camiseta preta')? Só vale para o nome QUASE INTEIRO ou para
    uma frase só com palavras dele. Pedaço de palavra não conta: 'Ivo' não é 'Tênis Esportivo' e
    'Jean' não é 'Calça Jeans' (são nomes de gente). `produtos` = lista de Produto do catálogo."""
    n = normalizar(texto)
    palavras = n.split()
    for p in produtos:
        nome_p = normalizar(p.nome)
        if fuzz.ratio(n, nome_p) >= 85:
            return True
        if len(palavras) >= 2 and set(palavras) <= set(nome_p.split()):
            return True
    return False
