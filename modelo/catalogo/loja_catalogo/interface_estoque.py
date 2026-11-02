"""
interface_estoque.py  --  Monitor e edição do ESTOQUE de uma loja (Streamlit)

É a interface do dia a dia: mostra o estoque que o bot está usando agora (o banco que ele desconta a cada venda),
deixa corrigir quantidades e tem o botão de emergência "ZERAR TODO O ESTOQUE".

  📊 Monitorar       situação de cada item (esgotado, baixo, ok, ilimitado, inativo), com atualização automática
  ✏️ Editar estoque  muda Quantidade / Ilimitado / Ativo e salva. Se o bot vender um item enquanto você edita,
                     esse item NÃO é sobrescrito (aparece como conflito): a venda nunca some.
  🕘 Histórico       tudo o que foi alterado por aqui (editar, zerar, desfazer)

  🚨 ZERAR TODO O ESTOQUE (sempre visível, no topo): pede uma confirmação, zera na hora e GUARDA o estado
  anterior, então dá para «Desfazer» em seguida. Também dá para zerar só alguns produtos (ex.: uma fornada estragou).

Cada loja tem o seu banco (lojas/<loja>/produtos.db ou produtos_especializados.db, conforme o modo da loja),
criado pela interface_catalogo.py ao salvar o primeiro produto.
Instalar:  pip install streamlit pandas
Rodar:     streamlit run interface_estoque.py
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from variacoes import constantes_especializado as ce
from nucleo.estoque_loja import EstoqueIndisponivel, EstoqueLoja
from nucleo.gerar_pastas import MODO_ESP, listar_lojas

VISOES = ["📊 Monitorar", "✏️ Editar estoque", "🕘 Histórico"]
ESGOTADO, BAIXO, OK, ILIMITADO, INATIVO = "🔴 Esgotado", "🟠 Baixo", "🟢 OK", "♾️ Ilimitado", "⚫ Inativo"
ORDEM = {ESGOTADO: 0, BAIXO: 1, OK: 2, ILIMITADO: 3, INATIVO: 4}


# ============================ lógica de tela (sem I/O) ========================

def situacao(item, limite):
    if not (item["ativo"] and item["produto_ativo"]):
        return INATIVO
    if item["ilimitado"]:
        return ILIMITADO
    if item["quantidade"] <= 0:
        return ESGOTADO
    if item["quantidade"] <= limite:
        return BAIXO
    return OK


def _fmt_estado(estado):
    q, ilim, ativo = estado
    return ("ilimitado" if ilim else f"{q} un.") + ("" if ativo else ", inativo")


def descrever_evento(e):
    acao = e.get("acao", "")
    if acao == "edição":
        return f"{e.get('item')}: {_fmt_estado(e['antes'])} → {_fmt_estado(e['depois'])}"
    if acao.startswith("zerar"):
        alvo = "" if not e.get("produtos") else f" (produtos: {', '.join(e['produtos'])})"
        return f"{e.get('itens', 0)} item(ns), {e.get('unidades', 0)} unidade(s){alvo}"
    if acao == "desfazer zerar":
        return f"{e.get('itens', 0)} restaurado(s), {e.get('conflitos', 0)} em conflito"
    return ""


# ================================ telas =======================================

def metricas(itens, limite):
    estados = [situacao(i, limite) for i in itens]
    unidades = sum(i["quantidade"] for i in itens if not i["ilimitado"] and i["ativo"] and i["produto_ativo"])
    c = st.columns(5)
    c[0].metric("Itens vendáveis", sum(1 for s in estados if s in (ESGOTADO, BAIXO, OK, ILIMITADO)))
    c[1].metric("🔴 Esgotados", estados.count(ESGOTADO))
    c[2].metric("🟠 Estoque baixo", estados.count(BAIXO), help=f"Até {limite} unidade(s).")
    c[3].metric("♾️ Ilimitados", estados.count(ILIMITADO))
    c[4].metric("Unidades em estoque", unidades)


def painel_leitura(est, limite, rotulos):
    """Métricas + tabela de situação. Pode rodar sozinho a cada N segundos (fragmento)."""
    try:
        itens = est.ler(rotulos)
    except EstoqueIndisponivel as e:
        st.error(str(e))
        return
    metricas(itens, limite)
    linhas = []
    for i in sorted(itens, key=lambda i: (ORDEM[situacao(i, limite)], i["quantidade"], i["produto"].casefold())):
        linha = {"Situação": situacao(i, limite), "Item": i["chave"], "Produto": i["produto"]}
        if est.modo == MODO_ESP:
            linha["Variação"] = i["variacao"]
        linha["Preço (R$)"] = i["preco"]
        linha["Quantidade"] = None if i["ilimitado"] else i["quantidade"]
        linhas.append(linha)
    st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True,
                 column_config={"Preço (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                                "Quantidade": st.column_config.NumberColumn(format="%d")})
    st.caption(f"Atualizado às {datetime.now():%H:%M:%S}")


def painel_edicao(est, slug, rotulos):
    ver = st.session_state.setdefault("ver", 0)      # muda ao salvar/recarregar: a tela recomeça do banco
    chave_orig = f"orig_{slug}_{ver}"
    if chave_orig not in st.session_state:
        try:
            st.session_state[chave_orig] = est.ler(rotulos)
        except EstoqueIndisponivel as e:
            st.error(str(e))
            return
    orig = st.session_state[chave_orig]
    st.caption("Mude **Quantidade**, **Ilimitado** ou **Ativo** e clique em Salvar. Esta tela não se atualiza sozinha "
               "(para não apagar o que você digitou): se o bot vender um item enquanto você edita, esse item vira "
               "conflito e **não é sobrescrito**.")
    colunas = []
    for i in orig:
        linha = {"Item": i["chave"], "Produto": i["produto"]}
        if est.modo == MODO_ESP:
            linha["Variação"] = i["variacao"]
        linha.update({"Preço (R$)": i["preco"], "Quantidade": i["quantidade"],
                      "Ilimitado": i["ilimitado"], "Ativo": i["ativo"]})
        colunas.append(linha)
    df = pd.DataFrame(colunas)
    so_leitura = [c for c in ("Item", "Produto", "Variação", "Preço (R$)") if c in df.columns]
    editado = st.data_editor(
        df, hide_index=True, use_container_width=True, disabled=so_leitura, key=f"editor_{slug}_{ver}",
        column_config={"Preço (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                       "Quantidade": st.column_config.NumberColumn(min_value=0, step=1, format="%d", required=True),
                       "Ilimitado": st.column_config.CheckboxColumn(help="Estoque infinito: a quantidade é ignorada."),
                       "Ativo": st.column_config.CheckboxColumn(help="Desmarcado = o bot não vende este item.")})
    mudancas = []
    for idx, it in enumerate(orig):
        linha = editado.iloc[idx]
        qtd = linha["Quantidade"]
        qtd = 0 if pd.isna(qtd) else int(qtd)
        ilim, ativo = bool(linha["Ilimitado"]), bool(linha["Ativo"])
        depois = (0 if ilim else qtd, ilim, ativo)
        antes = (it["quantidade"], it["ilimitado"], it["ativo"])
        if depois != antes:
            mudancas.append({"chave": it["chave"], "antes": antes, "depois": depois})
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        if st.button(f"💾 Salvar {len(mudancas)} alteração(ões)" if mudancas else "💾 Salvar",
                     type="primary", disabled=not mudancas, use_container_width=True):
            try:
                aplicadas, conflitos = est.salvar_edicoes(mudancas)
            except EstoqueIndisponivel as e:
                st.error(str(e))
                return
            if conflitos:
                st.session_state["msg_estoque"] = ("warning",
                    f"{len(aplicadas)} item(ns) salvo(s). **{len(conflitos)} mudaram enquanto você editava** "
                    f"(vendas do bot?) e não foram alterados: {', '.join(conflitos)}. Veja os valores atuais e edite de novo.")
            else:
                st.session_state["msg_estoque"] = ("success", f"{len(aplicadas)} item(ns) salvo(s).")
            st.session_state["ver"] = ver + 1
            st.rerun()
    with c2:
        if st.button("🔄 Recarregar do banco", use_container_width=True, help="Descarta o que você mudou e não salvou."):
            st.session_state["ver"] = ver + 1
            st.rerun()


def painel_historico(est):
    eventos = est.historico(200)
    if not eventos:
        st.info("Nada alterado por aqui ainda.")
        return
    st.dataframe(pd.DataFrame([{"Quando": e.get("quando", "").replace("T", " "), "Ação": e.get("acao", ""),
                                "Detalhe": descrever_evento(e)} for e in eventos]),
                 hide_index=True, use_container_width=True)


def painel_emergencia(est, itens):
    """Botão de emergência, sempre no topo. Zerar guarda o estado anterior: dá para desfazer."""
    with st.container(border=True):
        st.markdown("#### 🚨 Emergência")
        if st.session_state.get("zerar_pendente"):
            incluir = st.checkbox("Incluir itens de estoque ilimitado (passam a ter 0)", value=True, key="zerar_incluir")
            afetados = [i for i in itens if i["quantidade"] > 0 or (incluir and i["ilimitado"])]
            unidades = sum(i["quantidade"] for i in afetados if not i["ilimitado"])
            st.error(f"Isso vai zerar **{len(afetados)} item(ns)** ({unidades} unidade(s)) de «{est.loja.nome}». "
                     "O bot para de vender na hora. Logo depois dá para **desfazer** pelo botão «Desfazer».")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ CONFIRMAR: zerar tudo agora", type="primary", use_container_width=True):
                    try:
                        r = est.zerar(incluir_ilimitados=incluir)
                    except EstoqueIndisponivel as e:
                        st.error(str(e))
                        return
                    st.session_state["zerar_pendente"] = False
                    st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                    st.session_state["msg_estoque"] = (
                        "success", f"Estoque zerado: {r['itens']} item(ns), {r['unidades']} unidade(s). "
                                   "Para voltar atrás, use «Desfazer o último zerar».")
                    st.rerun()
            with c2:
                if st.button("Cancelar", use_container_width=True):
                    st.session_state["zerar_pendente"] = False
                    st.rerun()
            return

        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("🚨 ZERAR TODO O ESTOQUE", type="primary", use_container_width=True,
                         disabled=not any(i["quantidade"] > 0 or i["ilimitado"] for i in itens)):
                st.session_state["zerar_pendente"] = True
                st.rerun()
        with c2:
            pendente = est.zerar_pendente()
            if pendente:
                _, dados = pendente
                st.caption(f"Último «zerar»: {dados['criado_em'].replace('T', ' ')} ({len(dados['itens'])} item(ns)).")
                if st.button("↩️ Desfazer o último zerar"):
                    try:
                        r = est.desfazer_zerar()
                    except EstoqueIndisponivel as e:
                        st.error(str(e))
                        return
                    texto = f"Estoque restaurado: {r['restaurados']} item(ns)."
                    if r["conflitos"]:
                        texto += (f" {len(r['conflitos'])} já tinham sido mexidos depois do zerar e ficaram como estão: "
                                  f"{', '.join(r['conflitos'])}.")
                    st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                    st.session_state["msg_estoque"] = ("warning" if r["conflitos"] else "success", texto)
                    st.rerun()

        with st.expander("Zerar só alguns produtos (ex.: uma fornada estragou)"):
            produtos = {}
            for i in itens:
                produtos.setdefault(i["produto_id"], i["produto"])
            escolhidos = st.multiselect("Produtos", list(produtos), key="zerar_produtos",
                                        format_func=lambda p: f"{p} — {produtos[p]}")
            if st.button("Zerar só estes", disabled=not escolhidos):
                try:
                    r = est.zerar(produto_ids=escolhidos)
                except EstoqueIndisponivel as e:
                    st.error(str(e))
                    return
                st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                st.session_state["msg_estoque"] = (
                    "success", f"{r['itens']} item(ns) zerado(s) ({r['unidades']} unidade(s)). Dá para desfazer.")
                st.rerun()


def main():
    st.set_page_config(page_title="Monitor de estoque", page_icon="📦", layout="wide")
    st.title("📦 Monitor de estoque")

    lojas = listar_lojas()
    if not lojas:
        st.info("Ainda não há nenhuma loja. Crie uma na interface do catálogo (interface_catalogo.py).")
        st.stop()
    por_slug = {l.slug: l for l in lojas}
    if st.session_state.get("loja_estoque") not in por_slug:
        st.session_state["loja_estoque"] = next(iter(por_slug))

    with st.sidebar:
        st.header("Loja")
        slug = st.selectbox("Loja", list(por_slug), key="loja_estoque", format_func=lambda s: por_slug[s].nome)
        st.header("Monitor")
        limite = st.number_input("Estoque baixo: até (unidades)", min_value=0, value=5, step=1)
        auto = st.checkbox("Atualizar sozinho", value=True)
        intervalo = st.selectbox("A cada", [5, 10, 30, 60], index=1, format_func=lambda s: f"{s} segundos",
                                 disabled=not auto)
        if st.button("🔄 Atualizar agora"):
            st.rerun()
    loja = por_slug[slug]

    modo = loja.modo
    if modo is None:
        st.warning("Esta loja ainda não tem modo de estoque. Escolha o modo na interface do catálogo.")
        st.stop()
    rotulos = None
    if modo == MODO_ESP:
        try:
            ce.carregar(loja.arquivo_atributos)
            rotulos = ce.ROTULOS
        except (OSError, ValueError):
            pass

    est = EstoqueLoja(loja, modo)
    if not est.existe():
        st.warning(f"A loja «{loja.nome}» ainda não tem banco de estoque. Ele é criado quando você salva o "
                   "primeiro produto na interface do catálogo.")
        st.stop()
    try:
        itens = est.ler(rotulos)
    except EstoqueIndisponivel as e:
        st.error(str(e))
        st.stop()

    msg = st.session_state.pop("msg_estoque", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    painel_emergencia(est, itens)

    visao = st.radio("Tela", VISOES, horizontal=True, label_visibility="collapsed", key="visao_estoque")
    if visao == VISOES[0]:
        if auto:
            try:
                st.fragment(run_every=intervalo)(painel_leitura)(est, limite, rotulos)
            except (AttributeError, TypeError):   # Streamlit antigo, sem atualização automática de trecho
                painel_leitura(est, limite, rotulos)
                st.caption("A atualização automática precisa do Streamlit 1.37 ou mais novo; use «Atualizar agora».")
        else:
            painel_leitura(est, limite, rotulos)
    elif visao == VISOES[1]:
        metricas(itens, limite)
        painel_edicao(est, slug, rotulos)
    else:
        painel_historico(est)


if __name__ == "__main__":
    main()
