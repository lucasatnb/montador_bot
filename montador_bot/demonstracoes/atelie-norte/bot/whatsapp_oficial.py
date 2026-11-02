"""Canal WhatsApp OFICIAL (Cloud API da Meta). Recebe por webhook e responde pela Graph API.

Como ligar (resumo; o passo a passo está no LEIA-ME.txt do bot montado):
  1. Em developers.facebook.com: app tipo "Business" com o produto WhatsApp; copie o ID do número
     (phone_number_id), crie um token permanente (usuário do sistema) e anote o "segredo do app" (app secret).
  2. Preencha em bot_config.json > whatsapp_oficial: token, phone_number_id, app_secret e verify_token
     (qualquer texto que você inventar; o montador já gera um). Variáveis de ambiente também valem:
     WA_TOKEN, WA_PHONE_NUMBER_ID, WA_APP_SECRET, WA_VERIFY_TOKEN.
  3. Deixe o bot acessível por HTTPS (hospedagem, ou um túnel como Cloudflare Tunnel/ngrok apontando para a porta
     do bot) e, no painel da Meta (WhatsApp > Configuração > Webhook), cadastre  https://SEU-ENDERECO/webhook  com o
     mesmo verify_token e assine o campo "messages".
  4. python whatsapp_oficial.py

Identidade do cliente: desde 31/03/2026 o webhook traz o BSUID (user_id), e o telefone (wa_id/from) pode faltar.
A chave do cliente é "wa:<BSUID>" (ou "wa:<telefone>" se não houver BSUID). Vendedores (donos) podem ser listados
por telefone (5585999999999) OU por BSUID.

Janela de 24h: texto livre só sai até 24h depois da última mensagem do cliente. Para avisar o vendedor fora da
janela, crie na Meta um template de utilidade com UMA variável no corpo ({{1}}) e preencha template_aviso_nome
(e template_aviso_idioma). Sem isso o aviso fora da janela só vai para o log.
"""
import hashlib
import hmac
import json
import logging
import re
import sys
import time

import requests

import canal_comum as cc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SECAO = "whatsapp_oficial"
ERROS_CONHECIDOS = {
    131047: "fora da janela de 24h (o cliente não escreveu nas últimas 24h): só vale template aprovado",
    130497: "a conta está restrita de enviar para este país (ver nível/categoria do negócio na Meta)",
    131030: "número fora da lista de destinatários permitidos (conta ainda em modo de teste)",
    131026: "mensagem não entregável (número sem WhatsApp ou versão antiga do app)",
    131056: "muitas mensagens para o mesmo cliente em pouco tempo, tente de novo mais tarde",
    190: "token inválido ou expirado",
}


class ErroEnvio(RuntimeError):
    def __init__(self, codigo, mensagem):
        super().__init__(mensagem)
        self.codigo = codigo


class _EscondeSegredos(logging.Formatter):
    segredos = []

    def format(self, record):
        texto = super().format(record)
        for s in self.segredos:
            if s:
                texto = texto.replace(s, "***")
        return texto


def _telefone_valido(valor: str) -> bool:
    return bool(re.fullmatch(r"\+?\d{10,15}", str(valor).strip()))


class CanalOficial:
    def __init__(self, nucleo, rm, config: dict = None, enderecos=None):
        c = config or {}
        pegar = lambda chave, env="", padrao="": c.get(chave) or cc.cfg(SECAO, chave, env, padrao)
        self.token = str(pegar("token", "WA_TOKEN")).strip()
        self.numero_id = str(pegar("phone_number_id", "WA_PHONE_NUMBER_ID")).strip()
        self.verify_token = str(pegar("verify_token", "WA_VERIFY_TOKEN")).strip()
        self.segredo = str(pegar("app_secret", "WA_APP_SECRET")).strip()
        self.versao = str(pegar("versao_api", "", "v23.0")).strip()
        self.api_base = str(pegar("api_base", "", "https://graph.facebook.com")).rstrip("/")
        self.template = str(pegar("template_aviso_nome", "")).strip()
        self.idioma = str(pegar("template_aviso_idioma", "", "pt_BR")).strip()
        self.host = str(pegar("host", "", "0.0.0.0"))
        self.porta = int(pegar("porta", "", 8000))
        self.donos_cfg = [str(d).strip().removeprefix("wa:") for d in (c.get("donos") or cc.cfg(SECAO, "donos", "", []))
                          if str(d).strip()]
        self.donos_tel = {cc.so_digitos(d) for d in self.donos_cfg if _telefone_valido(d)}
        self.donos_bsuid = {d for d in self.donos_cfg if not _telefone_valido(d)}
        faltando = [n for n, v in (("token", self.token), ("phone_number_id", self.numero_id),
                                   ("verify_token", self.verify_token), ("app_secret", self.segredo)) if not v]
        if faltando:
            raise RuntimeError("Faltam em bot_config.json > whatsapp_oficial: " + ", ".join(faltando))
        self.nucleo, self.rm = nucleo, rm
        self.enderecos = enderecos or cc.Enderecos()
        self.http = requests.Session()
        self.despacho = cc.Despacho(int(c.get("trabalhadores") or cc.CONFIG.get("trabalhadores") or 8))
        self.servidor = cc.Servidor(self.host, self.porta, self._http)
        self.nucleo.DONOS.update(f"wa:{d}" for d in self.donos_bsuid)
        self.nucleo.DONOS.update(f"wa:{t}" for t in self.donos_tel)
        _EscondeSegredos.segredos = [self.token, self.segredo, self.verify_token]
        for h in logging.getLogger().handlers:
            h.setFormatter(_EscondeSegredos("%(asctime)s %(levelname)s %(message)s"))

    # ----------------------------------------------------------------- receber (webhook)
    def _http(self, metodo, caminho, query, cab, corpo):
        if caminho not in ("/webhook", "/webhook/"):
            return 200, "ok", "text/plain"   # saúde (túneis e hospedagens fazem GET /)
        if metodo == "GET":   # verificação do webhook, feita pela Meta ao cadastrar a URL
            if query.get("hub.mode") == "subscribe" and hmac.compare_digest(
                    str(query.get("hub.verify_token", "")), self.verify_token):
                return 200, query.get("hub.challenge", ""), "text/plain"
            logging.warning("verificação do webhook recusada (verify_token diferente do bot_config.json)")
            return 403, "verify_token inválido", "text/plain"
        if not self._assinatura_ok(cab.get("x-hub-signature-256", ""), corpo):
            logging.warning("webhook recusado: assinatura inválida (app_secret errado ou chamada que não é da Meta)")
            return 403, "assinatura inválida", "text/plain"
        try:
            payload = json.loads(corpo.decode("utf-8"))
        except ValueError:
            return 400, "json inválido", "text/plain"
        try:
            self.processar(payload)
        except Exception:   # nunca devolva erro para a Meta: ela reenviaria o mesmo webhook sem parar
            logging.exception("erro ao processar o webhook")
        return 200, "ok", "text/plain"

    def _assinatura_ok(self, cabecalho: str, corpo: bytes) -> bool:
        esperado = "sha256=" + hmac.new(self.segredo.encode(), corpo, hashlib.sha256).hexdigest()
        return hmac.compare_digest(esperado, cabecalho or "")

    def processar(self, payload: dict) -> None:
        for entrada in payload.get("entry") or []:
            for mudanca in entrada.get("changes") or []:
                v = mudanca.get("value") or {}
                for st in v.get("statuses") or []:
                    if st.get("status") == "failed":
                        for e in st.get("errors") or []:
                            logging.error("a Meta não entregou uma mensagem: %s %s", e.get("code"), e.get("title") or e.get("message"))
                for m in v.get("messages") or []:
                    self._mensagem(m, v.get("contacts") or [])

    def _mensagem(self, m: dict, contatos: list) -> None:
        if self.enderecos.ja_vista(m.get("id", "")):
            return
        bsuid = str(m.get("from_user_id") or "")
        tel = cc.so_digitos(m.get("from"))
        nome = ""
        for ct in contatos:   # o contato casa pelo BSUID ou pelo telefone; dele vêm o nome e o que faltar
            if (bsuid and ct.get("user_id") == bsuid) or (tel and cc.so_digitos(ct.get("wa_id")) == tel) or len(contatos) == 1:
                nome = (ct.get("profile") or {}).get("name", "")
                bsuid = bsuid or str(ct.get("user_id") or "")
                tel = tel or cc.so_digitos(ct.get("wa_id"))
                break
        if not (bsuid or tel):
            logging.warning("mensagem sem identificação do remetente, ignorada: %s", m.get("id"))
            return
        chave = "wa:" + (bsuid or tel)
        destino = tel or "bsuid:" + bsuid
        self.enderecos.salvar(chave, destino, tel, nome)
        if tel in self.donos_tel or (bsuid and bsuid in self.donos_bsuid):
            self.nucleo.DONOS.add(chave)   # vendedor cadastrado por telefone: reconhece o BSUID dele agora
        texto = (m.get("text") or {}).get("body", "") if m.get("type") == "text" else ""
        logging.info("%s escreveu: %r", chave, texto if texto else f"({m.get('type')})")

        def texto_id():
            return (f"Seu identificador: {bsuid or '-'}\nSeu telefone: {tel or '(oculto)'}\n"
                    "Para ser vendedor, coloque um deles em bot_config.json > whatsapp_oficial > donos e reinicie o bot.")

        responder = lambda t: self._enviar_seguro(destino, t)
        self.despacho.enviar(chave, lambda: cc.tratar_texto(
            self.nucleo, self.rm, chave=chave, nome=nome, texto=texto, enviar=responder, texto_id=texto_id))

    # ----------------------------------------------------------------- enviar
    def _post(self, corpo: dict) -> None:
        r = self.http.post(f"{self.api_base}/{self.versao}/{self.numero_id}/messages", json=corpo, timeout=20,
                           headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code >= 400:
            try:
                e = r.json().get("error") or {}
            except ValueError:
                e = {}
            codigo = e.get("code")
            detalhe = (e.get("error_data") or {}).get("details") or e.get("message") or r.text[:200]
            raise ErroEnvio(codigo, f"{ERROS_CONHECIDOS.get(codigo, 'a Meta recusou')} [{codigo}] {detalhe}")

    @staticmethod
    def _destinatario(destino: str) -> dict:
        return {"recipient": destino[6:]} if destino.startswith("bsuid:") else {"to": destino}

    def enviar(self, destino: str, texto: str, permitir_template: bool = False) -> None:
        for i, pedaco in enumerate(cc.dividir_texto(texto)):
            corpo = {"messaging_product": "whatsapp", "recipient_type": "individual", **self._destinatario(destino),
                     "type": "text", "text": {"body": pedaco, "preview_url": False}}
            try:
                self._post(corpo)
            except ErroEnvio as e:
                if e.codigo == 131047 and permitir_template and self.template and i == 0:
                    self._template(destino, texto)
                    return
                raise

    def _template(self, destino: str, texto: str) -> None:
        # variáveis de template não aceitam quebra de linha nem 4+ espaços seguidos (erro 132018 da Meta)
        limpo = re.sub(r"\s*\n\s*", " | ", texto.strip())
        limpo = re.sub(r" {2,}", " ", limpo)[:1000]
        self._post({"messaging_product": "whatsapp", **self._destinatario(destino), "type": "template",
                    "template": {"name": self.template, "language": {"code": self.idioma},
                                 "components": [{"type": "body", "parameters": [{"type": "text", "text": limpo}]}]}})

    def _enviar_seguro(self, destino: str, texto: str) -> None:   # resposta ao cliente: erro vai para o log, não derruba nada
        try:
            self.enviar(destino, texto)
        except (ErroEnvio, requests.RequestException) as e:
            logging.error("não consegui responder a %s: %s", destino, e)

    def avisar_cliente(self, chave: str, texto: str) -> None:   # usado pelo painel e pelos avisos de confirmar/cancelar
        destino = self.enderecos.destino(chave)
        if not destino:
            resto = chave.removeprefix("wa:")
            destino = resto if resto.isdigit() else "bsuid:" + resto
        self.enviar(destino, texto)   # levanta erro: o painel marca "falhou"

    def avisar_donos(self, texto: str) -> None:
        for d in self.donos_cfg:
            try:
                if _telefone_valido(d):
                    tel = cc.so_digitos(d)
                    destino = self.enderecos.destino_por_telefone(tel) or tel
                else:
                    destino = "bsuid:" + d
                self.enviar(destino, texto, permitir_template=True)
            except Exception as e:
                logging.error("não consegui avisar o vendedor %s: %s", d, e)

    # ----------------------------------------------------------------- ciclo de vida
    def conferir_credenciais(self) -> str:
        """Confere token e número na Meta. Devolve o número de exibição; levanta RuntimeError se o token for recusado."""
        r = self.http.get(f"{self.api_base}/{self.versao}/{self.numero_id}", timeout=15,
                          params={"fields": "display_phone_number,verified_name"},
                          headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code in (400, 401, 403):
            raise RuntimeError(f"A Meta recusou o token/número: {r.text[:200]}")
        return (r.json() or {}).get("display_phone_number", "?") if r.ok else "?"

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
        canal = CanalOficial(nucleo, rm)
    except RuntimeError as e:
        sys.exit(str(e))
    try:
        numero = canal.conferir_credenciais()
        logging.info("Conectado ao número %s (Cloud API %s).", numero, canal.versao)
    except RuntimeError as e:
        sys.exit(str(e))
    except requests.RequestException:
        logging.warning("Não consegui falar com a Meta agora para conferir o token; sigo mesmo assim.")
    if not canal.donos_cfg:
        logging.warning("Nenhum vendedor em whatsapp_oficial > donos: ninguém confirma comandas nem recebe avisos. "
                        "Mande 'id' ao bot para descobrir seu identificador.")
    canal.iniciar()
    logging.info("Webhook em http://%s:%s/webhook  (cadastre a URL pública HTTPS dele na Meta). Ctrl+C para parar.",
                 canal.host, canal.servidor.porta)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        canal.parar()
        logging.info("Bot encerrado.")


if __name__ == "__main__":
    main()
