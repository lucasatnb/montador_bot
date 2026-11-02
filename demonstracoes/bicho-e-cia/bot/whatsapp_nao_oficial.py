"""Canal WhatsApp NÃO OFICIAL (via Evolution API, que conecta um número comum lendo o QR code, como o WhatsApp Web).

ATENÇÃO: isso viola os termos do WhatsApp e o número pode ser banido de vez. Use um chip reserva, para teste.
Para a loja de verdade, use whatsapp_oficial.py.

Como ligar (o passo a passo completo está no LEIA-ME.txt do bot montado):
  1. Suba a Evolution API (v2) e crie uma instância; leia o QR code com o WhatsApp do chip de teste.
     (Confira a licença/ativação exigida pela versão que você usar.)
  2. Preencha em bot_config.json > whatsapp_nao_oficial: url_api (ex.: http://localhost:8080), apikey, instancia
     e token_webhook (qualquer texto; o montador já gera um). Variáveis de ambiente também valem:
     EVO_URL, EVO_APIKEY, EVO_INSTANCIA, EVO_WEBHOOK_TOKEN.
  3. No Evolution Manager, na instância > Webhook: URL  http://ENDERECO-DESTE-BOT:PORTA/webhook?token=SEU_TOKEN_WEBHOOK
     (mesma máquina: http://localhost:8001/webhook?token=...), ative e marque o evento MESSAGES_UPSERT.
  4. python whatsapp_nao_oficial.py

Identidade: o WhatsApp está trocando o número de telefone por um id "@lid". O bot responde sempre no MESMO endereço em
que a mensagem chegou (responder pelo telefone a uma conta @lid pode "enviar" e nunca chegar) e liga lid<->telefone
quando a Evolution informa os dois (remoteJidAlt). Vendedores (donos): liste o telefone (5585999999999).
Sem janela de 24h e sem templates: o aviso ao vendedor sai como texto normal.
"""
import hmac
import json
import logging
import sys
import time

import requests

import canal_comum as cc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SECAO = "whatsapp_nao_oficial"
ENVELOPES = ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "documentWithCaptionMessage")


class _EscondeSegredos(logging.Formatter):
    segredos = []

    def format(self, record):
        texto = super().format(record)
        for s in self.segredos:
            if s:
                texto = texto.replace(s, "***")
        return texto


def extrair_texto(mensagem: dict) -> str:
    m = mensagem or {}
    for _ in range(3):   # algumas mensagens vêm embrulhadas (temporárias, "ver uma vez")
        envelope = next((e for e in ENVELOPES if isinstance(m.get(e), dict)), None)
        if not envelope:
            break
        m = m[envelope].get("message") or {}
    return m.get("conversation") or (m.get("extendedTextMessage") or {}).get("text") or ""


class CanalNaoOficial:
    def __init__(self, nucleo, rm, config: dict = None, enderecos=None):
        c = config or {}
        pegar = lambda chave, env="", padrao="": c.get(chave) or cc.cfg(SECAO, chave, env, padrao)
        self.url = str(pegar("url_api", "EVO_URL", "http://localhost:8080")).rstrip("/")
        self.apikey = str(pegar("apikey", "EVO_APIKEY")).strip()
        self.instancia = str(pegar("instancia", "EVO_INSTANCIA")).strip()
        self.token_webhook = str(pegar("token_webhook", "EVO_WEBHOOK_TOKEN")).strip()
        self.host = str(pegar("host", "", "0.0.0.0"))
        self.porta = int(pegar("porta", "", 8001))
        self.donos_tel = [cc.so_digitos(d) for d in (c.get("donos") or cc.cfg(SECAO, "donos", "", []))
                          if cc.so_digitos(d)]
        faltando = [n for n, v in (("apikey", self.apikey), ("instancia", self.instancia),
                                   ("token_webhook", self.token_webhook)) if not v]
        if faltando:
            raise RuntimeError("Faltam em bot_config.json > whatsapp_nao_oficial: " + ", ".join(faltando))
        self.nucleo, self.rm = nucleo, rm
        self.enderecos = enderecos or cc.Enderecos()
        self.http = requests.Session()
        self.despacho = cc.Despacho(int(c.get("trabalhadores") or cc.CONFIG.get("trabalhadores") or 8))
        self.servidor = cc.Servidor(self.host, self.porta, self._http)
        self.nucleo.DONOS.update(f"wa:{t}" for t in self.donos_tel)
        _EscondeSegredos.segredos = [self.apikey, self.token_webhook]
        for h in logging.getLogger().handlers:
            h.setFormatter(_EscondeSegredos("%(asctime)s %(levelname)s %(message)s"))

    # ----------------------------------------------------------------- receber (webhook)
    def _http(self, metodo, caminho, query, cab, corpo):
        if caminho not in ("/webhook", "/webhook/") and not caminho.startswith("/webhook/"):
            return 200, "ok", "text/plain"
        if metodo != "POST":
            return 200, "ok", "text/plain"
        enviado = query.get("token") or cab.get("x-webhook-token", "")
        if not hmac.compare_digest(str(enviado), self.token_webhook):
            logging.warning("webhook recusado: token errado (confira o ?token= da URL cadastrada na Evolution)")
            return 403, "token inválido", "text/plain"
        try:
            payload = json.loads(corpo.decode("utf-8"))
        except ValueError:
            return 400, "json inválido", "text/plain"
        try:
            self.processar(payload)
        except Exception:
            logging.exception("erro ao processar o webhook")
        return 200, "ok", "text/plain"

    def processar(self, payload: dict) -> None:
        evento = str(payload.get("event", "")).lower().replace("_", ".")
        if evento != "messages.upsert":
            return
        if payload.get("instance") and payload["instance"] != self.instancia:
            return   # um servidor Evolution pode ter várias instâncias: só tratamos a nossa
        dados = payload.get("data")
        for d in (dados if isinstance(dados, list) else [dados]):
            if isinstance(d, dict):
                self._mensagem(d)

    def _mensagem(self, d: dict) -> None:
        key = d.get("key") or {}
        jid = str(key.get("remoteJid") or "")
        if key.get("fromMe") or not jid or jid.startswith("status@") or jid.endswith(("@g.us", "@broadcast", "@newsletter")):
            return   # mensagem nossa, grupo, status ou canal: o bot só atende conversa individual
        if self.enderecos.ja_vista(str(key.get("id") or "")):
            return
        alt = str(key.get("remoteJidAlt") or d.get("remoteJidAlt") or "")
        tel = cc.so_digitos(jid) if (jid.endswith("@s.whatsapp.net") or "@" not in jid) else (
            cc.so_digitos(alt) if alt.endswith("@s.whatsapp.net") else "")
        lid = cc.so_digitos(jid) if jid.endswith("@lid") else (cc.so_digitos(alt) if alt.endswith("@lid") else "")
        if lid and tel:
            self.enderecos.ligar_lid(lid, tel)
        elif lid:
            tel = self.enderecos.telefone_do_lid(lid)   # já vimos esse lid com o telefone antes?
        chave = "wa:" + (tel or lid)
        if chave == "wa:":
            logging.warning("mensagem sem identificação do remetente, ignorada")
            return
        nome = str(d.get("pushName") or "")
        self.enderecos.salvar(chave, jid, tel, nome)   # responde sempre no endereço em que chegou
        if tel in self.donos_tel:
            self.nucleo.DONOS.add(chave)
        texto = extrair_texto(d.get("message"))
        logging.info("%s escreveu: %r", chave, texto if texto else f"({d.get('messageType') or 'sem texto'})")

        def texto_id():
            return (f"Seu telefone: {tel or '(oculto pelo WhatsApp)'}\nSeu id: {lid or '-'}\n"
                    "Para ser vendedor, coloque o telefone em bot_config.json > whatsapp_nao_oficial > donos e reinicie o bot.")

        responder = lambda t: self._enviar_seguro(jid, t)
        self.despacho.enviar(chave, lambda: cc.tratar_texto(
            self.nucleo, self.rm, chave=chave, nome=nome, texto=texto, enviar=responder, texto_id=texto_id))

    # ----------------------------------------------------------------- enviar
    @staticmethod
    def _numero(destino: str) -> str:
        """Telefone puro para contas normais; o jid inteiro (...@lid) para contas @lid."""
        if "@" not in destino or destino.endswith("@s.whatsapp.net"):
            return cc.so_digitos(destino)
        return destino

    def enviar(self, destino: str, texto: str) -> None:
        for pedaco in cc.dividir_texto(texto, 3500):
            r = self.http.post(f"{self.url}/message/sendText/{self.instancia}", timeout=30,
                               headers={"apikey": self.apikey}, json={"number": self._numero(destino), "text": pedaco})
            if r.status_code >= 400:
                raise RuntimeError(f"Evolution recusou ({r.status_code}): {r.text[:200]}")

    def _enviar_seguro(self, destino: str, texto: str) -> None:
        try:
            self.enviar(destino, texto)
        except (RuntimeError, requests.RequestException) as e:
            logging.error("não consegui responder a %s: %s", destino, e)

    def avisar_cliente(self, chave: str, texto: str) -> None:   # painel e avisos de confirmar/cancelar; erro = "falhou"
        destino = self.enderecos.destino(chave) or chave.removeprefix("wa:")
        self.enviar(destino, texto)

    def avisar_donos(self, texto: str) -> None:
        for tel in self.donos_tel:
            try:
                self.enviar(self.enderecos.destino_por_telefone(tel) or tel, texto)
            except Exception as e:
                logging.error("não consegui avisar o vendedor %s: %s", tel, e)

    # ----------------------------------------------------------------- ciclo de vida
    def estado_da_instancia(self) -> str:
        r = self.http.get(f"{self.url}/instance/connectionState/{self.instancia}", timeout=10,
                          headers={"apikey": self.apikey})
        if r.status_code in (401, 403):
            raise RuntimeError("A Evolution recusou a apikey.")
        if not r.ok:
            return "?"
        corpo = r.json() or {}
        return str((corpo.get("instance") or corpo).get("state") or "?")

    def iniciar(self) -> None:
        self.nucleo.registrar_enviador(self.avisar_cliente)
        self.nucleo.registrar_notificador(self.avisar_donos)
        self.nucleo.iniciar_despachante()
        self.nucleo.iniciar_limpeza_carrinhos()
        self.servidor.iniciar()

    def parar(self) -> None:
        self.nucleo.parar_despachante()
        self.nucleo.parar_limpeza_carrinhos()
        self.servidor.parar()
        self.despacho.parar()


def main() -> None:
    import registro_mensagens as rm
    from atendimento import atendimento as nucleo
    try:
        canal = CanalNaoOficial(nucleo, rm)
    except RuntimeError as e:
        sys.exit(str(e))
    try:
        estado = canal.estado_da_instancia()
        if estado == "open":
            logging.info("Instância '%s' conectada ao WhatsApp.", canal.instancia)
        else:
            logging.warning("Instância '%s' está '%s' (esperado 'open'): leia o QR code no Evolution Manager.",
                            canal.instancia, estado)
    except RuntimeError as e:
        sys.exit(str(e))
    except requests.RequestException:
        logging.warning("Não consegui falar com a Evolution em %s agora; sigo mesmo assim.", canal.url)
    if not canal.donos_tel:
        logging.warning("Nenhum vendedor em whatsapp_nao_oficial > donos: ninguém confirma comandas nem recebe avisos. "
                        "Mande 'id' ao bot para descobrir seu telefone/id.")
    canal.iniciar()
    logging.info("Webhook em http://%s:%s/webhook?token=...  (cadastre essa URL na instância da Evolution). "
                 "Ctrl+C para parar.", canal.host, canal.servidor.porta)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        canal.parar()
        logging.info("Bot encerrado.")


if __name__ == "__main__":
    main()
