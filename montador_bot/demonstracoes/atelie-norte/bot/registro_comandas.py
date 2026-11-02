"""Registro das comandas fechadas: banco comandas.db (SQLite).

Uso (o atendimento.py já chama isso sozinho ao fechar a comanda):
    numero = salvar_comanda("tg:123", "Lucas", [(produto, qtd), ...], total)

Banco (comandas.db, SEPARADO do banco de estoque, criado sozinho na primeira vez):
    comandas(id, cliente_chave, cliente_nome, total, fechada_em, status, atualizada_em, tipo, endereco)
      status: 'aguardando' (itens reservados, esperando o vendedor) -> 'confirmada' ou 'cancelada'
      tipo: 'pedido' (normal: 'confirmada' = pagamento recebido) | 'orcamento' (loja por orçamento:
            'confirmada' = visita confirmada; guarda o endereço da visita em `endereco`)
    comanda_itens(comanda_id, produto_id, produto_nome, preco_unitario, quantidade, subtotal)
  - "chave" é o id do cliente no canal: "tg:123" no Telegram, o wa_id no WhatsApp.
  - produto_id é o código do SKU vendido (ex.: "A001_VE_G"): o cancelamento devolve o estoque por ele.
  - o nome e o preço de cada item são COPIADOS para a comanda: se o produto mudar de preço
    depois, a comanda antiga continua mostrando o que o cliente realmente pagou.
"""
import os
import sys
import sqlite3
import threading
from datetime import datetime

PASTA = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
# Para usar outro arquivo sem editar o código: variável de ambiente BOT_COMANDAS_DB (caminho completo do .db).
# O bot e o painel precisam enxergar a MESMA variável, senão cada um grava num banco diferente.
CAMINHO_DB = os.path.abspath(os.environ.get("BOT_COMANDAS_DB") or os.path.join(PASTA, "comandas.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS comandas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_chave TEXT NOT NULL,
    cliente_nome  TEXT NOT NULL,
    total         REAL NOT NULL,
    fechada_em    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'aguardando',   -- aguardando | confirmada | cancelada
    atualizada_em TEXT,
    tipo          TEXT NOT NULL DEFAULT 'pedido',       -- pedido | orcamento
    endereco      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS comanda_itens (
    comanda_id     INTEGER NOT NULL REFERENCES comandas(id) ON DELETE CASCADE,
    produto_id     TEXT    NOT NULL,
    produto_nome   TEXT    NOT NULL,
    preco_unitario REAL    NOT NULL,
    quantidade     INTEGER NOT NULL,
    subtotal       REAL    NOT NULL
);
-- carrinho ABERTO: itens já descontados do estoque, mas a comanda ainda não fechou.
-- Existe só para o estoque não ficar preso se o bot reiniciar (ao ligar, o que sobrou aqui é devolvido).
CREATE TABLE IF NOT EXISTS carrinhos (
    cliente_chave TEXT    NOT NULL,
    produto_id    TEXT    NOT NULL,
    quantidade    INTEGER NOT NULL,
    atualizado_em TEXT    NOT NULL,
    PRIMARY KEY (cliente_chave, produto_id)
);
CREATE INDEX IF NOT EXISTS idx_comandas_cliente ON comandas(cliente_chave);
CREATE INDEX IF NOT EXISTS idx_itens_comanda ON comanda_itens(comanda_id);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


_pronto: set = set()   # bancos cujo esquema já foi conferido NESTE processo (não repete a cada chamada)
_trava_esquema = threading.Lock()


def _conectar() -> sqlite3.Connection:
    # esquema, migração e modo WAL (que fica gravado no arquivo) só na 1ª vez, ou se o arquivo sumiu
    precisa = CAMINHO_DB not in _pronto or not os.path.exists(CAMINHO_DB)
    if precisa:
        os.makedirs(os.path.dirname(CAMINHO_DB), exist_ok=True)   # pasta escolhida pela variável pode ainda não existir
    con = sqlite3.connect(CAMINHO_DB, timeout=10)   # timeout=10: espera até 10 s se o painel estiver gravando (busy_timeout)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA synchronous = NORMAL")   # com WAL é seguro e grava bem mais rápido
    if precisa:
        with _trava_esquema:
            con.execute("PRAGMA journal_mode = WAL")   # bot e painel mexem no mesmo arquivo sem se travar
            con.executescript(ESQUEMA)   # só cria o que ainda não existe
            colunas = {r[1] for r in con.execute("PRAGMA table_info(comandas)")}
            if "status" not in colunas:   # banco criado antes do status existir: o que já estava lá conta como confirmado
                con.execute("ALTER TABLE comandas ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmada'")
                con.execute("ALTER TABLE comandas ADD COLUMN atualizada_em TEXT")
                con.commit()
            if "tipo" not in colunas:   # banco anterior ao modo orçamento: tudo o que já estava lá é pedido normal
                con.execute("ALTER TABLE comandas ADD COLUMN tipo TEXT NOT NULL DEFAULT 'pedido'")
                con.execute("ALTER TABLE comandas ADD COLUMN endereco TEXT NOT NULL DEFAULT ''")
                con.commit()
            _pronto.add(CAMINHO_DB)
    return con


# ------------------------------------------------------------------ comandas
def salvar_comanda(chave: str, nome: str, itens: list, total: float, endereco: str = "", tipo: str = "pedido") -> int:
    """Grava a comanda fechada no banco (tudo ou nada). Devolve o nº da comanda.
    Ela nasce com status 'aguardando' (itens reservados até o vendedor confirmar ou cancelar).
    itens = [(Produto, qtd), ...]. tipo='orcamento' + endereco = loja por orçamento (visita no endereço).
    Se o banco falhar, levanta exceção e NADA é gravado."""
    con = _conectar()
    try:
        with con:   # transação: confirma tudo no final ou desfaz tudo se algo falhar
            cur = con.execute("INSERT INTO comandas (cliente_chave, cliente_nome, total, fechada_em, status, tipo, endereco) "
                              "VALUES (?, ?, ?, ?, 'aguardando', ?, ?)",
                              (chave, nome, float(total), _agora(), tipo, endereco or ""))
            numero = cur.lastrowid
            con.executemany(
                "INSERT INTO comanda_itens (comanda_id, produto_id, produto_nome, preco_unitario, quantidade, subtotal) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(numero, p.id, p.nome, float(p.preco), int(q), float(p.preco) * int(q)) for p, q in itens])
            # o carrinho vira comanda NA MESMA transação: nunca sobra carrinho de comanda já gravada
            # (senão o estoque seria devolvido por engano ao religar o bot)
            con.execute("DELETE FROM carrinhos WHERE cliente_chave = ?", (chave,))
    finally:
        con.close()
    return numero


# ------------------------------------------------------------------ carrinho aberto (estoque reservado, comanda ainda não fechou)
def salvar_carrinho(chave: str, itens: list) -> None:
    """Substitui o carrinho aberto do cliente. itens = [(produto_id, quantidade), ...]"""
    con = _conectar()
    try:
        with con:
            con.execute("DELETE FROM carrinhos WHERE cliente_chave = ?", (chave,))
            con.executemany("INSERT INTO carrinhos (cliente_chave, produto_id, quantidade, atualizado_em) "
                            "VALUES (?, ?, ?, ?)", [(chave, pid, int(q), _agora()) for pid, q in itens])
    finally:
        con.close()


def apagar_carrinho(chave: str) -> None:
    con = _conectar()
    try:
        with con:
            con.execute("DELETE FROM carrinhos WHERE cliente_chave = ?", (chave,))
    finally:
        con.close()


def carrinhos_abertos() -> dict:
    """{chave: [(produto_id, quantidade), ...]} de todos os carrinhos que sobraram no banco."""
    con = _conectar()
    try:
        linhas = con.execute("SELECT cliente_chave, produto_id, quantidade FROM carrinhos "
                             "ORDER BY cliente_chave").fetchall()
    finally:
        con.close()
    saida: dict = {}
    for chave, pid, q in linhas:
        saida.setdefault(chave, []).append((pid, q))
    return saida


# ------------------------------------------------------------------ status (confirmar / cancelar)
def buscar_comanda(numero: int):
    """Dados da comanda (dict) ou None. itens = [(produto_id, produto_nome, quantidade), ...]"""
    con = _conectar()
    try:
        c = con.execute("SELECT id, cliente_chave, cliente_nome, total, status, fechada_em, tipo, endereco FROM comandas "
                        "WHERE id = ?", (numero,)).fetchone()
        if c is None:
            return None
        itens = con.execute("SELECT produto_id, produto_nome, quantidade FROM comanda_itens "
                            "WHERE comanda_id = ? ORDER BY rowid", (numero,)).fetchall()
    finally:
        con.close()
    return {"id": c[0], "chave": c[1], "nome": c[2], "total": c[3], "status": c[4], "quando": c[5],
            "tipo": c[6], "endereco": c[7], "itens": itens}


def comandas_com_status(status: str) -> list:
    con = _conectar()
    try:
        linhas = con.execute("SELECT id, cliente_nome, cliente_chave, total, fechada_em, tipo, endereco FROM comandas "
                             "WHERE status = ? ORDER BY id", (status,)).fetchall()
    finally:
        con.close()
    return [{"id": i, "nome": n, "chave": k, "total": t, "quando": q, "tipo": tp, "endereco": en}
            for i, n, k, t, q, tp, en in linhas]


def mudar_status(numero: int, de: str, para: str) -> bool:
    """Troca o status SÓ se a comanda ainda está em `de` (atômico: duas confirmações/cancelamentos
    ao mesmo tempo não passam os dois). Devolve True se foi esta chamada que mudou."""
    con = _conectar()
    try:
        with con:
            cur = con.execute("UPDATE comandas SET status = ?, atualizada_em = ? WHERE id = ? AND status = ?",
                              (para, _agora(), numero, de))
            mudou = cur.rowcount == 1
    finally:
        con.close()
    return mudou
