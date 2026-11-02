"""Grava produto e estoque DIRETO nos bancos da loja, sem passar por planilhas.

    catalogo.db                    -> gerar_pastas.gravar_produto_catalogo (descrição, categoria, fotos, acréscimos)
    produtos_especializados.db     -> gravar_esp()      (modo especializado: produtos + skus + fotos das skus)
    produtos.db                    -> gravar_simples_db() (modo simples)

Regra do estoque (a mesma que o importador sempre teve): a QUANTIDADE só é gravada quando o item é NOVO.
Item que já existe mantém a quantidade do banco, porque o bot desconta a cada venda e quem ajusta o estoque
depois é o gerenciador de estoque (interface_estoque.py). Nome, preço, fotos e variações são atualizados.
SKU que saiu do produto fica inativa (nunca é apagada). Cada gravação é UMA transação BEGIN IMMEDIATE,
a mesma trava que o bot usa: se algo falha, o banco fica como estava.

Este módulo não usa Streamlit.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from variacoes import constantes_especializado as ce
from variacoes import criar_banco_especializado as banco
from nucleo.formato_ids import montar_sku, validar_id
from variacoes.planilha_especializada import PlanilhaInvalida, chave_atributos, estado_a_partir_do_salvo, validar

MODO_ESP = "especializado"

ESQUEMA_SIMPLES = """
CREATE TABLE IF NOT EXISTS produtos (
    id            TEXT PRIMARY KEY,
    nome          TEXT    NOT NULL,
    preco         REAL    NOT NULL,
    quantidade    INTEGER NOT NULL DEFAULT 0,
    ilimitado     INTEGER NOT NULL DEFAULT 0,   -- 1 = estoque infinito
    ativo         INTEGER NOT NULL DEFAULT 1,   -- 0 = saiu do catálogo
    atualizado_em TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS imagens (
    produto_id TEXT    NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    ordem      INTEGER NOT NULL,
    url        TEXT    NOT NULL,
    PRIMARY KEY (produto_id, ordem)
);
"""


def _imagens_comuns(listas):
    """Fotos presentes em TODAS as SKUs do produto (as gerais do item), na ordem da primeira SKU."""
    if not listas:
        return []
    primeira, outras = listas[0], listas[1:]
    return [u for u in dict.fromkeys(primeira) if all(u in o for o in outras)]

IMAGENS_SKU = ("CREATE TABLE IF NOT EXISTS imagens_sku ("
               "sku TEXT NOT NULL REFERENCES skus(sku), ordem INTEGER NOT NULL, url TEXT NOT NULL, "
               "PRIMARY KEY (sku, ordem))")


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _conectar(caminho):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho), timeout=10, isolation_level=None)   # transações manuais
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _criar_tabelas_esp(con):
    for instrucao in banco.SCHEMA.split(";"):        # sem executescript: ele fecha a transação aberta
        if instrucao.strip():
            con.execute(instrucao)
    con.execute(IMAGENS_SKU)


def _rollback(con):
    if con.in_transaction:
        con.execute("ROLLBACK")


def _consultar(caminho, sql, params=()):
    """Leitura somente-leitura. Devolve [] se o banco ou a tabela ainda não existem."""
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    con = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise
    finally:
        con.close()


# ------------------------------------------------------------------ leitura (para a tela abrir o produto)
def ler_estoque_simples_db(caminho_db, id_produto):
    """{preco, quantidade, ilimitado} do produto no produtos.db, ou None se ele ainda não está lá."""
    linhas = _consultar(caminho_db, "SELECT preco, quantidade, ilimitado FROM produtos WHERE id = ?",
                        (str(id_produto).strip(),))
    if not linhas:
        return None
    preco, qtd, ilim = linhas[0]
    return {"preco": float(preco), "quantidade": 0 if ilim else int(qtd), "ilimitado": bool(ilim)}


def carregar_produto_esp(caminho_db, id_produto):
    """Mesmo formato de planilha_especializada.carregar_produto, mas lido do banco (só SKUs ativas)."""
    pid = str(id_produto).strip().upper()
    linhas = _consultar(caminho_db, "SELECT sku, atributos, preco, quantidade, ilimitado FROM skus "
                                    "WHERE produto_id = ? AND ativo = 1 ORDER BY rowid", (pid,))
    if not linhas:
        return None
    tipos, valores = {}, {}
    for sku, texto, preco, qtd, ilim in linhas:
        try:
            attrs = json.loads(texto or "{}")
        except ValueError:
            attrs = {}
        if not isinstance(attrs, dict):
            attrs = {}
        for t, o in attrs.items():
            if o not in tipos.setdefault(t, []):
                tipos[t].append(o)
        valores[chave_atributos(attrs)] = {"sku": sku, "preco": float(preco),
                                           "quantidade": 0 if ilim else int(qtd), "ilimitado": bool(ilim)}
    ordem = {t: [o for o in ce.VARIANTES[t] if o in tipos[t]] for t in ce.VARIANTES if t in tipos}
    return {"tipos": ordem, "valores": valores}


def estado_inicial_esp(caminho_db, id_produto, preco_catalogo):
    return estado_a_partir_do_salvo(carregar_produto_esp(caminho_db, id_produto), preco_catalogo)


# ------------------------------------------------------------------ validação (antes de mexer em qualquer coisa)
def _linhas_de_validacao(pid, nome, linhas, existentes):
    """Linhas no formato da planilha especializada (para reaproveitar validar()) e o SKU de cada combinação."""
    rows = []
    for linha in linhas:
        attrs_in = linha.get("atributos") or {}
        attrs = {t: attrs_in[t] for t in ce.VARIANTES if t in attrs_in}
        sku = existentes.get(banco.atributos_json(attrs)) or montar_sku(pid, attrs, ce.VARIANTES, ce.CODIGOS)
        rows.append({"sku": sku, "id": pid, "nome": nome, "preco": linha.get("preco", 0),
                     "quantidade": "TRUE" if linha.get("ilimitado") else linha.get("quantidade", 0),
                     "imagem": linha.get("imagem", ""), **attrs})
    validar(rows)
    return rows


def validar_antes_de_gravar(caminho_db, id_produto, nome, linhas, modo):
    """Lista de erros (vazia = pode gravar). Não grava nada."""
    erros = []
    try:
        if not str(nome or "").strip():
            raise PlanilhaInvalida("o nome do produto não pode ficar vazio")
        if modo == MODO_ESP:
            pid = validar_id(id_produto)
            existentes = {a: s for s, a in _consultar(caminho_db, "SELECT sku, atributos FROM skus "
                                                                  "WHERE produto_id = ?", (pid,))}
            _linhas_de_validacao(pid, str(nome).strip(), linhas, existentes)
    except (PlanilhaInvalida, ValueError) as e:      # FormatoInvalido é um ValueError
        erros.append(str(e))
    except sqlite3.Error as e:
        erros.append(f"Não consegui ler o banco do estoque ({e}). Ele está aberto em outro programa?")
    return erros


# ------------------------------------------------------------------ gravação
def gravar_esp(caminho_db, id_produto, nome, linhas):
    """Grava o produto e suas SKUs no produtos_especializados.db.
    linhas: [{"atributos": {tipo: opção}, "preco", "quantidade", "ilimitado", "imagem": "caminho;caminho"}].
    Devolve {"novos": [skus], "atualizados": [skus], "desativados": [skus]}."""
    pid = validar_id(id_produto)
    nome = str(nome or "").strip()
    con = _conectar(caminho_db)
    try:
        _criar_tabelas_esp(con)
        con.execute("BEGIN IMMEDIATE")
        existentes = {a: s for s, a in con.execute("SELECT sku, atributos FROM skus WHERE produto_id = ?", (pid,))}
        rows = _linhas_de_validacao(pid, nome, linhas, existentes)
        itens = []
        for linha, row in zip(linhas, rows):
            ilim = bool(linha.get("ilimitado"))
            attrs = {t: row[t] for t in ce.VARIANTES if row.get(t)}
            itens.append({"sku": row["sku"], "atributos": banco.atributos_json(attrs),
                          "preco": float(linha.get("preco") or 0),
                          "qtd": 0 if ilim else int(float(linha.get("quantidade") or 0)), "ilim": int(ilim),
                          "imagens": [u for u in str(linha.get("imagem") or "").split(";") if u]})
        agora = _agora()
        con.execute("INSERT INTO produtos(id, nome, ativo, atualizado_em) VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, ativo = 1, "
                    "atualizado_em = excluded.atualizado_em", (pid, nome, agora))
        resumo = {"novos": [], "atualizados": [], "desativados": []}
        for it in itens:
            atual = con.execute("SELECT produto_id, atributos FROM skus WHERE sku = ?", (it["sku"],)).fetchone()
            if atual and (atual[0] != pid or atual[1] != it["atributos"]):
                raise PlanilhaInvalida(f"SKU '{it['sku']}' já existe no banco associada a outro produto/combinação")
            if atual is None:
                con.execute("INSERT INTO skus(sku, produto_id, atributos, preco, quantidade, ilimitado, ativo, "
                            "atualizado_em) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                            (it["sku"], pid, it["atributos"], it["preco"], it["qtd"], it["ilim"], agora))
                resumo["novos"].append(it["sku"])
            else:   # quantidade e ilimitado NÃO são mexidos: o estoque real é o do banco
                con.execute("UPDATE skus SET preco = ?, ativo = 1, atualizado_em = ? WHERE sku = ?",
                            (it["preco"], agora, it["sku"]))
                resumo["atualizados"].append(it["sku"])
        mantidas = {it["sku"] for it in itens}
        for (sku,) in con.execute("SELECT sku FROM skus WHERE produto_id = ? AND ativo = 1", (pid,)).fetchall():
            if sku not in mantidas:
                con.execute("UPDATE skus SET ativo = 0, atualizado_em = ? WHERE sku = ?", (agora, sku))
                resumo["desativados"].append(sku)
        # fotos: as gerais do produto (comuns a todas as SKUs) e as de cada SKU, como o importador faz
        comuns = _imagens_comuns([it["imagens"] for it in itens])
        if [r[0] for r in con.execute("SELECT url FROM imagens WHERE produto_id = ? ORDER BY ordem", (pid,))] != comuns:
            con.execute("DELETE FROM imagens WHERE produto_id = ?", (pid,))
            con.executemany("INSERT INTO imagens(produto_id, ordem, url) VALUES (?, ?, ?)",
                            [(pid, i, u) for i, u in enumerate(comuns, 1)])
        for it in itens:
            if [r[0] for r in con.execute("SELECT url FROM imagens_sku WHERE sku = ? ORDER BY ordem",
                                          (it["sku"],))] != it["imagens"]:
                con.execute("DELETE FROM imagens_sku WHERE sku = ?", (it["sku"],))
                con.executemany("INSERT INTO imagens_sku(sku, ordem, url) VALUES (?, ?, ?)",
                                [(it["sku"], i, u) for i, u in enumerate(it["imagens"], 1)])
        con.execute("COMMIT")
        return resumo
    except Exception:
        _rollback(con)
        raise
    finally:
        con.close()


def gravar_simples_db(caminho_db, id_produto, nome, preco, quantidade, ilimitado):
    """Grava o produto no produtos.db (modo simples). Quantidade só vale para produto NOVO. Devolve True se era novo."""
    pid = str(id_produto).strip()
    con = _conectar(caminho_db)
    try:
        con.executescript(ESQUEMA_SIMPLES)       # roda em autocommit, antes do BEGIN
        con.execute("BEGIN IMMEDIATE")
        existe = con.execute("SELECT 1 FROM produtos WHERE id = ?", (pid,)).fetchone() is not None
        agora = _agora()
        if existe:
            con.execute("UPDATE produtos SET nome = ?, preco = ?, ativo = 1, atualizado_em = ? WHERE id = ?",
                        (str(nome).strip(), float(preco), agora, pid))
        else:
            con.execute("INSERT INTO produtos(id, nome, preco, quantidade, ilimitado, ativo, atualizado_em) "
                        "VALUES (?, ?, ?, ?, ?, 1, ?)",
                        (pid, str(nome).strip(), float(preco), 0 if ilimitado else int(quantidade),
                         int(bool(ilimitado)), agora))
        con.execute("COMMIT")
        return not existe
    except Exception:
        _rollback(con)
        raise
    finally:
        con.close()
