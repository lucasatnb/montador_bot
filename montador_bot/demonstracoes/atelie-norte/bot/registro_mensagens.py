"""Registro das conversas e fila de envio: banco mensagens.db (SQLite), compartilhado entre o BOT e o PAINEL.

O bot e o painel (interface_loja.py) são programas separados; este arquivo é a ponte entre os dois:
  - o BOT grava aqui tudo o que o cliente escreve e tudo o que o bot responde (atendimento.py faz isso sozinho);
  - o PAINEL grava aqui as mensagens que o dono quer mandar ao cliente (sentido 'dono', status 'pendente');
  - o DESPACHANTE do bot (notificacoes.iniciar_despachante) lê as pendentes e envia pelo canal registrado
    (Telegram, WhatsApp...), marcando 'enviada' ou 'erro'.

Banco (mensagens.db, criado sozinho na primeira vez):
    mensagens(id, chave, nome, sentido, texto, quando, status, erro, enviada_em)
      sentido: 'cliente' (o cliente escreveu) | 'bot' (resposta automática) | 'dono' (escrita pelo painel)
      status : 'ok' (cliente/bot) | 'enviada' (aviso do bot ao cliente) | 'erro'
               e, só para 'dono': 'pendente' -> 'enviando' -> 'enviada' | 'erro'
    estado(chave, valor)   -> 'despachante' = último batimento do despachante (o painel mostra "bot online")
    pausas(chave, desde, ate) -> clientes cujo atendimento o dono assumiu: o bot fica calado até o dono liberar.
      `ate` vazio = pausa manual (vale até liberar); `ate` preenchido = pausa COM PRAZO (loja por orçamento:
      depois que a comanda fecha o bot fica calado até o atendente ligar ou até esse horário, o que vier primeiro)
  - "chave" é o id do cliente no canal: "tg:123" no Telegram, o wa_id no WhatsApp.
"""
import os
import sys
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

PASTA = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
CAMINHO_DB = os.environ.get("BOT_CAMINHO_MENSAGENS") or os.path.join(PASTA, "mensagens.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensagens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chave       TEXT NOT NULL,
    nome        TEXT NOT NULL DEFAULT '',
    sentido     TEXT NOT NULL,          -- cliente | bot | dono
    texto       TEXT NOT NULL,
    quando      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ok',
    erro        TEXT,
    enviada_em  TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_chave ON mensagens(chave, id);
CREATE INDEX IF NOT EXISTS idx_msg_fila ON mensagens(sentido, status);
CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pausas (chave TEXT PRIMARY KEY, desde TEXT NOT NULL, ate TEXT);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


_pronto: set = set()   # bancos cujo esquema já foi conferido NESTE processo (não repete a cada chamada)
_trava_esquema = threading.Lock()


def _conectar() -> sqlite3.Connection:
    # o esquema (e o modo WAL, que fica gravado no arquivo) só é conferido na 1ª vez, ou se o arquivo sumiu
    precisa = CAMINHO_DB not in _pronto or not os.path.exists(CAMINHO_DB)
    con = sqlite3.connect(CAMINHO_DB, timeout=10)
    con.execute("PRAGMA synchronous = NORMAL")   # com WAL é seguro e grava bem mais rápido
    if precisa:
        with _trava_esquema:
            con.execute("PRAGMA journal_mode = WAL")   # bot e painel escrevem ao mesmo tempo sem se travar
            con.executescript(ESQUEMA)                 # só cria o que ainda não existe
            if "ate" not in {r[1] for r in con.execute("PRAGMA table_info(pausas)")}:   # banco anterior ao prazo da pausa
                con.execute("ALTER TABLE pausas ADD COLUMN ate TEXT")
                con.commit()
            _pronto.add(CAMINHO_DB)
    return con


def existe() -> bool:
    return os.path.exists(CAMINHO_DB)


# ------------------------------------------------------------------ gravar
def registrar(chave: str, nome: str, sentido: str, texto: str, status: str = "ok") -> int:
    """Guarda uma mensagem no histórico. Devolve o id dela."""
    con = _conectar()
    try:
        with con:
            return con.execute("INSERT INTO mensagens (chave, nome, sentido, texto, quando, status) "
                               "VALUES (?, ?, ?, ?, ?, ?)", (chave, nome or "", sentido, texto, _agora(), status)).lastrowid
    finally:
        con.close()


def registrar_varias(chave: str, nome: str, itens: list, status: str = "ok") -> None:
    """Guarda várias mensagens do mesmo cliente numa conexão e numa transação só.
    itens = [(sentido, texto), ...] na ordem em que aconteceram (ex.: [("cliente", "oi"), ("bot", "Olá!")])."""
    if not itens:
        return
    agora = _agora()
    con = _conectar()
    try:
        with con:
            con.executemany("INSERT INTO mensagens (chave, nome, sentido, texto, quando, status) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            [(chave, nome or "", sentido, texto, agora, status) for sentido, texto in itens])
    finally:
        con.close()


def enfileirar(chave: str, texto: str, nome: str = "") -> int:
    """O dono quer mandar `texto` ao cliente `chave`: entra na fila (status 'pendente')."""
    return registrar(chave, nome, "dono", texto, "pendente")


# ------------------------------------------------------------------ fila de envio (usada pelo despachante)
def reservar_pendentes(limite: int = 20) -> list:
    """Pega as mensagens do dono ainda não enviadas, na ordem, e as marca 'enviando' (atômico: dois despachantes
    nunca pegam a mesma). Devolve [(id, chave, texto)]."""
    con = _conectar()
    try:
        ids = [r[0] for r in con.execute("SELECT id FROM mensagens WHERE sentido = 'dono' AND status = 'pendente' "
                                         "ORDER BY id LIMIT ?", (limite,))]
        pegas = []
        for i in ids:
            with con:
                cur = con.execute("UPDATE mensagens SET status = 'enviando' WHERE id = ? AND status = 'pendente'", (i,))
            if cur.rowcount == 1:
                pegas.append(con.execute("SELECT id, chave, texto FROM mensagens WHERE id = ?", (i,)).fetchone())
        return pegas
    finally:
        con.close()


def concluir(id_: int, ok: bool, erro: str = "") -> None:
    con = _conectar()
    try:
        with con:
            con.execute("UPDATE mensagens SET status = ?, erro = ?, enviada_em = ? WHERE id = ?",
                        ("enviada" if ok else "erro", None if ok else (erro or "erro desconhecido"),
                         _agora() if ok else None, id_))
    finally:
        con.close()


def reenfileirar(id_: int) -> bool:
    """Põe de novo na fila uma mensagem que deu erro."""
    con = _conectar()
    try:
        with con:
            return con.execute("UPDATE mensagens SET status = 'pendente', erro = NULL WHERE id = ? "
                               "AND sentido = 'dono' AND status = 'erro'", (id_,)).rowcount == 1
    finally:
        con.close()


def marcar_interrompidos() -> int:
    """Ao ligar o bot: o que ficou 'enviando' quando ele caiu NÃO é reenviado sozinho (pode já ter saído);
    vira 'erro' para o dono conferir e, se quiser, tentar de novo pelo painel."""
    con = _conectar()
    try:
        with con:
            return con.execute("UPDATE mensagens SET status = 'erro', erro = 'interrompida: confira se o cliente recebeu "
                               "antes de tentar de novo' WHERE sentido = 'dono' AND status = 'enviando'").rowcount
    finally:
        con.close()


# ------------------------------------------------------------------ pausa do bot por cliente
def pausar(chave: str, minutos: Optional[int] = None) -> None:
    """O bot não responde a este cliente.
    minutos=None (padrão): o atendente assumiu; vale até liberar().
    minutos=N: pausa COM PRAZO (loja por orçamento); o bot volta sozinho depois de N minutos se ninguém ligar antes.
    Uma pausa manual já existente nunca é encurtada por uma com prazo; e o atendente assumir (sem prazo) por cima
    de uma com prazo a torna manual."""
    agora = datetime.now()
    ate = None if minutos is None else (agora + timedelta(minutes=int(minutos))).isoformat(timespec="seconds")
    con = _conectar()
    try:
        with con:
            if ate is None:
                con.execute("INSERT INTO pausas (chave, desde, ate) VALUES (?, ?, NULL) "
                            "ON CONFLICT(chave) DO UPDATE SET ate = NULL", (chave, _agora()))
            else:   # se já havia pausa manual (ate NULL), ela continua manual
                con.execute("INSERT INTO pausas (chave, desde, ate) VALUES (?, ?, ?) "
                            "ON CONFLICT(chave) DO UPDATE SET "
                            "desde = CASE WHEN pausas.ate IS NULL THEN pausas.desde ELSE excluded.desde END, "
                            "ate = CASE WHEN pausas.ate IS NULL THEN NULL ELSE excluded.ate END",
                            (chave, _agora(), ate))
    finally:
        con.close()


def liberar(chave: str) -> bool:
    """O atendente terminou (ou ligou o bot): o bot volta a responder a este cliente. True se havia pausa."""
    con = _conectar()
    try:
        with con:
            return con.execute("DELETE FROM pausas WHERE chave = ?", (chave,)).rowcount > 0
    finally:
        con.close()


def esta_pausado(chave: str) -> bool:
    """True enquanto a pausa vale. Pausa com prazo vencido é apagada aqui mesmo (o bot volta a atender)."""
    con = _conectar()
    try:
        r = con.execute("SELECT ate FROM pausas WHERE chave = ?", (chave,)).fetchone()
        if r is None:
            return False
        if r[0] is None or r[0] > _agora():   # ISO com o mesmo formato: comparar texto = comparar datas
            return True
        with con:
            con.execute("DELETE FROM pausas WHERE chave = ? AND ate IS NOT NULL AND ate <= ?", (chave, _agora()))
        return False
    finally:
        con.close()


def pausado_ate(chave: str) -> Optional[datetime]:
    """Quando a pausa com prazo termina; None se não há pausa ou se ela é manual (sem prazo)."""
    con = _conectar()
    try:
        r = con.execute("SELECT ate FROM pausas WHERE chave = ?", (chave,)).fetchone()
    finally:
        con.close()
    return datetime.fromisoformat(r[0]) if r and r[0] else None


def expirar_pausas() -> int:
    """Apaga as pausas com prazo vencido (limpeza; esta_pausado já ignora as vencidas). Devolve quantas."""
    con = _conectar()
    try:
        with con:
            return con.execute("DELETE FROM pausas WHERE ate IS NOT NULL AND ate <= ?", (_agora(),)).rowcount
    finally:
        con.close()


# ------------------------------------------------------------------ "bot online?"
def batimento() -> None:
    con = _conectar()
    try:
        with con:
            con.execute("INSERT INTO estado (chave, valor) VALUES ('despachante', ?) "
                        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (_agora(),))
    finally:
        con.close()


def ultimo_batimento() -> Optional[datetime]:
    if not existe():
        return None
    con = _conectar()
    try:
        r = con.execute("SELECT valor FROM estado WHERE chave = 'despachante'").fetchone()
    finally:
        con.close()
    return datetime.fromisoformat(r[0]) if r else None


# ------------------------------------------------------------------ ler (painel)
def conversas(limite: int = 200) -> list:
    """Uma linha por cliente, a conversa mais recente primeiro: chave, nome, ultima (quando), previa, total.
    Uma consulta só (antes eram 1 + uma por cliente)."""
    con = _conectar()
    try:
        linhas = con.execute(
            "SELECT m.chave, "
            "  (SELECT x.nome FROM mensagens x WHERE x.chave = m.chave AND x.nome <> '' ORDER BY x.id DESC LIMIT 1), "
            "  m.quando, m.texto, m.sentido, t.total "
            "FROM (SELECT chave, MAX(id) AS ultimo, COUNT(*) AS total FROM mensagens "
            "      GROUP BY chave ORDER BY ultimo DESC LIMIT ?) t "
            "JOIN mensagens m ON m.id = t.ultimo ORDER BY m.id DESC", (limite,)).fetchall()
    finally:
        con.close()
    return [{"chave": chave, "nome": nome or "", "ultima": q, "previa": t, "sentido": s_, "total": total}
            for chave, nome, q, t, s_, total in linhas]


def mensagens(chave: str, limite: int = 300) -> list:
    """As últimas `limite` mensagens do cliente, da mais antiga para a mais nova."""
    con = _conectar()
    try:
        linhas = con.execute("SELECT id, sentido, texto, quando, status, erro FROM mensagens WHERE chave = ? "
                             "ORDER BY id DESC LIMIT ?", (chave, limite)).fetchall()
    finally:
        con.close()
    return [{"id": i, "sentido": s, "texto": t, "quando": q, "status": st, "erro": e}
            for i, s, t, q, st, e in reversed(linhas)]
