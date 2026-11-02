"""montador_ui.py -- tela do montador de bots.   Rodar:  streamlit run montador_ui.py   (ou abrir_montador.bat)

1 · Catálogo: cadastra a loja (produtos, fotos, variações, estoque inicial) em catalogo/loja/.
2 · Site: gera o site da MESMA loja (criador_site/); sai em catalogo/loja/site/ e não vai para dentro do bot.
3-5: canal, PIX, textos e ajustes.   6 · Montar: entrega a pasta do bot pronta, com a loja dentro (loja/).
A lógica está em montador.py, catalogo/ e criador_site/; aqui só tem tela.
"""
import json
import re
import sys
from pathlib import Path

import streamlit as st

import montador as m

sys.path.insert(0, str(m.CATALOGO))   # o catálogo importa nucleo/ e variacoes/ pelo nome
import interface_catalogo as catalogo_ui  # noqa: E402

sys.path.insert(0, str(m.CRIADOR_SITE))   # o criador de site importa gerador_site pelo nome (e acha moldes_site/ ao lado)
import interface_site as site_ui  # noqa: E402

st.set_page_config(page_title="Montador de bots", page_icon="🤖", layout="wide")

CAMPOS_SIMPLES = {   # chave da tela -> (seção, campo)
    "tok": ("telegram", "token"), "tg_usuario": ("telegram", "usuario"), "pix_chave": ("pix", "chave"), "pix_nome": ("pix", "nome"),
    "pix_cidade": ("pix", "cidade"),
    "a_iguais": ("antispam", "max_mensagens_iguais"), "a_sem": ("antispam", "max_sem_sentido"),
    "a_timeout": ("antispam", "timeout_min"), "a_janela": ("antispam", "janela_min"),
    "wo_token": ("whatsapp_oficial", "token"), "wo_numero": ("whatsapp_oficial", "phone_number_id"),
    "wo_segredo": ("whatsapp_oficial", "app_secret"), "wo_verify": ("whatsapp_oficial", "verify_token"),
    "wo_versao": ("whatsapp_oficial", "versao_api"), "wo_porta": ("whatsapp_oficial", "porta"),
    "wo_tpl": ("whatsapp_oficial", "template_aviso_nome"), "wo_tpl_idioma": ("whatsapp_oficial", "template_aviso_idioma"),
    "wn_url": ("whatsapp_nao_oficial", "url_api"), "wn_apikey": ("whatsapp_nao_oficial", "apikey"),
    "wn_instancia": ("whatsapp_nao_oficial", "instancia"), "wn_token": ("whatsapp_nao_oficial", "token_webhook"),
    "wn_porta": ("whatsapp_nao_oficial", "porta"),
}
DONOS = {"donos": "telegram", "wo_donos": "whatsapp_oficial", "wn_donos": "whatsapp_nao_oficial"}   # chave da tela -> seção


# ------------------------------------------------------------------ configuração <-> widgets
LIMITES = {"a_iguais": (2, 50), "a_sem": (2, 50), "a_timeout": (1, 1440), "a_janela": (1, 1440),
           "carrinho": (1, 1440), "orc_pausa": (1, 1440), "trab": (1, 64), "wo_porta": (1, 65535), "wn_porta": (1, 65535)}   # iguais aos dos campos da aba 5


def _limitar(chave: str, valor):
    """Número fora do limite (perfil antigo ou editado à mão) faria o campo da tela dar erro: encaixa no limite."""
    if chave not in LIMITES:
        return valor
    lo, hi = LIMITES[chave]
    try:
        return max(lo, min(hi, int(valor)))
    except (TypeError, ValueError):
        return lo


def _para_tela(cfg: dict) -> None:
    """Joga uma configuração nos widgets (só chamar antes de eles serem desenhados, ou num callback)."""
    for chave, (secao, campo) in CAMPOS_SIMPLES.items():
        st.session_state[chave] = _limitar(chave, cfg[secao][campo])
    for chave, secao in DONOS.items():
        st.session_state[chave] = "\n".join(str(d) for d in cfg[secao]["donos"])
    st.session_state["canal"] = cfg["canal"] if cfg["canal"] in m.CANAIS else "telegram"
    st.session_state["carrinho"] = _limitar("carrinho", cfg["carrinho_minutos"])
    st.session_state["orc_pausa"] = _limitar("orc_pausa", cfg["orcamento_pausa_minutos"])
    st.session_state["trab"] = _limitar("trab", cfg["trabalhadores"])
    for chave in m.CHAVES_TEXTO:
        st.session_state["t_" + chave] = cfg["textos"][chave]


def _da_tela() -> dict:
    cfg = m.config_padrao()
    for chave, (secao, campo) in CAMPOS_SIMPLES.items():
        cfg[secao][campo] = st.session_state[chave]
    for chave, secao in DONOS.items():
        cfg[secao]["donos"] = [d for d in re.split(r"[,;\s]+", st.session_state[chave]) if d]
    cfg["canal"] = st.session_state["canal"]
    cfg["carrinho_minutos"] = st.session_state["carrinho"]
    cfg["orcamento_pausa_minutos"] = st.session_state["orc_pausa"]
    cfg["trabalhadores"] = st.session_state["trab"]
    cfg["textos"] = {c: st.session_state["t_" + c] for c in m.CHAVES_TEXTO}
    return cfg


def _restaurar_textos() -> None:
    for chave, valor in m.config_padrao()["textos"].items():
        st.session_state["t_" + chave] = valor


def _conferir_loja():
    """Confere a loja do catálogo. Devolve (dados da loja, None) ou (None, mensagem de erro)."""
    if not (m.LOJA_CATALOGO / "config.json").is_file():
        return None, "A loja ainda não foi criada. Cadastre-a na aba 1 · Catálogo."
    try:
        with m.abrir_loja(m.LOJA_CATALOGO) as loja:
            return {"nome": loja.nome, "modo": loja.modo, "produtos": loja.produtos,
                    "skus": loja.skus, "avisos": loja.avisos}, None
    except m.ErroMontagem as e:
        return None, str(e)


# ------------------------------------------------------------------ início
if "iniciado" not in st.session_state:
    _para_tela(m.config_padrao())
    st.session_state.update(iniciado=True, nome_bot="", destino=str(Path.home() / "Documents"), testar=True,
                            perfil_aplicado=None)

st.title("🤖 Montador de bots")
st.caption("Cadastre a loja no catálogo, preencha o que muda de loja para loja e o montador entrega a pasta do bot "
           "pronta, com tudo apontando para os lugares certos.")

perfil = st.file_uploader("Reaproveitar as configurações de outro bot (opcional): envie o bot_config.json dele",
                          type=["json"])
if perfil is not None and st.session_state["perfil_aplicado"] != (perfil.name, perfil.size):
    try:
        _para_tela(m.aplicar_perfil(m.config_padrao(), json.loads(perfil.getvalue().decode("utf-8-sig"))))
        st.session_state["perfil_aplicado"] = (perfil.name, perfil.size)
        st.success("Configurações carregadas. Confira as abas e troque o que for da nova loja (token, PIX, saudação).")
    except (ValueError, UnicodeDecodeError):
        st.error("Esse arquivo não é um JSON válido.")

aba_loja, aba_site, aba_tg, aba_textos, aba_ajustes, aba_montar = st.tabs(
    ["1 · Catálogo", "2 · Site", "3 · Canal e PIX", "4 · Textos", "5 · Ajustes", "6 · Montar"])

# ------------------------------------------------------------------ 1 catálogo (a loja é cadastrada aqui)
with aba_loja:
    col_lateral, col_catalogo = st.columns([1, 3])
    with col_catalogo:
        catalogo_ui.desenhar(lateral=col_lateral)

# ------------------------------------------------------------------ 2 site (da mesma loja do catálogo)
with aba_site:
    # com o canal Telegram e o @usuario do bot preenchido (aba 3), o botão do carrinho do site abre o Telegram em vez do WhatsApp
    site_ui.desenhar(m.LOJA_CATALOGO,
                     telegram_usuario=st.session_state["tg_usuario"] if st.session_state["canal"] == "telegram" else "")

# ------------------------------------------------------------------ 3 telegram e pix
with aba_tg:
    st.subheader("Canal")
    st.radio("Por onde o bot atende?", list(m.CANAIS), format_func=m.CANAIS.get, key="canal",
             help="O Telegram é só para testar. Preencha o canal escolhido; os outros ficam guardados no bot_config.json.")
    atual = st.session_state["canal"]
    with st.expander("Telegram", expanded=atual == "telegram"):
        st.text_input("Token do bot (do @BotFather)", key="tok", type="password",
                      help="Fica no bot_config.json do bot montado. Não envie essa pasta a ninguém sem apagar o token.")
        st.text_input("@usuario do bot (para o link do site)", key="tg_usuario",
                      help="Ex.: MinhaLoja_bot. O botão do site abre t.me/<usuario>?start=<carrinho> e o pedido já entra no bot.")
        st.text_area("Vendedores (chat id), um por linha", key="donos", height=80,
                     help="Quem confirma/cancela comandas e recebe o aviso de comanda nova. Não sabe o seu? "
                          "Ligue o bot, mande /id para ele e preencha depois.")
    with st.expander("WhatsApp oficial (Cloud API da Meta)", expanded=atual == "whatsapp_oficial"):
        o1, o2 = st.columns(2)
        o1.text_input("Token de acesso (permanente)", key="wo_token", type="password")
        o2.text_input("ID do número (phone_number_id)", key="wo_numero", help="Está no painel da Meta; não é o telefone.")
        o3, o4 = st.columns(2)
        o3.text_input("Segredo do app (app secret)", key="wo_segredo", type="password",
                      help="Serve para conferir que o webhook veio mesmo da Meta.")
        o4.text_input("verify_token do webhook", key="wo_verify",
                      help="Você inventa; use o mesmo ao cadastrar o webhook na Meta. Vazio = o montador gera um.")
        o5, o6 = st.columns(2)
        o5.number_input("Porta do webhook", 1, 65535, key="wo_porta")
        o6.text_input("Versão da Graph API", key="wo_versao")
        st.text_area("Vendedores: telefone com DDI+DDD (5585999999999) ou BSUID, um por linha", key="wo_donos", height=80)
        o7, o8 = st.columns(2)
        o7.text_input("Template de aviso ao vendedor (opcional)", key="wo_tpl",
                      help="Nome de um template aprovado na Meta, com UMA variável no corpo. Serve para avisar o vendedor "
                           "depois de 24h sem ele escrever ao bot.")
        o8.text_input("Idioma do template", key="wo_tpl_idioma")
    with st.expander("WhatsApp NÃO oficial (Evolution API) — risco de banimento, só para teste",
                     expanded=atual == "whatsapp_nao_oficial"):
        n1, n2 = st.columns(2)
        n1.text_input("Endereço da Evolution API", key="wn_url")
        n2.text_input("apikey", key="wn_apikey", type="password")
        n3, n4 = st.columns(2)
        n3.text_input("Nome da instância", key="wn_instancia")
        n4.text_input("Token do webhook", key="wn_token", help="Vazio = o montador gera um.")
        st.number_input("Porta do webhook", 1, 65535, key="wn_porta")
        st.text_area("Vendedores: telefone com DDI+DDD (5585999999999), um por linha", key="wn_donos", height=80)

    st.subheader("PIX")
    st.caption("Preencha os três ou deixe os três vazios.")
    p1, p2, p3 = st.columns([2, 2, 1])
    p1.text_input("Chave PIX", key="pix_chave", help="CPF, telefone (+55...), e-mail ou chave aleatória")
    p2.text_input("Nome do recebedor", key="pix_nome", help="até 25 letras")
    p3.text_input("Cidade", key="pix_cidade", help="até 15 letras")

# ------------------------------------------------------------------ 4 textos
with aba_textos:
    st.caption("O que o bot diz. Mantenha os {campos} entre chaves: o bot troca por nome, número, total etc.")
    st.button("↩️ Restaurar todos os textos ao padrão", on_click=_restaurar_textos)
    for chave, titulo, dica in m.TEXTOS:
        st.text_area(titulo, key="t_" + chave, help=dica or None, height=100 if len(st.session_state["t_" + chave]) > 120 else 70)

# ------------------------------------------------------------------ 5 ajustes
with aba_ajustes:
    st.subheader("Anti-spam")
    a1, a2 = st.columns(2)
    a1.number_input("Mensagens iguais seguidas até bloquear", 2, 50, key="a_iguais")
    a2.number_input("Mensagens sem sentido seguidas até bloquear", 2, 50, key="a_sem")
    a3, a4 = st.columns(2)
    a3.number_input("Minutos de bloqueio", 1, 1440, key="a_timeout")
    a4.number_input("Janela das repetições (minutos)", 1, 1440, key="a_janela")
    st.subheader("Atendimento")
    b1, b2 = st.columns(2)
    b1.number_input("Minutos até um carrinho parado devolver o estoque", 1, 1440, key="carrinho")
    b2.number_input("Clientes atendidos ao mesmo tempo", 1, 64, key="trab")
    st.number_input("Loja por orçamento: minutos de bot calado depois que a comanda fecha (volta sozinho)", 1, 1440,
                    key="orc_pausa", help="Só vale se a loja estiver marcada «por orçamento» no catálogo. O atendente pode "
                                          "ligar antes: comando «ligar 7» no chat ou botão no painel.")

# ------------------------------------------------------------------ 6 montar
with aba_montar:
    cfg = _da_tela()
    erros, avisos = m.validar_config(cfg)
    loja_info, loja_erro = _conferir_loja()
    if loja_erro:
        st.error(loja_erro)
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Loja", loja_info["nome"])
        c2.metric("Produtos ativos", loja_info["produtos"])
        c3.metric("Variações à venda", loja_info["skus"])
        for aviso in loja_info["avisos"]:
            st.warning(aviso)
    n1, n2 = st.columns(2)
    padrao_nome = f"bot-{m.slug(loja_info['nome'], 'minha-loja')}" if loja_info else "bot-minha-loja"
    nome_bot = n1.text_input("Nome da pasta do bot", key="nome_bot", placeholder=padrao_nome) or padrao_nome
    n2.text_input("Criar dentro de", key="destino")
    st.checkbox("Testar o bot montado no final", key="testar",
                help="Abre o bot uma vez para conferir que ele lê a loja e o bot_config.json. Precisa do rapidfuzz instalado.")
    st.checkbox("Entregar só executáveis (esconde o código)", key="exe",
                help="Troca os .py por .exe (iniciar_bot, painel, alterar_loja). Precisa do PyInstaller e só gera .exe se este montador estiver no Windows. Demora alguns minutos.")
    st.markdown(f"Vai criar: `{Path(st.session_state['destino']).expanduser() / m.slug(nome_bot, 'bot')}`")
    for e in erros:
        st.error(e)
    for a in avisos:
        st.warning(a)
    pronto = bool(loja_info) and not erros
    if st.button("🚀 Montar bot", type="primary", disabled=not pronto):
        try:
            with st.spinner("Montando..."):
                r = m.montar(None, st.session_state["destino"], nome_bot, cfg, testar=st.session_state["testar"], exe=st.session_state.get("exe", False))
        except m.ErroMontagem as e:
            st.error(str(e))
        else:
            st.success(f"Bot montado em: {r.pasta}")
            for p in r.passos:
                st.write("✅ " + p)
            for a in r.avisos:
                st.warning(a)
            st.markdown("**Próximos passos:** abra a pasta, dê dois cliques em `iniciar_bot.bat` e em `abrir_painel.bat`. "
                        "Para mudar preço, nome, descrição ou categoria depois, use `alterar_loja.bat`. "
                        "Para montar o bot de outro cliente, use «Zerar loja» na aba 1 e cadastre a próxima loja.")
            st.download_button("⬇️ Baixar uma cópia do bot_config.json (serve de perfil para a próxima loja)",
                               (r.pasta / "bot_config.json").read_bytes(), "bot_config.json", "application/json")
    if not pronto:
        st.caption("Para montar: deixe a loja válida na aba 1 e corrija os erros acima.")
