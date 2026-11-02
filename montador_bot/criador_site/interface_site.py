"""
interface_site.py  --  Criador de site (Streamlit): logo, 3 cores, molde, preview e botão de gerar o site.

No montador ele é a aba "2 · Site": montador_ui.py chama desenhar(). O site é gerado da loja do catálogo
(catalogo/loja/), a MESMA que o bot recebe, e vai para catalogo/loja/site/ (essa pasta não vai para dentro do bot).
Sozinho, para testes:  streamlit run interface_site.py

Depende SÓ da pasta da loja, onde ficam juntos:
    catalogo.db   produtos_especializados.db   imagens/

Nome da loja, WhatsApp, cores, molde e logo são gravados dentro do catalogo.db (tabelas site_config e site_logo).
Loja por orçamento (config.json da loja): o site mostra «A combinar» no lugar dos preços.
Canal Telegram com @usuario do bot preenchido no montador: o botão do carrinho abre o Telegram em vez do WhatsApp.

Você:
  - envia a logo (as 3 cores mais frequentes dela são sugeridas) e ajusta as 3 cores (60% fundo / 30% secundária / 10% destaque);
  - vê qual molde o programa recomenda (e por quê) e pode trocar na mão;
  - confere o preview (celular ou computador) -- ele já mostra as mudanças ainda não salvas;
  - clica em "Gerar / regerar site" quando quiser (sempre que entrar ou sair um item, o aviso amarelo lembra).

Instalar:  pip install streamlit pillow
"""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import gerador_site as gs
from gerador_site import ErroDados, PastaDados

ROTULOS_COR = (
    ("fundo", "Cor de fundo (60%)", "A cor da página, a que mais aparece."),
    ("secundaria", "Cor secundária (30%)", "Barra de cima, cartões e gaveta do carrinho."),
    ("destaque", "Cor de destaque (10%)", "Botões, preços e o que está selecionado."),
)
AUTO = "Automático (o recomendado)"


def desenhar(raiz=None, telegram_usuario=""):
    """Desenha o criador de site no lugar onde for chamada (uma aba, por exemplo).
    `raiz`: pasta da loja (padrão: a loja do catálogo). `telegram_usuario`: @ do bot, quando o canal é o Telegram
    (o site passa a pedir pelo Telegram). Aqui dentro não há st.set_page_config nem st.stop: o resto da página continua."""
    pasta = PastaDados(Path(raiz) if raiz else gs.pasta_padrao())
    telegram_usuario = str(telegram_usuario or "").strip().lstrip("@")

    st.caption("O site sai da loja cadastrada na aba 1 (mesmos produtos, fotos e variações do bot). "
               "Cadastre e aprove os produtos lá; depois ajuste a cara do site aqui.")
    if not pasta.catalogo.is_file():
        st.info("A loja ainda não tem produtos. Cadastre ao menos um produto na aba 1 · Catálogo para criar o site.")
        return
    for rotulo, ok in (("produtos_especializados.db", pasta.estoque.is_file()), ("imagens/", pasta.imagens.is_dir())):
        if not ok:
            st.warning(f"Não encontrei {rotulo} na loja ({pasta.raiz}).")

    uid = hashlib.md5(str(pasta.raiz).encode()).hexdigest()[:6]
    ch = lambda nome: f"site_{nome}_{uid}"   # estado separado por pasta de dados, e longe das chaves de outras abas

    try:
        tema = gs.ler_tema(pasta)
        cfg = gs.ler_cfg(pasta)
        logo = gs.ler_logo(pasta)
    except ErroDados as e:
        st.error(str(e))
        return

    # ---- estado: valores iniciais dos campos e troca de cores sugeridas ----
    if st.session_state.pop("site_aplicar_cores", None):
        for k, v in zip(("fundo", "secundaria", "destaque"), st.session_state.pop(ch("sugestao"), [])):
            st.session_state[ch("cor_" + k)] = v
    for k in ("fundo", "secundaria", "destaque"):
        st.session_state.setdefault(ch("cor_" + k), tema["cores"][k])
    msg = st.session_state.pop("site_msg", None)

    col_ctrl, col_prev = st.columns([2, 3], gap="large")

    # ================================ controles =================================
    with col_ctrl:
        st.subheader("Logo")
        arq = st.file_uploader("Logo da loja", type=["png", "jpg", "jpeg", "webp", "svg"], key=ch("upload_logo"),
                               help="PNG com fundo transparente fica melhor. Ao enviar, ela já é salva no catalogo.db.")
        if arq is not None:
            dados = arq.getvalue()
            marca = hashlib.md5(dados).hexdigest()
            if st.session_state.get(ch("ultima_logo")) != marca:
                try:
                    gs.salvar_logo(pasta, arq.name, dados)
                except ErroDados as e:
                    st.error(str(e))
                else:
                    st.session_state[ch("ultima_logo")] = marca
                    sug = gs.extrair_cores(dados)
                    if sug:
                        st.session_state[ch("sugestao")] = sug
                    st.rerun()
        if logo:
            st.image(logo[1], width=120)
        else:
            st.caption("Nenhuma logo ainda: o site vai mostrar só o nome da loja.")

        st.subheader("Cores")
        sug = st.session_state.get(ch("sugestao"))
        if sug:
            st.caption("Cores mais frequentes da logo:")
            st.markdown(" ".join(f"<span style='display:inline-block;width:34px;height:34px;border-radius:6px;"
                                 f"background:{c};border:1px solid #8883' title='{c}'></span>" for c in sug), unsafe_allow_html=True)
            if st.button("🎨 Usar as cores da logo", key=ch("usar_cores")):
                st.session_state["site_aplicar_cores"] = True
                st.rerun()
        cores = {}
        for chave, rotulo, ajuda in ROTULOS_COR:
            cores[chave] = st.color_picker(rotulo, key=ch("cor_" + chave), help=ajuda)

        st.subheader("Loja e pedido")
        if gs.config_da_loja(pasta).get("orcamento"):
            st.info("Esta loja trabalha por orçamento (aba 1): o site mostra «A combinar» no lugar dos preços "
                    "e o carrinho não mostra valores.")
        nome_loja = st.text_input("Nome da loja", value=cfg["nome"] or gs.nome_padrao(pasta), key=ch("nome"))
        numero = st.text_input("Número do WhatsApp", value=cfg["whatsapp"], key=ch("zap"),
                               placeholder="5585999999999",
                               help="Código do país + DDD + número, só dígitos. Ex.: 5585999999999")
        mensagem = st.text_input("Mensagem inicial do pedido (opcional)", value=cfg["mensagem_inicial"], key=ch("mensagem"))
        usar_estoque = st.checkbox("Mostrar/limitar pelo estoque", value=cfg["usar_estoque"], key=ch("usar_estoque"),
                                   help="Só vale quando há SKUs em produtos_especializados.db.")
        so_nomes = st.checkbox("Pedido só com o nome dos produtos (sem ID/código)", value=cfg["pedido_so_nomes"],
                               key=ch("so_nomes"),
                               help="Vale para o site todo. No WhatsApp o pedido vai com um texto pronto e só os nomes "
                                    "(com a quantidade). A mensagem inicial acima, se preenchida, vira a abertura do texto. "
                                    "No Telegram o pedido sempre vai por código.")
        tg = gs.usuario_telegram({"telegram_usuario": telegram_usuario})
        if tg:
            st.success(f"O botão do carrinho abre o Telegram do bot @{tg} (definido na aba Canal e PIX). "
                       "O número do WhatsApp fica só de reserva.")
        elif telegram_usuario:
            st.warning("O @usuario do bot do Telegram (aba Canal e PIX) parece inválido: o site vai pedir pelo WhatsApp.")
        cfg_atual = {"nome": nome_loja, "whatsapp": gs.limpar_numero(numero),
                     "mensagem_inicial": mensagem, "usar_estoque": usar_estoque, "pedido_so_nomes": so_nomes}
        _, aviso_zap = gs.numero_whatsapp(cfg_atual)
        if aviso_zap and not tg:
            st.warning(aviso_zap)
        cfg_atual_site = {**cfg_atual, "telegram_usuario": telegram_usuario}   # o @ do bot vale só para gerar, não é gravado

    tema_atual = {"cores": cores, "molde": None}

    # ---- análise (sem escrever nada): contagem, recomendação, estado do site ----
    try:
        analise = gs.analisar_loja(pasta, molde=None, tema=tema_atual, cfg=cfg_atual_site)
    except ErroDados as e:
        with col_ctrl:
            st.info(str(e))
        return

    with col_ctrl:
        st.subheader("Molde")
        st.info(f"**Recomendado: {gs.NOMES_MOLDE[analise['recomendado']]}**\n\n{analise['motivo']}")
        opcoes = [AUTO] + [gs.NOMES_MOLDE[n] for n in (1, 2, 3, 4)]
        inicial = AUTO if tema["molde"] is None else gs.NOMES_MOLDE[tema["molde"]]
        escolha = st.selectbox("Molde do site", opcoes, index=opcoes.index(inicial), key=ch("molde"))
        molde = None if escolha == AUTO else next(n for n, t in gs.NOMES_MOLDE.items() if t == escolha)
        molde_final = molde or analise["recomendado"]
        pode, porque = gs.molde_possivel(molde_final, analise["contagem"])
        if not pode:
            st.error(porque + " Escolha outro molde.")
        tema_atual["molde"] = molde
        analise_final = analise   # a assinatura precisa ser a do molde ESCOLHIDO, para o aviso de "desatualizado" valer
        if pode and molde_final != analise["molde"]:
            analise_final = gs.analisar_loja(pasta, molde=molde_final, tema=tema_atual, cfg=cfg_atual_site)
        with st.expander("Categorias da loja"):
            for c, n in analise["contagem"].items():
                st.write(f"{c}: {n} iten(s)")

    # ================================== preview ==================================
    estado = analise_final["estado"]
    with col_prev:
        if msg:
            st.success(msg)
        if not estado["gerado"]:
            st.warning("O site ainda não foi gerado.")
        elif estado["desatualizado"]:
            st.warning(f"O catálogo, os SKUs, as configurações, o tema ou o molde mudou desde a última geração "
                       f"({estado['quando']}). Clique em **Gerar / regerar site**.")
        else:
            st.success(f"Site atualizado (gerado em {estado['quando']}, molde {estado['molde']}).")

        c1, c2, c3 = st.columns([1, 1.5, 1.6])
        with c1:
            salvar = st.button("💾 Salvar tudo", key=ch("salvar"))
        with c2:
            gerar = st.button("🔄 Gerar / regerar site", type="primary", disabled=not pode, key=ch("gerar"))
        with c3:
            tela = st.radio("Preview", ["Celular", "Computador"], horizontal=True, label_visibility="collapsed",
                            key=ch("tela"))

        if salvar or gerar:
            try:
                cfg_salva = gs.gravar_cfg(pasta, cfg_atual)
                gs.gravar_tema(pasta, tema_atual)
                if gerar:
                    res = gs.gerar_site(pasta, molde=molde_final, tema=tema_atual,
                                        cfg={**cfg_salva, "telegram_usuario": telegram_usuario})
                    extra = f" Avisos: {len(res['avisos'])}." if res["avisos"] else ""
                    st.session_state["site_msg"] = (f"Site gerado em {res['pasta']} (molde {res['molde']}, "
                                                    f"{res['produtos']} produtos).{extra}")
                else:
                    st.session_state["site_msg"] = "Configurações e tema salvos no catalogo.db."
                st.rerun()
            except (ErroDados, PermissionError) as e:
                st.error(str(e))

        if estado["gerado"]:
            st.download_button("⬇️ Baixar o site (.zip)", _zip_do_site(str(pasta.raiz), estado["quando"]),
                               f"site-{_slug(nome_loja)}.zip", "application/zip", key=ch("baixar"),
                               help="A pasta site/ inteira, pronta para hospedar. Abre direto no navegador (index.html).")

        if pode:
            try:
                pagina = _preview(str(pasta.raiz), molde_final, json.dumps(tema_atual, sort_keys=True),
                                  json.dumps(cfg_atual_site, sort_keys=True), analise_final["assinatura"])
                _mostrar(pagina, 390 if tela == "Celular" else None)
                st.caption("O preview mostra as mudanças ainda não salvas. O botão de pedir só funciona no site gerado.")
            except ErroDados as e:
                st.error(str(e))

        if analise["avisos"]:
            with st.expander(f"Avisos ({len(analise['avisos'])})"):
                for a in analise["avisos"]:
                    st.write("• " + a)


def _slug(texto):
    """Nome de arquivo simples a partir do nome da loja."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "loja"


def _mostrar(pagina, largura):
    """Mostra o site num quadro. st.iframe nas versões novas do Streamlit; components.html nas antigas."""
    if hasattr(st, "iframe"):
        st.iframe(pagina, width=largura or "stretch", height=760)
    else:
        components.html(pagina, width=largura, height=760, scrolling=True)


@st.cache_data(show_spinner="Montando o preview…", max_entries=8)
def _preview(raiz, molde, tema_json, cfg_json, assinatura):
    # `assinatura` só entra aqui para o cache renovar quando o catálogo, os SKUs, as fotos ou o tema mudarem
    return gs.html_preview(PastaDados(Path(raiz)), molde=molde, tema=json.loads(tema_json), cfg=json.loads(cfg_json))


@st.cache_data(show_spinner=False, max_entries=4)
def _zip_do_site(raiz, quando):
    """A pasta site/ num .zip (em memória). `quando` (hora da geração) só renova o cache quando o site é regerado."""
    site = PastaDados(Path(raiz)).site
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(site.rglob("*")):
            if arq.is_file():
                z.write(arq, arq.relative_to(site).as_posix())
    return buf.getvalue()


def main():
    st.set_page_config(page_title="Criador de site", page_icon="🌐", layout="wide")
    st.title("Criador de site")
    desenhar()


if __name__ == "__main__":
    main()
