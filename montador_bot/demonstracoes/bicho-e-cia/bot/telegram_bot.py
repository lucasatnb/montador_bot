"""Canal Telegram do bot. Usa long polling: não precisa de servidor nem de túnel.

Como rodar (PowerShell, na pasta BOT):
    python -m pip install requests
    $env:TELEGRAM_TOKEN = "123456:ABC..."    # token que o @BotFather te dá
    $env:TELEGRAM_DONOS = "123456789"        # SEU chat id (vendedor): confirma/cancela comandas e recebe os avisos
                                             # (vários: "123456789,987654321"). Não sabe o seu? Rode sem, mande /id ao bot.
    $env:PIX_CHAVE = "sua-chave-pix"         # dados do PIX (ficam fora do código)
    $env:PIX_NOME = "Nome do recebedor"      # até 25 letras
    $env:PIX_CIDADE = "Fortaleza"            # até 15 letras
    $env:BOT_PASTA_ESTOQUE = "C:/.../pizza-pepi"   # opcional: pasta do estoque (senão usa a de configuracao.py)
    $env:BOT_TEMPO_CARRINHO_MIN = "30"       # opcional: minutos parado até o carrinho devolver o estoque
    $env:BOT_TRABALHADORES = "8"             # opcional: quantos clientes atender ao mesmo tempo
    python telegram_bot.py
(as variáveis valem só nesta janela do PowerShell; para guardar de vez use: setx PIX_CHAVE "...")

O que este arquivo liga ao atendimento:
  - registrar_enviador:   como mandar mensagem a um cliente (usado nos avisos de confirmar/cancelar e na fila do painel)
  - registrar_notificador: como avisar os vendedores (DONOS) quando uma comanda fecha
  - iniciar_despachante:  thread que envia as mensagens que o dono escreve no painel (interface_loja.py)
"""
import logging
import os
import queue
import sys
import threading
import time

import requests
from requests.adapters import HTTPAdapter

import registro_mensagens as rm   # pausa do bot por cliente (mensagens.db)

try:   # bot_config.json (gerado pelo montador); variáveis de ambiente continuam tendo prioridade
    import bot_config
    _CFG = bot_config.CONFIG
except ImportError:
    _CFG = {}

# O módulo do bot (atendimento/atendimento.py). Importar o módulo de dentro do pacote funciona com ou sem
# o __init__.py reexportar nomes; o atendimento.py reexporta registrar_enviador, iniciar_despachante etc.
from atendimento import atendimento as nucleo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class _FormatadorSemToken(logging.Formatter):
    """Erros do `requests` trazem a URL com o token do bot; isto troca o token por *** em qualquer linha de log."""
    token = ""

    def format(self, record):
        texto = super().format(record)
        return texto.replace(self.token, "***") if self.token else texto


def _esconder_token(token: str) -> None:
    _FormatadorSemToken.token = token
    for h in logging.getLogger().handlers:
        h.setFormatter(_FormatadorSemToken("%(asctime)s %(levelname)s %(message)s"))


def chave_cliente(chat_id) -> str:
    return f"tg:{chat_id}"   # no WhatsApp será o wa_id / user_id; o resto do bot não muda


class Telegram:
    def __init__(self, token: str):
        self.api = f"https://api.telegram.org/bot{token}"
        # UMA sessão para tudo: reaproveita a conexão HTTPS (antes cada chamada abria uma nova)
        self.http = requests.Session()
        self.http.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=32))

    def quem_sou_eu(self) -> str:
        """Confere o token e devolve o @usuario do bot (é nele que você tem que mandar mensagem)."""
        dados = self.http.get(f"{self.api}/getMe", timeout=15).json()
        if not dados.get("ok"):
            raise RuntimeError(dados.get("description", "token inválido"))
        return dados["result"]["username"]

    def enviar(self, chat_id, texto: str, levantar: bool = False) -> None:
        """Manda a mensagem. Se o Telegram recusar: levantar=False só registra no log (resposta ao cliente não
        derruba o bot); levantar=True lança erro (usado pelo despachante do painel, para marcar 'falhou')."""
        dados = self.http.post(f"{self.api}/sendMessage",
                              json={"chat_id": chat_id, "text": texto}, timeout=15).json()
        if not dados.get("ok"):
            motivo = dados.get("description", "sem detalhe")
            logging.error("Telegram não aceitou a mensagem para o chat %s: %s", chat_id, motivo)
            if levantar:
                raise RuntimeError(f"Telegram recusou: {motivo}")

    def novas_mensagens(self, offset):
        dados = self.http.get(f"{self.api}/getUpdates",
                             params={"timeout": 30, "offset": offset}, timeout=45).json()
        if not dados.get("ok"):
            raise RuntimeError(f"Telegram recusou: {dados.get('description')}")
        return dados["result"]


def tratar(tg: Telegram, update: dict) -> None:
    msg = update.get("message")
    if not msg:   # edição de mensagem, entrada em grupo etc.
        logging.info("evento ignorado (sem 'message'): %s", [k for k in update if k != "update_id"])
        return
    chat_id = msg["chat"]["id"]
    texto = msg.get("text")
    logging.info("chat %s escreveu: %r", chat_id, texto if texto else "(sem texto)")
    chave = chave_cliente(chat_id)
    if chave not in nucleo.DONOS and rm.esta_pausado(chave):
        # atendente no comando: guarda o que o cliente escreveu (para aparecer no painel) e não responde nada
        if texto:
            rm.registrar(chave, msg.get("from", {}).get("first_name", ""), "cliente", texto)
        logging.info("chat %s está pausado (atendente no comando): bot calado", chat_id)
        return
    if nucleo.esta_bloqueado(chave):   # timeout anti-spam: não responde nada (nem a foto, nem /start)
        logging.info("chat %s está em timeout (anti-spam): bot calado", chat_id)
        return
    if not texto:  # foto, áudio, figurinha...
        tg.enviar(chat_id, "Só consigo ler texto por enquanto. Pode escrever o que você quer?")
        return
    if texto.startswith("/id"):   # para o vendedor descobrir o próprio chat id e pôr em TELEGRAM_DONOS
        tg.enviar(chat_id, f"Seu chat id: {chat_id}\nPara ser vendedor, defina TELEGRAM_DONOS={chat_id} e reinicie o bot.")
        return
    if texto.startswith("/start"):
        # link do site: t.me/<bot>?start=<carrinho>. O Telegram só aceita A-Z a-z 0-9 _ - (até 64) no parâmetro,
        # então o site manda "-" no lugar da vírgula do código (SKU nunca tem "-").
        carga = texto.split(maxsplit=1)[1].strip().replace("-", ",") if len(texto.split(maxsplit=1)) > 1 else ""
        if carga and nucleo.estoque.parece_codigo(carga):
            texto = carga   # segue como se o cliente tivesse mandado o código do carrinho
        else:
            r = nucleo.iniciar(chave_cliente(chat_id))   # saudação do atendimento.py
            if r.mensagem:
                tg.enviar(chat_id, r.mensagem)
            return
    r = nucleo.atender(chave_cliente(chat_id), texto)
    logging.info("chat %s -> status %s", chat_id, r.status)
    if r.mensagem:   # vazio = cliente em timeout: não manda nada
        tg.enviar(chat_id, r.mensagem)


class Despacho:
    """Pool de threads que atende vários clientes ao mesmo tempo. Cada cliente cai SEMPRE na mesma fila
    (chat_id % nº de atendentes), então as mensagens dele continuam sendo tratadas na ordem em que chegaram,
    e um cliente lento não segura os outros (o laço do Telegram só recebe e distribui)."""

    def __init__(self, tg: Telegram, quantos: int):
        self.tg = tg
        self.filas = [queue.Queue(maxsize=500) for _ in range(quantos)]   # cheia = o laço espera (freio contra enxurrada)
        for i, fila in enumerate(self.filas):
            threading.Thread(target=self._trabalhar, args=(fila,), daemon=True, name=f"atendente-{i}").start()

    def _tratar(self, update: dict) -> None:
        try:
            tratar(self.tg, update)
        except Exception:
            logging.exception("erro ao tratar a mensagem")

    def _trabalhar(self, fila: "queue.Queue") -> None:
        while True:
            update = fila.get()
            if update is None:   # sinal de parada
                return
            self._tratar(update)

    def enviar(self, update: dict) -> None:
        msg = update.get("message")
        if not msg:   # evento sem mensagem: só vai para o log, não precisa de fila
            self._tratar(update)
            return
        self.filas[int(msg["chat"]["id"]) % len(self.filas)].put(update)

    def parar(self) -> None:
        for fila in self.filas:
            fila.put(None)


def _ler_trabalhadores() -> int:
    """BOT_TRABALHADORES = quantos clientes atender em paralelo (padrão 8)."""
    try:
        return max(1, int(os.environ.get("BOT_TRABALHADORES") or _CFG.get("trabalhadores") or 8))
    except ValueError:
        return 8


def _ler_donos() -> set:
    """TELEGRAM_DONOS = ids separados por vírgula ("123,456" ou "tg:123,tg:456") -> {"tg:123", "tg:456"}."""
    bruto = os.environ.get("TELEGRAM_DONOS") or ",".join(str(d) for d in (_CFG.get("telegram") or {}).get("donos", []))
    return {chave_cliente(p.strip().removeprefix("tg:")) for p in bruto.split(",") if p.strip()}


def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN") or (_CFG.get("telegram") or {}).get("token") or ""
    if not token:
        sys.exit("Falta o token do Telegram: preencha em bot_config.json (telegram > token) ou defina TELEGRAM_TOKEN.")
    _esconder_token(token)
    tg = Telegram(token)

    donos = _ler_donos()
    nucleo.DONOS.update(donos)   # o MESMO conjunto de configuracao.py
    if not donos:
        logging.warning("TELEGRAM_DONOS não definido: ninguém pode confirmar/cancelar comandas pelo chat e "
                        "ninguém recebe o aviso de nova comanda. Mande /id ao bot para descobrir seu chat id.")

    def avisar_cliente(chave: str, texto: str) -> None:   # levanta erro se falhar: o painel mostra "falhou"
        tg.enviar(chave.removeprefix("tg:"), texto, levantar=True)

    def avisar_donos(texto: str) -> None:
        for d in list(nucleo.DONOS):   # um vendedor com problema não impede o aviso aos outros
            try:
                tg.enviar(d.removeprefix("tg:"), texto, levantar=True)
            except Exception:
                logging.exception("não consegui avisar o vendedor %s", d)

    nucleo.registrar_enviador(avisar_cliente)
    nucleo.registrar_notificador(avisar_donos)
    try:
        usuario = tg.quem_sou_eu()
    except (RuntimeError, requests.RequestException) as e:
        sys.exit(f"Não consegui entrar com esse token: {e}")
    nucleo.iniciar_despachante()   # a partir daqui as mensagens escritas no painel saem pelo Telegram
    nucleo.iniciar_limpeza_carrinhos()   # devolve ao estoque o que sobrou de antes e os carrinhos parados
    logging.info("Conectado como @%s. Abra https://t.me/%s, mande /start e escreva um pedido. "
                 "Ctrl+C para parar.", usuario, usuario)
    despacho = Despacho(tg, _ler_trabalhadores())
    offset = None
    try:
        while True:
            try:
                for update in tg.novas_mensagens(offset):
                    offset = update["update_id"] + 1
                    despacho.enviar(update)
            except requests.RequestException:
                logging.warning("sem conexão com o Telegram, tentando de novo...")
                time.sleep(3)
            except RuntimeError as e:   # ex.: duas cópias do bot rodando ao mesmo tempo
                logging.error("%s", e)
                time.sleep(5)
    except KeyboardInterrupt:
        nucleo.parar_despachante()
        nucleo.parar_limpeza_carrinhos()
        despacho.parar()
        logging.info("Bot encerrado.")


if __name__ == "__main__":
    main()
