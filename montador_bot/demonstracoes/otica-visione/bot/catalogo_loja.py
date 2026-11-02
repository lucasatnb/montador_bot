"""catalogo_loja.py -- CRUD de produtos da loja do bot (usado pelo painel do dono, aba «Catálogo»).

    listar_produtos(pasta)                                     -> produtos ativos, com preço e SKUs
    criar_produto(pasta, nome, descricao, categoria, preco)    -> ID novo (A000, A001...)
    editar_produto(pasta, id, nome=, descricao=, categoria=, precos=)
    remover_produto(pasta, id)

Só biblioteca padrão. Grava nos DOIS bancos da loja, como o alterar_loja.py:
    produtos_especializados.db   o que o bot VENDE (produtos + skus: nome e preço)
    catalogo.db                  o que o bot MOSTRA (descrição e categoria; alimenta a lista de categorias e o site)

Regras:
  - Produto novo nasce com UMA SKU (sem variação, SKU = ID). Variações (cor, tamanho...) e fotos continuam no
    montador, onde o catálogo é cadastrado.
  - Remover NÃO apaga o histórico: no banco de estoque o produto e as SKUs ficam inativos (comandas antigas e o
    «cancelar» continuam funcionando) e o ID nunca é reaproveitado. No catalogo.db o produto sai de verdade.
  - Cada gravação é uma transação curta (BEGIN IMMEDIATE), a mesma trava do bot: pode usar com o bot ligado.
    O bot percebe a mudança sozinho (relê o banco quando o arquivo muda).
  - O SITE é uma página pronta: depois de adicionar, remover ou mudar preço, regere o site no montador.
"""
import json
import re
import sqlite3
from pathlib import Path

from alterar_loja import BANCO, CATALOGO, ErroLoja, _agora, _executar, _ler, numero, pasta_loja  # noqa: F401

RE_ID = re.compile(r"^[A-Z][0-9]{3}$")

_TABELAS_CATALOGO = (
    """CREATE TABLE IF NOT EXISTS produtos (
           id TEXT PRIMARY KEY, nome TEXT NOT NULL, preco REAL, descricao TEXT, categoria TEXT,
           aprovado INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS imagens (
           id_produto TEXT NOT NULL REFERENCES produtos(id), ordem INTEGER NOT NULL, caminho TEXT NOT NULL,
           PRIMARY KEY (id_produto, ordem))""",
    """CREATE TABLE IF NOT EXISTS imagens_variacao (
           id_produto TEXT NOT NULL REFERENCES produtos(id), tipo TEXT NOT NULL, opcao TEXT NOT NULL,
           ordem INTEGER NOT NULL, caminho TEXT NOT NULL, PRIMARY KEY (id_produto, tipo, opcao, ordem))""",
    """CREATE TABLE IF NOT EXISTS acrescimos_variacao (
           id_produto TEXT NOT NULL REFERENCES produtos(id), tipo TEXT NOT NULL, opcao TEXT NOT NULL,
           acrescimo REAL NOT NULL, PRIMARY KEY (id_produto, tipo, opcao))""",
)


# ------------------------------------------------------------------ utilidades
def _limpar(texto) -> str:
    return " ".join(str(texto or "").split())


def _texto(valor, campo: str) -> str:
    """Nome e categoria numa linha só; descrição pode ter quebras de linha."""
    v = str(valor or "").strip() if campo == "descrição" else _limpar(valor)
    if not v:
        raise ErroLoja(f"A {campo} não pode ficar vazia." if campo != "nome" else "O nome não pode ficar vazio.")
    return v


def _garantir_catalogo(pasta: Path) -> None:
    """Cria o catalogo.db (e as tabelas) se a loja não tiver: sem ele não há descrição nem categoria para mostrar."""
    con = sqlite3.connect(str(pasta / CATALOGO), timeout=10, isolation_level=None)
    try:
        for ddl in _TABELAS_CATALOGO:
            con.execute(ddl)
    except sqlite3.Error as e:
        raise ErroLoja(f"Não consegui abrir o catalogo.db ({e}).") from e
    finally:
        con.close()


def _ids_usados(pasta: Path) -> set:
    """Todos os IDs que já existiram (inclusive de produtos removidos): um ID nunca é reaproveitado."""
    usados = {r[0] for r in _ler(pasta / BANCO, "SELECT id FROM produtos")}
    if (pasta / CATALOGO).is_file():
        try:
            usados |= {r[0] for r in _ler(pasta / CATALOGO, "SELECT id FROM produtos")}
        except ErroLoja:
            pass
    return {str(i).strip().upper() for i in usados}


def proximo_id(pasta: Path) -> str:
    usados = _ids_usados(pasta)
    for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for n in range(1000):
            candidato = f"{letra}{n:03d}"
            if candidato not in usados:
                return candidato
    raise ErroLoja("Todos os IDs de A000 a Z999 já foram usados.")


def _dados_catalogo(pasta: Path) -> dict:
    """{id: (descrição, categoria)} do catalogo.db ({} se ele não existe)."""
    if not (pasta / CATALOGO).is_file():
        return {}
    try:
        linhas = _ler(pasta / CATALOGO, "SELECT id, descricao, categoria FROM produtos")
    except ErroLoja:
        return {}
    return {i: (d or "", c or "") for i, d, c in linhas}


def _nome_repetido(pasta: Path, nome: str, categoria: str, ignorar_id: str = "") -> bool:
    """Já existe OUTRO produto ativo com o mesmo nome na mesma categoria? (o bot não saberia qual é qual)"""
    dados = _dados_catalogo(pasta)
    for pid, n in _ler(pasta / BANCO, "SELECT id, nome FROM produtos WHERE ativo = 1"):
        if pid != ignorar_id and _limpar(n).casefold() == nome.casefold() \
                and _limpar(dados.get(pid, ("", ""))[1]).casefold() == categoria.casefold():
            return True
    return False


# ------------------------------------------------------------------ leitura
def listar_produtos(pasta: Path) -> list:
    """[{id, nome, descricao, categoria, preco (o menor entre as SKUs), skus: [{sku, variacao, preco}]}]
    Só produtos ativos com ao menos uma SKU ativa, na ordem do cadastro."""
    produtos = _ler(pasta / BANCO, "SELECT id, nome FROM produtos WHERE ativo = 1 ORDER BY rowid")
    skus = _ler(pasta / BANCO, "SELECT produto_id, sku, atributos, preco FROM skus WHERE ativo = 1 ORDER BY rowid")
    por_produto: dict = {}
    for pid, sku, atrib, preco in skus:
        try:
            valores = [str(v) for v in json.loads(atrib or "{}").values()]
        except (ValueError, AttributeError):
            valores = []
        por_produto.setdefault(pid, []).append({"sku": sku, "variacao": " ".join(valores), "preco": float(preco)})
    dados = _dados_catalogo(pasta)
    saida = []
    for pid, nome in produtos:
        if pid not in por_produto:
            continue
        desc, cat = dados.get(pid, ("", ""))
        saida.append({"id": pid, "nome": nome, "descricao": desc, "categoria": cat,
                      "preco": min(s["preco"] for s in por_produto[pid]), "skus": por_produto[pid]})
    return saida


def categorias(pasta: Path) -> list:
    """Categorias já usadas na loja (para escolher na lista em vez de digitar de novo)."""
    return sorted({c for _, c in _dados_catalogo(pasta).values() if c}, key=str.casefold)


# ------------------------------------------------------------------ criar
def criar_produto(pasta: Path, nome, descricao, categoria, preco, ilimitado: bool = True, quantidade: int = 0) -> str:
    """Cadastra um produto novo (uma SKU, sem variação) e devolve o ID. `ilimitado=False` usa `quantidade`."""
    nome, descricao, categoria = _texto(nome, "nome"), _texto(descricao, "descrição"), _texto(categoria, "categoria")
    valor = numero(preco)
    qtd = 0 if ilimitado else int(quantidade or 0)
    if qtd < 0:
        raise ErroLoja("A quantidade não pode ser negativa.")
    if _nome_repetido(pasta, nome, categoria):
        raise ErroLoja(f"Já existe «{nome}» na categoria «{categoria}». Use outro nome ou edite o que já existe.")
    pid = proximo_id(pasta)
    agora = _agora()
    _garantir_catalogo(pasta)
    _executar(pasta / BANCO, [
        ("INSERT INTO produtos(id, nome, ativo, atualizado_em) VALUES (?, ?, 1, ?)", (pid, nome, agora)),
        ("INSERT INTO skus(sku, produto_id, atributos, preco, quantidade, ilimitado, ativo, atualizado_em) "
         "VALUES (?, ?, '{}', ?, ?, ?, 1, ?)", (pid, pid, valor, qtd, int(bool(ilimitado)), agora))])
    try:
        _executar(pasta / CATALOGO, [(
            "INSERT INTO produtos(id, nome, preco, descricao, categoria, aprovado) VALUES (?, ?, ?, ?, ?, 1)",
            (pid, nome, valor, descricao, categoria))])
    except ErroLoja:   # não deixa um produto sem descrição/categoria à venda: desfaz o primeiro passo
        _executar(pasta / BANCO, [("DELETE FROM skus WHERE produto_id = ?", (pid,)),
                                  ("DELETE FROM produtos WHERE id = ?", (pid,))])
        raise
    return pid


# ------------------------------------------------------------------ editar
def editar_produto(pasta: Path, id_produto: str, nome=None, descricao=None, categoria=None, precos=None) -> None:
    """Muda o que for informado (None = não mexe). `precos` = {sku: preço}: um por SKU do produto."""
    pid = str(id_produto or "").strip().upper()
    atual = next((p for p in listar_produtos(pasta) if p["id"] == pid), None)
    if atual is None:
        raise ErroLoja(f"Não achei o produto '{pid}'.")
    novo_nome = _texto(nome if nome is not None else atual["nome"], "nome")
    nova_desc = _texto(descricao if descricao is not None else atual["descricao"], "descrição")
    nova_cat = _texto(categoria if categoria is not None else atual["categoria"], "categoria")
    skus_do_produto = {s["sku"] for s in atual["skus"]}
    novos_precos = {}
    for sku, valor in (precos or {}).items():
        sku = str(sku).strip().upper()
        if sku not in skus_do_produto:
            raise ErroLoja(f"O item '{sku}' não é do produto {pid}.")
        novos_precos[sku] = numero(valor)
    if _nome_repetido(pasta, novo_nome, nova_cat, ignorar_id=pid):
        raise ErroLoja(f"Já existe «{novo_nome}» na categoria «{nova_cat}». Use outro nome.")
    agora = _agora()
    _executar(pasta / BANCO,
              [("UPDATE produtos SET nome = ?, atualizado_em = ? WHERE id = ?", (novo_nome, agora, pid))]
              + [("UPDATE skus SET preco = ?, atualizado_em = ? WHERE sku = ?", (v, agora, s))
                 for s, v in novos_precos.items()])
    preco_base = min({**{s["sku"]: s["preco"] for s in atual["skus"]}, **novos_precos}.values())
    _garantir_catalogo(pasta)
    _executar(pasta / CATALOGO, [
        ("INSERT INTO produtos(id, nome, preco, descricao, categoria, aprovado) VALUES (?, ?, ?, ?, ?, 1) "
         "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, preco = excluded.preco, "
         "descricao = excluded.descricao, categoria = excluded.categoria, aprovado = 1",
         (pid, novo_nome, preco_base, nova_desc, nova_cat))])


# ------------------------------------------------------------------ remover
def remover_produto(pasta: Path, id_produto: str) -> str:
    """Tira o produto da venda. Devolve o nome dele. Estoque: fica inativo (histórico preservado); catálogo: sai."""
    pid = str(id_produto or "").strip().upper()
    atual = next((p for p in listar_produtos(pasta) if p["id"] == pid), None)
    if atual is None:
        raise ErroLoja(f"Não achei o produto '{pid}'.")
    agora = _agora()
    _executar(pasta / BANCO, [
        ("UPDATE skus SET ativo = 0, atualizado_em = ? WHERE produto_id = ?", (agora, pid)),
        ("UPDATE produtos SET ativo = 0, atualizado_em = ? WHERE id = ?", (agora, pid))])
    if (pasta / CATALOGO).is_file():
        existentes = {r[0] for r in _ler(pasta / CATALOGO, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        _executar(pasta / CATALOGO, [(f"DELETE FROM {t} WHERE {c} = ?", (pid,)) for t, c in (
            ("acrescimos_variacao", "id_produto"), ("imagens_variacao", "id_produto"),
            ("imagens", "id_produto"), ("produtos", "id")) if t in existentes])
    return atual["nome"]
