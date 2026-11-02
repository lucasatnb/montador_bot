"""Vitrine por categoria e por GRUPO (subcategoria): o bot lista os GRUPOS (depois do nome) e o cliente
escolhe um ("roupas masculinas"): o bot lista as subcategorias dele; o cliente escolhe uma ("calças"):
o bot mostra os itens dela.

Como funciona:
  - As categorias e as descrições vêm do catalogo.db (mesma pasta do banco de estoque); os grupos vêm do
    grupos_categorias.json ao lado dele; os preços, as variações (cor, tamanho...) e o estoque vêm do banco
    de estoque. Só aparecem itens com algum SKU em estoque.
  - O texto do cliente é comparado com as palavras dos NOMES dos grupos e das categorias (aceita plural e
    erro de digitação):
        "roupas masculinas"  -> grupo: lista as subcategorias
        "calças"             -> categoria: mostra os itens
        "uma roupa"          -> sem grupos: "roupa masculina" e "roupa feminina" empatam: mostra 4 de uma das duas
  - Mostra todos os itens em estoque da categoria, na ordem do catálogo (até MAX_ITENS; se houver mais, sorteia MAX_ITENS).
    Categoria toda esgotada = avisa. O cliente responde com o nome do que quer.
  - LOJA POR ORÇAMENTO: a lista nunca mostra preço.
  - NÃO entra quando: o texto fala de um produto específico ("quero uma blusa"), tem negação ("não quero roupa"),
    é um código do carrinho ou o estoque está no meio de uma pergunta (ex.: "qual cor?").
Funções sem estado de conversa: recebe o Estoque, devolve o texto da vitrine (ou None se não é pedido de categoria/grupo).

Também aqui: exemplo_de_pedido(), que monta um exemplo de pedido a partir do catálogo atual, para os textos do
bot (configuracao.py) não ficarem presos a um tipo de loja.
"""
import json
import logging
import os
import random
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import configuracao as cfg
from estoque.constantes import _NEGACAO
from estoque.modelos import BancoInvalido
from estoque.utilidades import juntar, normalizar, preco_exibido, rotulo_opcao

MAX_ITENS = 20   # itens mostrados por categoria (se houver mais, sorteia estes)
_norm_cat = lru_cache(maxsize=512)(normalizar)   # nomes de categoria se repetem a cada mensagem: normaliza uma vez
MAX_DESCRICAO = 110   # caracteres da descrição mostrados por item

# {id do produto: (categoria, descrição)} do catalogo.db, relido só quando o arquivo muda
_cache = {"caminho": None, "mtime": None, "dados": {}}

# {grupo: [categorias]} do grupos_categorias.json (ao lado do catalogo.db), relido só quando o arquivo muda
_cache_grupos = {"caminho": None, "mtime": None, "dados": {}}
GRUPOS_NOME = "grupos_categorias.json"


def _ler_catalogo(caminho: str) -> dict:
    try:
        mtime = os.path.getmtime(caminho)
    except OSError:
        return {}
    if _cache["caminho"] == caminho and _cache["mtime"] == mtime:
        return _cache["dados"]
    dados = {}
    try:
        con = sqlite3.connect(Path(caminho).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            for id_, cat, desc in con.execute("SELECT id, categoria, descricao FROM produtos"):
                dados[id_] = ((cat or "").strip(), " ".join((desc or "").split()))
        finally:
            con.close()
    except sqlite3.Error:
        logging.warning("vitrine: não consegui ler categorias/descrições em '%s'", caminho)
        return {}
    _cache.update(caminho=caminho, mtime=mtime, dados=dados)
    return dados


def _por_categoria(estoque) -> dict:
    """{categoria normalizada: (nome da categoria, [produtos-base])} (inclui os esgotados; quem usa filtra)"""
    dados = _ler_catalogo(estoque.repo.caminho_catalogo)
    saida: dict = {}
    for p in estoque.produtos:   # produtos-base com ao menos um SKU ativo
        cat = dados.get(p.id, ("", ""))[0]
        if cat:
            saida.setdefault(_norm_cat(cat), (cat, []))[1].append(p)
    return saida


def _opcoes_do_produto(estoque, p) -> str:
    """'cor: verde, preto · tamanho: M, G' a partir das variações do produto."""
    por_tipo: dict = {}
    for v in p.variacoes:
        for tipo, valor in v.atributos.items():
            if valor not in por_tipo.setdefault(tipo, []):
                por_tipo[tipo].append(valor)
    rotulos = estoque.texto._rotulos
    return " · ".join(f"{rotulos.get(t, t)}: {', '.join(rotulo_opcao(v) for v in vs)}" for t, vs in por_tipo.items())


def _exemplo_item(p, qtd: int) -> str:
    """'2 Pizza Calabresa M TR': nome do produto + as opções de uma variação em estoque (sem plural, para
    funcionar em qualquer tipo de loja)."""
    v = next((v for v in p.variacoes if v.ilimitado or v.quantidade > 0), None)
    if v is None:
        return f"{qtd} {p.nome}"
    return " ".join([str(qtd), v.nome_base or p.nome] + [rotulo_opcao(x) for x in v.atributos.values()])


def exemplo_de_pedido(estoque, itens: int = 1) -> str:
    """Exemplo de pedido tirado do catálogo ATUAL, para os textos do bot. itens=1: '2 Pizza Calabresa M TR';
    itens=2: '2 Pizza Calabresa M TR e 1 Coca-Cola 2L'. Se não houver produto em estoque, devolve um texto genérico."""
    try:
        estoque.repo.atualizar()
    except BancoInvalido:
        pass
    disponiveis = [p for p in estoque.produtos if p.ilimitado or p.quantidade > 0]
    if not disponiveis:
        return "a quantidade e o nome do produto"
    partes = [_exemplo_item(disponiveis[0], 2)]
    if itens >= 2 and len(disponiveis) > 1:
        partes.append(_exemplo_item(disponiveis[1], 1))
    return " e ".join(partes)


def _ler_grupos(estoque) -> dict:
    """{grupo: [categorias]} do grupos_categorias.json da loja ({} se não existe / é ilegível)."""
    caminho = Path(estoque.repo.caminho_catalogo).with_name(GRUPOS_NOME)
    try:
        mtime = os.path.getmtime(caminho)
    except OSError:
        return {}
    if _cache_grupos["caminho"] == str(caminho) and _cache_grupos["mtime"] == mtime:
        return _cache_grupos["dados"]
    dados = {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        bruto = {}
    if isinstance(bruto, dict):
        for grupo, categorias in bruto.items():
            g = " ".join(str(grupo).split())
            lista = [" ".join(str(c).split()) for c in categorias] if isinstance(categorias, list) else []
            lista = [c for c in lista if c]
            if g:
                dados[g] = lista
    _cache_grupos.update(caminho=str(caminho), mtime=mtime, dados=dados)
    return dados


def _grupos_por_categoria(estoque) -> dict:
    """{grupo: (nome, [(categoria, [produtos-base])])} — só categorias que existem no catálogo."""
    por_cat = _por_categoria(estoque)
    saida = {}
    for grupo, categorias in _ler_grupos(estoque).items():
        itens = []
        for c in categorias:
            chave = _norm_cat(c)
            if chave in por_cat:
                itens.append((por_cat[chave][0], por_cat[chave][1]))
        if itens:
            saida[grupo] = (grupo, itens)
    return saida


def grupos_disponiveis(estoque) -> list:
    """Nomes dos grupos que têm ao menos uma categoria com item em estoque."""
    try:
        estoque.repo.atualizar()
    except BancoInvalido:
        return []
    saida = []
    for nome, itens in _grupos_por_categoria(estoque).values():
        if any(p.ilimitado or p.quantidade > 0 for _, produtos in itens for p in produtos):
            saida.append(nome)
    return saida


def categorias_disponiveis(estoque) -> list:
    """Nomes das categorias que têm ao menos um item em estoque, na ordem em que aparecem no catálogo."""
    try:
        estoque.repo.atualizar()
    except BancoInvalido:
        return []
    saida = []
    for nome, produtos in _por_categoria(estoque).values():
        if any(p.ilimitado or p.quantidade > 0 for p in produtos):
            saida.append(nome)
    return saida


def texto_categorias(estoque):
    """'Estas são as nossas categorias:' + grupos e categorias soltas. None se a loja não tem nada."""
    nomes = categorias_disponiveis(estoque)
    grupos = grupos_disponiveis(estoque)
    if not nomes and not grupos:
        return None
    em_grupo = set()
    for _, itens in _grupos_por_categoria(estoque).values():
        for nome, produtos in itens:
            if any(p.ilimitado or p.quantidade > 0 for p in produtos):
                em_grupo.add(nome)
    soltas = [c for c in nomes if c not in em_grupo]
    linhas = [cfg.TEXTO_CATEGORIAS_TOPO, ""]
    if grupos:
        linhas.append(cfg.TEXTO_CATEGORIAS_GRUPOS)
        linhas += [f"• {g}" for g in grupos]
    if soltas:
        if grupos:
            linhas += ["", cfg.TEXTO_CATEGORIAS_OUTRAS]
        linhas += [f"• {c}" for c in soltas]
    linhas += ["", cfg.TEXTO_CATEGORIAS_RODAPE]
    return "\n".join(linhas)


def _texto_itens(estoque, nomes_categorias, pool):
    """Bloco final da vitrine: até MAX_ITENS itens (com descrição, opções e exemplo)."""
    dados = _ler_catalogo(estoque.repo.caminho_catalogo)
    sorteados = pool if len(pool) <= MAX_ITENS else random.sample(pool, MAX_ITENS)
    linhas = []
    for p in sorteados:
        linha = f"• {p.nome}" if estoque.orcamento else f"• {p.nome} — {preco_exibido(p)}"   # orçamento: sem preço
        descricao = dados.get(p.id, ("", ""))[1]
        if descricao:
            linha += "\n   " + (descricao if len(descricao) <= MAX_DESCRICAO else descricao[:MAX_DESCRICAO - 1].rstrip() + "…")
        opcoes = _opcoes_do_produto(estoque, p)
        if opcoes:
            linha += f"\n   {opcoes}"
        linhas.append(linha)
    msg = cfg.TEXTO_VITRINE_TOPO.format(categoria=juntar(nomes_categorias)) + "\n\n" + "\n".join(linhas)
    if len(nomes_categorias) > 1:
        msg += "\n\n" + cfg.TEXTO_VITRINE_VARIAS.format(exemplo=nomes_categorias[0])
    return msg + "\n\n" + cfg.TEXTO_VITRINE_RODAPE.format(exemplo=exemplo_de_pedido(estoque))


def tentar(estoque, texto: str) -> Optional[str]:
    """Texto da vitrine se `texto` é um pedido de categoria ou de GRUPO; None se não é (o fluxo normal segue)."""
    n = normalizar(texto)
    if any(t in _NEGACAO for t in n.split()):   # "não quero roupa": nunca é pedido de vitrine
        return None
    try:
        estoque.repo.atualizar()
    except BancoInvalido:
        return None
    tx = estoque.texto
    _, consulta = tx._extrair_qtd(texto)
    palavras_cliente = tx._significativas(normalizar(consulta))
    if not palavras_cliente:
        return None
    categorias = _por_categoria(estoque)   # só monta o mapa se a mensagem tem alguma palavra significativa
    grupos_por = _grupos_por_categoria(estoque)
    if not categorias and not grupos_por:
        return None

    def pontos_de(alvos):
        # quantas palavras do cliente cada nome "explica"; vale o(s) que explicar(em) mais
        return {chave: sum(1 for t in palavras_cliente if any(tx._bate(t, w) for w in _norm_cat(chave).split()))
                for chave in alvos}

    pontos = pontos_de(categorias)
    melhor_folha = max(pontos.values()) if pontos else 0
    pontos_grupo = pontos_de(grupos_por)
    melhor_grupo = max(pontos_grupo.values()) if pontos_grupo else 0
    if melhor_folha == 0 and melhor_grupo == 0:
        return None
    achados = tx.buscar(consulta, n=1)
    if achados and achados[0][1] >= tx.limite_direto:   # fala de um produto específico: o estoque cuida
        return None

    if melhor_folha >= melhor_grupo and melhor_folha > 0:   # empate: a categoria (mais específica) ganha
        escolhidas = [categorias[c] for c, pt in pontos.items() if pt == melhor_folha]
        nomes_categorias = [nome for nome, _ in escolhidas]
        pool = [p for _, produtos in escolhidas for p in produtos if p.ilimitado or p.quantidade > 0]   # esgotado não aparece
        if not pool:
            return cfg.TEXTO_VITRINE_VAZIA.format(categoria=juntar(nomes_categorias))
        return _texto_itens(estoque, nomes_categorias, pool)

    # grupo: mostra as subcategorias (ou os itens direto, se o grupo tiver uma categoria só)
    escolhidos = [grupos_por[g] for g, pt in pontos_grupo.items() if pt == melhor_grupo]
    nomes_grupos = [nome for nome, _ in escolhidos]
    subcats = []
    for nome, itens in escolhidos:
        for cat_nome, produtos in itens:
            disp = [p for p in produtos if p.ilimitado or p.quantidade > 0]
            if disp:
                subcats.append((nome if len(escolhidos) > 1 else None, cat_nome, disp))
    if not subcats:
        return cfg.TEXTO_VITRINE_VAZIA.format(categoria=juntar(nomes_grupos))
    if len(subcats) == 1:
        return _texto_itens(estoque, [subcats[0][1]], subcats[0][2])
    linhas = [f"• " + (f"{pref} › " if pref else "") + cat for pref, cat, _ in subcats]
    return (cfg.TEXTO_SUBCATEGORIAS_TOPO.format(grupo=juntar(nomes_grupos)) + "\n\n"
            + "\n".join(linhas) + "\n\n" + cfg.TEXTO_SUBCATEGORIAS_RODAPE)
