"""Peças comuns aos canais de WhatsApp (whatsapp_oficial.py e whatsapp_nao_oficial.py). Só biblioteca padrão.

  - Despacho:     fila por cliente (as mensagens de um cliente são tratadas na ordem; clientes não se seguram)
  - Enderecos:    guarda em canais.db para onde responder cada cliente, o telefone/ids dele e as mensagens já vistas
  - Servidor:     mini servidor HTTP para os webhooks (sem Flask)
  - tratar_texto: a mesma regra do telegram_bot.py (pausa do atendente, anti-spam, só-texto, 'id') -> atendimento.atender
  - dividir_texto: quebra respostas longas (o WhatsApp limita o tamanho da mensagem)

Nada aqui conhece a Meta ou a Evolution: é só o que os dois canais têm em comum.
"""
import logging
import os
import sys
import queue
import re
import sqlite3
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    import bot_config
    CONFIG = bot_config.CONFIG
    RAIZ = bot_config.RAIZ
except ImportError:
    CONFIG, RAIZ = {}, (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)

TEXTO_SO_TEXTO = "Só consigo ler texto por enquanto. Pode escrever o que você quer?"


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def cfg(secao: str, chave: str, env: str = "", padrao=""):
    """Valor de bot_config.json > <secao> > <chave>; a variável de ambiente `env`, se existir, ganha."""
    if env and os.environ.get(env):
        return os.environ[env]
    valor = (CONFIG.get(secao) or {}).get(chave)
    return padrao if valor in (None, "") else valor


def dividir_texto(texto: str, limite: int = 3800) -> list:
    """Quebra em pedaços de até `limite` letras, preferindo cortar em fim de linha/frase."""
    texto = str(texto or "")
    if len(texto) <= limite:
        return [texto] if texto.strip() else []
    pedacos = []
    while len(texto) > limite:
        corte = max(texto.rfind("\n", 0, limite), texto.rfind(". ", 0, limite) + 1, texto.rfind(" ", 0, limite))
        if corte < limite // 2:
            corte = limite
        pedacos.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip("\n ")
    if texto.strip():
        pedacos.append(texto)
    return pedacos


class Despacho:
    """Pool de threads. Cada cliente (chave) cai SEMPRE na mesma fila, então as mensagens dele saem na ordem em que
    chegaram; o servidor HTTP só recebe e entrega (responde 200 logo, que é o que a Meta/Evolution esperam)."""

    def __init__(self, quantos: int = 8):
        self.filas = [queue.Queue(maxsize=500) for _ in range(max(1, quantos))]
        for i, fila in enumerate(self.filas):
            threading.Thread(target=self._trabalhar, args=(fila,), daemon=True, name=f"atendente-wa-{i}").start()

    @staticmethod
    def _trabalhar(fila) -> None:
        while True:
            tarefa = fila.get()
            if tarefa is None:
                return
            try:
                tarefa()
            except Exception:
                logging.exception("erro ao tratar a mensagem")

    def enviar(self, chave: str, tarefa) -> None:
        self.filas[zlib.crc32(chave.encode()) % len(self.filas)].put(tarefa)

    def parar(self) -> None:
        for fila in self.filas:
            fila.put(None)


class Enderecos:
    """canais.db: para onde responder cada cliente (sobrevive a reinício), identidades e mensagens já tratadas."""

    def __init__(self, caminho=None):
        self.caminho = str(caminho or os.environ.get("BOT_CANAIS_DB") or Path(RAIZ) / "canais.db")
        self._trava = threading.Lock()
        with self._con() as con:
            con.executescript(
                "CREATE TABLE IF NOT EXISTS enderecos (chave TEXT PRIMARY KEY, destino TEXT NOT NULL,"
                " telefone TEXT NOT NULL DEFAULT '', nome TEXT NOT NULL DEFAULT '', atualizado REAL NOT NULL);"
                "CREATE INDEX IF NOT EXISTS ix_end_tel ON enderecos(telefone);"
                "CREATE TABLE IF NOT EXISTS identidades (lid TEXT PRIMARY KEY, telefone TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS vistas (id TEXT PRIMARY KEY, quando REAL NOT NULL);")
            con.execute("DELETE FROM vistas WHERE quando < ?", (time.time() - 3 * 86400,))

    def _con(self):
        con = sqlite3.connect(self.caminho, timeout=15)
        con.execute("PRAGMA journal_mode=WAL")
        return _Fechando(con)

    def salvar(self, chave: str, destino: str, telefone: str = "", nome: str = "") -> None:
        with self._trava, self._con() as con:
            con.execute(
                "INSERT INTO enderecos (chave, destino, telefone, nome, atualizado) VALUES (?,?,?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET destino=excluded.destino, atualizado=excluded.atualizado,"
                " telefone=CASE WHEN excluded.telefone<>'' THEN excluded.telefone ELSE telefone END,"
                " nome=CASE WHEN excluded.nome<>'' THEN excluded.nome ELSE nome END",
                (chave, destino, telefone, nome, time.time()))

    def destino(self, chave: str):
        with self._con() as con:
            linha = con.execute("SELECT destino FROM enderecos WHERE chave = ?", (chave,)).fetchone()
        return linha[0] if linha else None

    def destino_por_telefone(self, telefone: str):
        with self._con() as con:
            linha = con.execute("SELECT destino FROM enderecos WHERE telefone = ? ORDER BY atualizado DESC LIMIT 1",
                                (telefone,)).fetchone()
        return linha[0] if linha else None

    def ligar_lid(self, lid: str, telefone: str) -> None:
        with self._trava, self._con() as con:
            con.execute("INSERT INTO identidades (lid, telefone) VALUES (?,?) "
                        "ON CONFLICT(lid) DO UPDATE SET telefone=excluded.telefone", (lid, telefone))

    def telefone_do_lid(self, lid: str) -> str:
        with self._con() as con:
            linha = con.execute("SELECT telefone FROM identidades WHERE lid = ?", (lid,)).fetchone()
        return linha[0] if linha else ""

    def ja_vista(self, id_mensagem: str) -> bool:
        """True se essa mensagem já foi tratada (a Meta/Evolution reenviam webhooks que demoram a ser respondidos)."""
        if not id_mensagem:
            return False
        with self._trava, self._con() as con:
            cur = con.execute("INSERT OR IGNORE INTO vistas (id, quando) VALUES (?, ?)", (id_mensagem, time.time()))
            return cur.rowcount == 0


class _Fechando:
    """Conexão sqlite que confirma (ou desfaz) E FECHA ao sair do `with` (o `with` puro do sqlite não fecha)."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, tipo, valor, tb):
        try:
            self.con.commit() if tipo is None else self.con.rollback()
        finally:
            self.con.close()
        return False


class Servidor:
    """Servidor HTTP dos webhooks. `tratador(metodo, caminho, query, cabecalhos, corpo)` -> (status, corpo, tipo)."""

    def __init__(self, host: str, porta: int, tratador, limite_corpo: int = 2_000_000):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _responder(self, metodo):
                try:
                    partes = urlsplit(self.path)
                    tamanho = int(self.headers.get("Content-Length") or 0)
                    if tamanho > outer.limite:
                        self.send_response(413)
                        self.end_headers()
                        return
                    corpo = self.rfile.read(tamanho) if tamanho else b""
                    query = {k: v[0] for k, v in parse_qs(partes.query).items()}
                    cab = {k.lower(): v for k, v in self.headers.items()}
                    status, resposta, tipo = outer.tratador(metodo, partes.path, query, cab, corpo)
                except Exception:
                    logging.exception("erro no webhook")
                    status, resposta, tipo = 500, "erro", "text/plain"
                dados = resposta if isinstance(resposta, bytes) else str(resposta).encode()
                self.send_response(status)
                self.send_header("Content-Type", f"{tipo}; charset=utf-8")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def do_GET(self):
                self._responder("GET")

            def do_POST(self):
                self._responder("POST")

            def log_message(self, formato, *args):   # o log do http.server é barulhento; o nosso já registra o que importa
                logging.debug("http: " + formato, *args)

        self.tratador, self.limite = tratador, limite_corpo
        self.httpd = ThreadingHTTPServer((host, int(porta)), Handler)
        self.httpd.daemon_threads = True
        self.porta = self.httpd.server_address[1]

    def iniciar(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="webhook-http").start()

    def parar(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def tratar_texto(nucleo, rm, *, chave: str, nome: str, texto: str, enviar, texto_id) -> None:
    """Regra única de atendimento por mensagem (igual à do telegram_bot.tratar).
    `nucleo` = atendimento.atendimento, `rm` = registro_mensagens, `enviar(texto)` responde a ESTE cliente,
    `texto_id()` monta a resposta do comando 'id'."""
    if chave not in nucleo.DONOS and rm.esta_pausado(chave):
        if texto:   # atendente no comando: guarda para aparecer no painel e não responde
            rm.registrar(chave, nome, "cliente", texto)
        logging.info("%s está pausado (atendente no comando): bot calado", chave)
        return
    if nucleo.esta_bloqueado(chave):
        logging.info("%s está em timeout (anti-spam): bot calado", chave)
        return
    if not texto:
        enviar(TEXTO_SO_TEXTO)
        return
    if texto.strip().lower() in ("id", "/id", "!id"):   # o vendedor descobre o próprio id para pôr nos donos
        enviar(texto_id())
        return
    r = nucleo.atender(chave, texto)
    logging.info("%s -> status %s", chave, r.status)
    if r.mensagem:
        enviar(r.mensagem)
