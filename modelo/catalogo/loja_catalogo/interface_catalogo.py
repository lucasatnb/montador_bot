"""
interface_catalogo.py  --  Interface de cadastro do catálogo (Streamlit), uma LOJA por vez.

Fluxo:   interface pega as infos  ->  gera a pasta de fotos  ->  grava direto nos bancos

Cada loja tem catálogo, fotos, estoque e banco PRÓPRIOS (lojas/<loja>/...). Nada é compartilhado
entre lojas. Para começar do zero, crie uma "Nova loja" na barra lateral.

Dentro de uma loja:
  - "Adicionar novo produto": o ID é gerado sozinho (A000 a Z999); você digita nome, preço, categoria, descrição, estoque e escolhe as fotos;
  - "Editar produto existente": escolhe o produto na lista e ajusta o que quiser.
Ao clicar em "Salvar produto" o programa (SEM gerar planilhas):
  1. cria a pasta imagens/<ID>/ da loja e salva as fotos (01.jpg, 02.png, ...); no modo especializado há também
     fotos por variação em imagens/<ID>/<tipo>/<opção>/ (ex.: imagens/A000/cor/Verde/): você escolhe um atributo
     principal (todas as opções dele têm fotos) e, nos outros atributos, só 1 ou 2 opções com fotos;
  2. grava o produto no catalogo.db da loja (é a fonte do catálogo);
  3. grava o estoque direto no banco que o bot usa, conforme o MODO da loja (escolhido uma vez):
        - simples       -> produtos.db
        - especializado -> produtos_especializados.db
     No especializado, o preço de cada SKU = preço base + acréscimos das opções dos atributos marcados
     como "afeta o preço" (ficam em acrescimos.json).
     A quantidade só é gravada para item NOVO; depois disso o estoque é do bot (vendas) e do
     gerenciador de estoque (interface_estoque.py).

Categorias e atributos (só de tela): a categoria do produto é criada na barra lateral e é ela que "tem" os atributos
(tamanho, cor...). Ao escolher a categoria do item, ele só vê os atributos dela. Por dentro o vocabulário continua
UM só por loja (atributos_loja): atributo com o mesmo nome em duas categorias é o MESMO, nunca é duplicado.
O vínculo categoria -> atributos fica em categorias_ui.json (ao lado do arquivo de atributos); só esta tela lê.

As regras de pasta/catálogo ficam no gerar_pastas.py e as do estoque no banco_loja.py; aqui é só a tela.
Instalar:  pip install streamlit
Rodar:     streamlit run interface_catalogo.py
"""
import json
import shutil
import sqlite3
import unicodedata
from pathlib import Path

import streamlit as st

from variacoes import atributos_loja
from nucleo import banco_loja
from variacoes import constantes_especializado as ce
from nucleo import formato_ids
from variacoes import planilha_especializada as planilha_esp
from variacoes import uso_atributos
from nucleo.gerar_pastas import (
    BASE,
    MODO_ESP,
    MODO_SIMPLES,
    NOMES_MODO,
    ErroDados,
    aprovado,
    acrescimos_do_produto,
    criar_loja,
    fotos_do_sku,
    gerar_db,
    gravar_acrescimos_produto,
    gravar_produto_catalogo,
    ids_em_uso,
    legado_na_raiz,
    ler_catalogo,
    listar_imagens,
    listar_lojas,
    nome_pasta,
    preco_do_sku,
    salvar_imagens,
    zerar_loja,
)

SEM = "— escolha uma categoria —"
ACAO_NOVO = "➕ Adicionar novo produto"
ACAO_EDITAR = "✏️ Editar produto existente"
SEM_OPCAO = "— o arquivo diz qual (Opção: palavras) —"


# ============================ lógica de tela (sem I/O) ========================

def canonica(nova, existentes):
    """Evita 'pizzas' e 'Pizzas' virarem duas categorias: reaproveita a grafia que já existe."""
    nova = " ".join(nova.split())
    for c in existentes:
        if c.casefold() == nova.casefold():
            return c
    return nova


def proximo_pendente(produtos, apos_id):
    """Primeiro produto não aprovado depois de apos_id; se não houver, o primeiro pendente; senão o próprio."""
    ids = [p["id"] for p in produtos]
    inicio = ids.index(apos_id) + 1 if apos_id in ids else 0
    for p in produtos[inicio:] + produtos[:inicio]:
        if not aprovado(p):
            return p["id"]
    return apos_id if apos_id in ids else ids[0]


# ================================ interface ===================================

def grade(itens, desenhar, colunas=4):
    for i in range(0, len(itens), colunas):
        for col, item in zip(st.columns(colunas), itens[i:i + colunas]):
            with col:
                desenhar(item)


def bloco_fotos(loja, id_produto, tipo, opcao, chave):
    """Uploader + previews de UM grupo de fotos: as gerais do item (tipo=None) ou as de uma opção (ex.: cor/Verde).
    Devolve {tipo, opcao, arquivos (novos), remover (já salvos marcados)}."""
    if tipo is None:
        pasta = loja.pasta_produto(id_produto) if id_produto else None
        caminho = f"imagens/{nome_pasta(id_produto) or '<ID>'}/" if id_produto else "imagens/<ID>/"
        ajuda = "Fotos do item como um todo. Aparecem em todas as variações. A primeira é a capa."
    else:
        pasta = loja.pasta_atributo(id_produto, tipo, opcao) if id_produto else None
        caminho = f"imagens/{nome_pasta(id_produto) or '<ID>'}/{nome_pasta(tipo)}/{nome_pasta(opcao)}/"
        ajuda = f"Só as variações com {ce.ROTULOS.get(tipo, tipo)} = {opcao} usam estas fotos."
    st.caption(f"{ajuda}  Pasta: `{caminho}`")
    arquivos = st.file_uploader(
        "Escolher fotos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"fotos_{chave}",
    )
    if arquivos:
        st.markdown("**Fotos novas (ainda não salvas)**")
        grade(arquivos, lambda a: st.image(a.getvalue(), caption=a.name))
    remover = []
    existentes = listar_imagens(pasta)
    st.markdown("**Fotos já salvas na pasta**")
    if existentes:
        def desenha(f):
            st.image(str(f), caption=f.name)
            if st.checkbox("Remover", key=f"rm_{chave}_{f.name}"):
                remover.append(f)

        grade(existentes, desenha)
    else:
        st.caption("Nenhuma foto salva ainda.")
    return {"tipo": tipo, "opcao": opcao, "arquivos": arquivos or [], "remover": remover,
            "existentes": len(existentes)}


def tipo_principal_salvo(loja, id_produto, tipos_escolhidos):
    """Tipo de variação que já tem fotos em mais opções (para sugerir o atributo principal ao reabrir um produto)."""
    if not id_produto:
        return None
    melhor, n_melhor = None, 0
    for t, ops in tipos_escolhidos.items():
        n = sum(1 for o in ops if listar_imagens(loja.pasta_atributo(id_produto, t, o)))
        if n > n_melhor:
            melhor, n_melhor = t, n
    return melhor


def limpar_selecoes(loja, opcoes=(), categorias=()):
    """Depois de excluir, tira do formulário do produto as seleções que apontavam para o que sumiu (o multiselect
    quebra se a seleção guardada tem uma opção que já não existe). Só mexe no que foi afetado.
    Roda antes de os campos do produto serem criados (a barra lateral vem primeiro), então pode mexer neles."""
    for chave in list(st.session_state):
        if not isinstance(chave, str):
            continue
        for tipo in categorias:
            if chave.startswith(f"tipo_{tipo}_{loja.slug}_"):
                st.session_state.pop(chave, None)
        for tipo, nome in opcoes:
            if chave.startswith(f"tipo_{tipo}_{loja.slug}_") and nome in (st.session_state.get(chave) or []):
                st.session_state.pop(chave, None)


# ===================== categorias do produto e os atributos de cada uma (só de tela) ====================
# O vocabulário (atributos, opções, códigos, sinônimos) continua UM só por loja, em atributos_loja. O que muda é
# quem enxerga o quê: cada categoria de produto escolhe quais atributos oferece. Atributo com o mesmo nome em
# duas categorias é o mesmo atributo da loja (reaproveitado, nunca criado de novo).

ARQ_CATEGORIAS = "categorias_ui.json"


def _sem_acento(texto):
    base = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in base if not unicodedata.combining(c)).casefold().strip()


def arquivo_categorias(loja):
    return Path(loja.arquivo_atributos).parent / ARQ_CATEGORIAS


def ler_categorias_ui(loja):
    """{categoria: [chaves dos atributos que ela oferece]}, criadas na barra lateral. Só a tela lê isto."""
    try:
        bruto = json.loads(arquivo_categorias(loja).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(bruto, dict):
        return {}
    return {str(c): [str(t) for t in ts] for c, ts in bruto.items() if isinstance(ts, list)}


def gravar_categorias_ui(loja, vinculos):
    arq = arquivo_categorias(loja)
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(vinculos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(arq)


def arquivar_categorias_ui(loja, destino):
    """Ao zerar a loja, leva junto o vínculo categoria -> atributos (nada é apagado)."""
    arq = arquivo_categorias(loja)
    if arq.exists():
        try:
            shutil.move(str(arq), str(Path(destino) / arq.name))
        except OSError:
            pass


def todas_categorias(produtos, vinculos):
    """Categorias dos produtos + as criadas na lateral que ainda não têm produto, sem repetir por maiúscula/minúscula."""
    vistas = []
    nomes = [str(x["categoria"]).strip() for x in produtos if x["categoria"] and str(x["categoria"]).strip()]
    for c in nomes + list(vinculos):
        c = canonica(c, vistas)
        if c and c not in vistas:
            vistas.append(c)
    return sorted(vistas, key=str.casefold)


def achar_vinculo(vinculos, categoria):
    """Atributos da categoria, ou None se ela nunca foi configurada na lateral (lojas que já existiam)."""
    for c, ts in vinculos.items():
        if c.casefold() == categoria.casefold():
            return ts
    return None


def tipos_da_categoria(vinculos, categoria, todos_tipos):
    ligados = achar_vinculo(vinculos, categoria)
    if ligados is None:        # nunca configurada: oferece tudo, como era antes
        return list(todos_tipos)
    return [t for t in todos_tipos if t in ligados]


def com_vinculo(vinculos, categoria, chaves):
    novo = {c: ts for c, ts in vinculos.items() if c.casefold() != categoria.casefold()}
    novo[categoria] = list(dict.fromkeys(chaves))
    return novo


def achar_tipo_por_rotulo(dados, rotulo):
    """Chave do atributo da loja com este nome (sem ligar para maiúscula/acento), ou None. Evita atributo repetido."""
    alvo = _sem_acento(rotulo)
    for chave, t in dados["tipos"].items():
        if alvo in (_sem_acento(t["rotulo"]), _sem_acento(chave)):
            return chave
    return None


def painel_categorias(loja, modo, produtos):
    """Barra lateral: cria categorias de produto e, no modo especializado, escolhe os atributos de cada uma."""
    vinculos = ler_categorias_ui(loja)
    aviso = st.session_state.pop("msg_categoria", None)
    if aviso:
        st.success(aviso)

    with st.form(f"nova_cat_produto_{loja.slug}", clear_on_submit=True):
        nome = st.text_input("Nova categoria", placeholder="Ex.: Pizzas")
        criar = st.form_submit_button("Criar categoria")
    if criar:
        existentes = todas_categorias(produtos, vinculos)
        nome = canonica(nome, existentes)
        if not nome:
            st.warning("Digite o nome da categoria.")
        elif nome in existentes:
            st.info(f"A categoria «{nome}» já existe.")
        else:
            try:
                gravar_categorias_ui(loja, com_vinculo(vinculos, nome, []))
            except OSError as e:
                st.error(f"Não consegui criar a categoria: {e}")
            else:
                st.session_state[f"cat_lateral_{loja.slug}"] = nome
                st.session_state["msg_categoria"] = f"Categoria «{nome}» criada."
                st.rerun()

    categorias = todas_categorias(produtos, vinculos)
    if modo != MODO_ESP:
        st.caption("As categorias organizam os produtos desta loja. Atributos (tamanho, cor...) existem no modo especializado.")
        return
    if not categorias:
        st.caption("Crie a primeira categoria acima para definir os atributos dela.")
        return

    chave_sel = f"cat_lateral_{loja.slug}"
    if st.session_state.get(chave_sel) not in categorias:
        st.session_state.pop(chave_sel, None)
    st.divider()
    categoria = st.selectbox("Atributos da categoria", categorias, key=chave_sel)
    painel_atributos(loja, categoria, vinculos, categorias)


def painel_atributos(loja, categoria, vinculos, categorias):
    """Atributos/opções/sinônimos da CATEGORIA escolhida. Por dentro é o vocabulário único da loja: dá para acrescentar à
    vontade e excluir o que nenhum produto usa; o que já está em uso (🔒) não sai nem muda (regra em atributos_loja.salvar;
    o levantamento do que está em uso, em uso_atributos.levantar)."""
    try:
        dados = atributos_loja.ler(loja.arquivo_atributos)
    except atributos_loja.VocabularioInvalido as e:
        st.error(str(e))
        return

    try:       # o que algum produto já usa; None = não consegui conferir, e então nada pode ser excluído
        uso = uso_atributos.levantar(loja, dados)
    except uso_atributos.UsoIndeterminado as e:
        uso = None
        st.warning(f"Não consegui conferir o que já está em uso, então a exclusão fica desligada por enquanto. {e}")

    todos = list(dados["tipos"])
    tipos_cat = tipos_da_categoria(vinculos, categoria, todos)
    visiveis = {c: dados["tipos"][c] for c in tipos_cat}
    rotulo_de = lambda c: dados["tipos"][c]["rotulo"]

    def gravar(novo, depois=None):
        try:
            atributos_loja.salvar(loja.arquivo_atributos, novo, uso)
        except atributos_loja.VocabularioInvalido as e:
            st.error(str(e))
            return False
        if depois:
            depois()
        st.rerun()

    # ---- quais atributos esta categoria oferece (e criar um novo, sem repetir um que a loja já tem) ----
    if achar_vinculo(vinculos, categoria) is None:
        st.caption("Esta categoria ainda não foi configurada e por isso oferece todos os atributos da loja. "
                   "Escolha abaixo os que ela deve ter.")
    versao = st.session_state.setdefault("v_atributos_cat", 0)    # muda ao salvar e refaz o campo com o que foi gravado
    with st.form(f"atributos_cat_{loja.slug}"):
        escolhidos = st.multiselect(
            "Atributos desta categoria", todos, default=tipos_cat, format_func=rotulo_de,
            key=f"attr_cat_{loja.slug}_{categoria}_{versao}",
            help="Só estes aparecem ao cadastrar um item desta categoria. Retirar daqui não apaga nada.")
        novo_rotulo = st.text_input(
            "Criar atributo novo (opcional)", placeholder="Ex.: Tecido",
            help="Se a loja já tiver um atributo com esse nome, ele é reaproveitado (não cria outro igual).")
        salvar_attr = st.form_submit_button("Salvar atributos da categoria")
    if salvar_attr:
        chaves = list(escolhidos)
        rotulo_limpo = " ".join(novo_rotulo.split())
        try:
            if rotulo_limpo:
                existente = achar_tipo_por_rotulo(dados, rotulo_limpo)
                if existente is None:
                    antes = set(dados["tipos"])
                    novo_dados = atributos_loja.com_tipo(dados, rotulo_limpo)
                    chaves += [c for c in novo_dados["tipos"] if c not in antes]
                    atributos_loja.salvar(loja.arquivo_atributos, novo_dados, uso)
                else:
                    chaves.append(existente)       # já existe na loja: só liga à categoria
            gravar_categorias_ui(loja, com_vinculo(vinculos, categoria, chaves))
        except atributos_loja.VocabularioInvalido as e:
            st.error(str(e))
        except OSError as e:
            st.error(f"Não consegui gravar: {e}")
        else:
            st.session_state["v_atributos_cat"] = versao + 1
            st.rerun()

    if visiveis:
        for chave, t in visiveis.items():
            em_uso = (uso or {}).get(chave) or {}
            opcoes_txt = ", ".join(f"{n} ({c})" + (" 🔒" if n in em_uso else "") for n, c in t["opcoes"].items())
            st.markdown(f"**{t['rotulo']}**: " + (opcoes_txt or "_sem opções ainda_"))
    else:
        st.caption("Esta categoria ainda não tem atributos. Escolha ou crie acima, ou use os atributos padrão.")
    st.caption("Nomes e códigos não mudam depois de criados. 🔒 = já usado por algum produto (planilha, estoque ou "
               "fotos): esse não pode ser excluído. O que ninguém usou ainda pode ser excluído lá embaixo. "
               "Atributo com o mesmo nome em duas categorias é o mesmo (as opções valem para as duas).")

    if st.button("Adicionar atributos padrão", help="Tamanho, numeração, cor e borda, com códigos prontos. Só soma o que "
                                                    "ainda não existe na loja e liga à categoria os que forem novos."):
        antes = set(dados["tipos"])
        novo = atributos_loja.com_padrao(dados)
        novos = [c for c in novo["tipos"] if c not in antes]
        gravar(novo, lambda: gravar_categorias_ui(loja, com_vinculo(vinculos, categoria, tipos_cat + novos)))

    if visiveis:
        with st.form(f"nova_opcao_{loja.slug}", clear_on_submit=True):
            tipo = st.selectbox("Atributo", list(visiveis), format_func=rotulo_de)
            nome = st.text_input("Nova opção", placeholder="Ex.: Algodão")
            codigo = st.text_input("Código (opcional)", placeholder="Ex.: ALG. Vazio = gerado sozinho",
                                   help="Entra no SKU (ex.: A000_ALG). Letras maiúsculas e números, sem repetir no atributo.")
            if st.form_submit_button("Adicionar opção"):
                try:
                    gravar(atributos_loja.com_opcao(dados, tipo, nome, codigo))
                except atributos_loja.VocabularioInvalido as e:
                    st.error(str(e))

        opcoes_todas = [o for t in visiveis.values() for o in t["opcoes"]]
        if opcoes_todas:
            with st.form(f"novo_sinonimo_{loja.slug}", clear_on_submit=True):
                texto = st.text_input("Sinônimo (como o cliente escreve)", placeholder="Ex.: preta")
                oficial = st.selectbox("Significa a opção", opcoes_todas)
                if st.form_submit_button("Adicionar sinônimo"):
                    try:
                        gravar(atributos_loja.com_sinonimo(dados, texto, oficial))
                    except atributos_loja.VocabularioInvalido as e:
                        st.error(str(e))

            # ---- vários sinônimos de uma vez, de um .txt ----
            st.markdown("**Importar sinônimos de um .txt**")
            st.caption("Palavras separadas por vírgula. Ex.: `preta, negra, escura`. Para várias opções num arquivo só, "
                       "uma por linha: `Preto: preta, negra` e `Branco: branca, clara`. Antes de gravar, você vê o que vai entrar.")
            chave_envio = f"sinonimos_txt_{loja.slug}"
            n_envio = st.session_state.setdefault(chave_envio, 0)     # muda depois de importar e limpa o campo
            arquivo = st.file_uploader("Arquivo .txt", type=["txt"], key=f"sin_arquivo_{loja.slug}_{n_envio}")
            escolha_txt = st.selectbox("Opção das palavras sem «Opção:» na frente", [SEM_OPCAO] + list(dict.fromkeys(opcoes_todas)),
                                       key=f"sin_opcao_{loja.slug}")
            if arquivo is not None:
                novo_txt, rel = atributos_loja.com_sinonimos_do_texto(
                    dados, atributos_loja.decodificar_texto(arquivo.getvalue()),
                    None if escolha_txt == SEM_OPCAO else escolha_txt)
                if rel["novos"]:
                    st.success(f"{len(rel['novos'])} sinônimo(s) novo(s): "
                               + ", ".join(f"{s} → {o}" for s, o in rel["novos"][:30])
                               + (" …" if len(rel["novos"]) > 30 else ""))
                if rel["repetidos"]:
                    st.caption(f"{len(rel['repetidos'])} já existia(m) e foi(ram) ignorado(s).")
                for problema in rel["problemas"][:10]:
                    st.warning(problema)
                if len(rel["problemas"]) > 10:
                    st.warning(f"… e mais {len(rel['problemas']) - 10} problema(s).")
                if not rel["novos"] and not rel["problemas"]:
                    st.info("Não há nada novo neste arquivo.")

                def proximo_envio():
                    st.session_state[chave_envio] = n_envio + 1

                if rel["novos"] and st.button(f"Importar {len(rel['novos'])} sinônimo(s)", type="primary",
                                              key=f"sin_importar_{loja.slug}"):
                    gravar(novo_txt, proximo_envio)

    # ---- excluir o que nenhum produto usa ----
    if dados["tipos"] and uso is not None:
        opcoes_da_categoria = {n for t in visiveis.values() for n in t["opcoes"]}
        op_livres = [f"{c}|{n}" for c, n in atributos_loja.opcoes_removiveis(dados, uso) if c in visiveis]   # nomes não têm '|'
        sin_livres = [s for s in atributos_loja.sinonimos_removiveis(dados, uso)
                      if dados["sinonimos"].get(s) in opcoes_da_categoria]
        # atributo inteiro só sai se nenhuma categoria o oferece mais (senão sumiria das outras)
        em_alguma = {t for c in categorias for t in tipos_da_categoria(vinculos, c, todos)}
        cat_livres = [c for c in atributos_loja.tipos_removiveis(dados, uso) if c not in em_alguma]
        if op_livres or cat_livres or sin_livres:
            with st.form(f"excluir_{loja.slug}", clear_on_submit=True):
                st.markdown("**Excluir o que ainda não foi usado**")
                sel_sin = st.multiselect("Sinônimos", sin_livres, key=f"exc_sin_{loja.slug}",
                                         format_func=lambda s: f"{s} → {dados['sinonimos'][s]}")
                sel_op = st.multiselect("Opções", op_livres, key=f"exc_op_{loja.slug}",
                                        format_func=lambda x: f"{dados['tipos'][x.split('|', 1)[0]]['rotulo']} › {x.split('|', 1)[1]}",
                                        help="Leva junto os sinônimos que só existiam por causa dela.")
                sel_cat = st.multiselect("Atributos sem categoria", cat_livres, key=f"exc_cat_{loja.slug}",
                                         format_func=rotulo_de,
                                         help="Atributos que nenhuma categoria oferece e nenhum produto usa. "
                                              "Leva junto as opções e os sinônimos dele.")
                if st.form_submit_button("Excluir selecionados"):
                    if not (sel_sin or sel_op or sel_cat):
                        st.warning("Escolha o que excluir.")
                    else:
                        escolhidas = [tuple(x.split("|", 1)) for x in sel_op]
                        try:
                            novo = atributos_loja.com_sinonimos_removidos(dados, sel_sin, uso)
                            for c, n in escolhidas:
                                novo = atributos_loja.com_opcao_removida(novo, c, n, uso)
                            for c in sel_cat:
                                novo = atributos_loja.com_tipo_removido(novo, c, uso)
                        except atributos_loja.VocabularioInvalido as e:
                            st.error(str(e))
                        else:
                            gravar(novo, lambda: limpar_selecoes(loja, escolhidas, sel_cat))
        else:
            st.caption("Nada para excluir: tudo o que existe aqui já está em uso (🔒).")


def form_nova_loja(prefixo):
    """Formulário de loja nova (começar do zero). Nunca mexe em lojas existentes."""
    vl = st.session_state.setdefault("vl", 0)       # muda a cada loja criada e limpa o formulário
    nome = st.text_input("Nome da loja", key=f"{prefixo}_nome_{vl}", placeholder="Ex.: Pizzaria do Zé")
    modo = st.radio(
        "Modo de estoque", [MODO_SIMPLES, MODO_ESP], format_func=NOMES_MODO.get, key=f"{prefixo}_modo_{vl}",
        help="Vale para todos os produtos da loja. Simples: preço e quantidade. "
             "Especializado: variações (tamanho, sabor...) com SKU, preço e estoque por combinação.",
    )
    copiar = False
    if legado_na_raiz():
        copiar = st.checkbox(
            "Copiar para esta loja os arquivos antigos (planilhas, fotos e bancos soltos na pasta do programa)",
            key=f"{prefixo}_legado_{vl}",
            help="É uma cópia: os arquivos originais continuam onde estão.",
        )
    if st.button("Criar loja", type="primary", key=f"{prefixo}_criar_{vl}"):
        try:
            loja = criar_loja(nome, modo, copiar_legado=copiar)
        except ErroDados as e:
            st.error(str(e))
            return
        except OSError as e:
            st.error(f"Não consegui criar a loja: {e}")
            return
        st.session_state["loja_ir_para"] = loja.slug
        st.session_state["vl"] = vl + 1
        st.rerun()


def tela_escolha_modo(loja):
    st.subheader(f"Loja «{loja.nome}»: escolha o modo de estoque")
    st.write("Essa escolha vale para **todos** os produtos desta loja.")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Simples**")
        st.caption("Cada produto tem um preço e uma quantidade. Banco: `produtos.db`.")
        if st.button("Usar modo simples", use_container_width=True):
            loja.definir_modo(MODO_SIMPLES)
            st.rerun()
    with col_b:
        st.markdown("**Especializado**")
        st.caption("Produtos com variações (tamanho, sabor...), cada combinação com SKU, preço e estoque. "
                   "Banco: `produtos_especializados.db`.")
        if st.button("Usar modo especializado", use_container_width=True):
            loja.definir_modo(MODO_ESP)
            st.rerun()


def main():
    st.set_page_config(page_title="Cadastro do catálogo", page_icon="🍕", layout="wide")
    st.title("Cadastro do catálogo")

    # ---------------------------------------------------------------- loja
    lojas = listar_lojas()
    if not lojas:
        st.subheader("Vamos começar: crie a primeira loja")
        st.caption("Cada loja tem catálogo, fotos e estoque próprios, sem misturar com as outras.")
        form_nova_loja("main")
        st.stop()

    por_slug = {l.slug: l for l in lojas}
    slugs = list(por_slug)
    if "loja_ir_para" in st.session_state:
        st.session_state["loja"] = st.session_state.pop("loja_ir_para")
    if st.session_state.get("loja") not in slugs:
        st.session_state["loja"] = slugs[0]

    with st.sidebar:
        st.header("Loja")
        slug = st.selectbox("Loja", slugs, key="loja", format_func=lambda s: por_slug[s].nome)
        with st.expander("➕ Nova loja (começar do zero)"):
            form_nova_loja("side")
    loja = por_slug[slug]

    if st.session_state.get("_loja_anterior") != slug:    # trocou de loja: nada do produto anterior vale
        for k in ("produto", "acao", "msg"):
            st.session_state.pop(k, None)
        st.session_state["_loja_anterior"] = slug

    modo = loja.modo
    if modo is None:
        tela_escolha_modo(loja)
        st.stop()

    if modo == MODO_ESP:      # o vocabulário (categorias, opções, códigos) é da LOJA, não do programa
        try:
            ce.carregar(loja.arquivo_atributos)
        except (OSError, ValueError) as e:
            st.error(f"Não consegui ler os atributos da loja: {e}")
            st.stop()

    # ------------------------------------------------------------ catálogo
    try:
        produtos = ler_catalogo(loja)
    except FileNotFoundError:
        produtos = []          # loja nova: o catalogo.db é criado ao salvar o primeiro produto
    except PermissionError:
        st.error("Não consegui abrir o catalogo.db. Ele está aberto em outro programa? Feche e recarregue a página.")
        st.stop()
    except ValueError as e:
        st.error(str(e))
        st.stop()

    ids = [p["id"] for p in produtos]
    por_id = {p["id"]: p for p in produtos}

    # estado: trocas pós-salvamento são feitas aqui, antes de os widgets serem criados
    if "ir_para" in st.session_state:
        st.session_state["produto"] = st.session_state.pop("ir_para")
        st.session_state["acao"] = ACAO_EDITAR
    opcoes_acao = [ACAO_NOVO, ACAO_EDITAR] if produtos else [ACAO_NOVO]
    if st.session_state.get("acao") not in opcoes_acao:
        st.session_state["acao"] = ACAO_EDITAR if produtos else ACAO_NOVO
    if produtos and st.session_state.get("produto") not in ids:
        st.session_state["produto"] = proximo_pendente(produtos, None)
    v = st.session_state.setdefault("v", 0)  # muda a cada salvamento e limpa os campos
    msg = st.session_state.pop("msg", None)

    n_aprovados = sum(aprovado(p) for p in produtos)
    with st.sidebar:
        st.divider()
        st.header("Progresso")
        if produtos:
            st.progress(n_aprovados / len(produtos))
            st.write(f"{n_aprovados} de {len(produtos)} produtos aprovados")
        else:
            st.write("Nenhum produto nesta loja ainda.")
        if st.button("Regerar catalogo.db", disabled=not produtos,
                     help="Relê as fotos das pastas e os acréscimos e refaz as tabelas de fotos do catalogo.db."):
            try:
                gerar_db(loja, produtos)
                st.success("catalogo.db regerado.")
            except (PermissionError, sqlite3.OperationalError):
                st.error("Não consegui gravar o catalogo.db. Ele está aberto em outro programa?")

        st.divider()
        st.header("Modo desta loja")
        st.write(f"**{NOMES_MODO[modo]}**")
        st.caption(f"Estoque em `{loja.banco_estoque(modo).name}` (vale para todos os produtos).")
        outro = MODO_ESP if modo == MODO_SIMPLES else MODO_SIMPLES
        with st.expander("Trocar modo"):
            st.caption(f"Produtos já salvos continuam em `{loja.banco_estoque(modo).name}`. "
                       f"Para tê-los em `{loja.banco_estoque(outro).name}`, salve cada um de novo depois da troca.")
            if st.button(f"Trocar para {NOMES_MODO[outro]}"):
                loja.definir_modo(outro)
                st.session_state["v"] = v + 1
                st.rerun()

        with st.expander("🗂️ Categorias e atributos"):
            painel_categorias(loja, modo, produtos)

        with st.expander("🗑️ Zerar esta loja"):
            st.caption("Move catálogo, estoque, fotos e bancos desta loja para a pasta `_arquivo/` dentro dela "
                       "e deixa a loja vazia. Nada é apagado. As outras lojas não são afetadas.")
            confirma = st.text_input(f"Para confirmar, digite o nome da loja ({loja.nome})", key=f"zerar_{loja.slug}_{v}")
            if st.button("Zerar loja", disabled=confirma.strip().casefold() != loja.nome.casefold()):
                try:
                    destino = zerar_loja(loja)
                except PermissionError as e:
                    st.error(str(e))
                else:
                    arquivar_categorias_ui(loja, destino)
                    st.session_state["msg"] = f"Loja zerada. O que havia está em {destino.relative_to(BASE).as_posix()}/"
                    st.session_state["v"] = v + 1
                    st.rerun()

    # ------------------------------------------- adicionar novo x editar
    if produtos:
        acao = st.radio("O que você quer fazer?", opcoes_acao, key="acao", horizontal=True)
    else:
        st.info("Esta loja ainda está vazia. Comece adicionando o primeiro produto.")
        acao = ACAO_NOVO
    novo = acao == ACAO_NOVO

    if novo:
        p = {"id": "", "nome": "", "preco": None, "descricao": "", "categoria": ""}
    else:
        id_atual = st.selectbox(
            "Produto", ids, key="produto",
            format_func=lambda i: f"{'✅' if aprovado(por_id[i]) else '⬜'}  {i} — {por_id[i]['nome']}",
        )
        p = por_id[id_atual]
    kp = "novo" if novo else p["id"]

    def k(nome_campo):          # chave única por loja + produto + versão (campos limpam depois de salvar)
        return f"{nome_campo}_{loja.slug}_{kp}_{v}"

    if msg:
        st.success(msg)

    # ---- dados básicos ----
    if novo:
        st.subheader("Novo produto")
        try:   # o ID é sempre automático: primeiro livre entre A000 e Z999
            id_produto = formato_ids.proximo_id(ids_em_uso(loja, ids))
        except formato_ids.FormatoInvalido as e:
            st.error(str(e))
            st.stop()
        st.text_input("ID do produto (automático)", value=id_produto, disabled=True, key=k("id"),
                      help="Gerado sozinho, de A000 a Z999. Vira o nome da pasta de fotos (imagens/<ID>/) e "
                           "o começo do SKU no modo especializado.")
    else:
        st.subheader(f"{p['id']} — {p['nome']}")
        id_produto = p["id"]

    col_nome, col_preco = st.columns([3, 1])
    with col_nome:
        nome = st.text_input("Nome", value=p["nome"], key=k("nome"))
    with col_preco:
        preco_catalogo = st.number_input(
            "Preço base (R$)" if modo == MODO_ESP else "Preço (R$)",
            min_value=0.0, value=float(planilha_esp.preco_numerico(p["preco"])),
            step=0.5, format="%.2f", key=k("preco"),
            help=("Preço sem acréscimos. Cada variação soma os acréscimos dos atributos marcados "
                  "como \"afeta o preço\" (veja em Estoque)." if modo == MODO_ESP else None),
        )

    vinculos = ler_categorias_ui(loja)
    categorias = todas_categorias(produtos, vinculos)
    opcoes = [SEM] + categorias
    atual = canonica(str(p["categoria"] or "").strip(), categorias)
    escolha = st.selectbox(
        "Categoria", opcoes,
        index=opcoes.index(atual) if atual in opcoes else 0,
        key=k("cat"),
        help="Lista com as categorias desta loja. Para criar uma nova, use a barra lateral («Categorias e atributos»).",
    )
    if not categorias:
        st.info("Esta loja ainda não tem categorias. Crie a primeira na barra lateral, em «Categorias e atributos».")
    categoria = "" if escolha == SEM else escolha

    descricao = st.text_area("Descrição", value=str(p["descricao"] or ""), height=120, key=k("desc"))

    # ---- estoque: o formulário depende do MODO da loja (fixo), nunca do produto ----
    st.markdown(f"**Estoque** — modo {NOMES_MODO[modo].lower()}")
    linhas_estoque = []
    tipos_escolhidos = {}

    if modo == MODO_SIMPLES:
        salvo = None
        if not novo:
            try:
                salvo = banco_loja.ler_estoque_simples_db(loja.banco_estoque(MODO_SIMPLES), id_produto)
            except (OSError, ValueError, sqlite3.Error) as e:
                st.warning(f"Não consegui ler o estoque no produtos.db ({e}). Os campos começam zerados.")
        no_banco = salvo is not None      # já está no banco: a quantidade é do bot/gerenciador de estoque
        salvo = salvo or {"quantidade": 0, "ilimitado": False}
        ilimitado = st.checkbox("Estoque ilimitado", value=bool(salvo["ilimitado"]),
                                disabled=no_banco, key=k("ilimitado"))
        quantidade = st.number_input(
            "Quantidade atual" if no_banco else "Quantidade inicial", min_value=0, value=int(salvo["quantidade"]),
            step=1, disabled=ilimitado or no_banco, key=k("qtd"),
        )
        if no_banco:
            st.caption("A quantidade de um produto já cadastrado só muda no gerenciador de estoque "
                       "(o bot desconta a cada venda).")
        linhas_estoque = [{"atributos": {}, "preco": preco_catalogo, "quantidade": quantidade,
                           "ilimitado": ilimitado, "imagem": ""}]

    else:  # MODO_ESP
        estado = planilha_esp.estado_inicial_vazio(preco_catalogo)
        if not novo:
            try:
                estado = banco_loja.estado_inicial_esp(loja.banco_estoque(MODO_ESP), id_produto, preco_catalogo)
            except (planilha_esp.PlanilhaInvalida, OSError, sqlite3.Error) as e:
                st.warning(f"Não consegui ler o estoque já salvo ({e}). Os campos começam com o preço do catálogo.")
        no_banco = bool(estado["valores"])   # já tem SKUs no banco: a quantidade é do bot/gerenciador de estoque

        # os atributos que aparecem são os da categoria escolhida; o que o produto já tem salvo continua aparecendo
        tipos_cat = tipos_da_categoria(vinculos, categoria, list(ce.VARIANTES)) if categoria else []
        tipos_visiveis = [t for t in ce.VARIANTES if t in tipos_cat or estado["tipos"].get(t)]
        if not categoria:
            st.info("Escolha a categoria do item: os atributos (tamanho, cor...) aparecem conforme a categoria.")
        elif not tipos_visiveis:
            st.info(f"A categoria «{categoria}» ainda não tem atributos. Crie ou escolha na barra lateral, em "
                    "«Categorias e atributos». Sem eles, o produto vale como uma única opção.")
        st.caption("Marque as variações que o produto tem. Sem nenhuma marcada, o produto vale como uma única opção. "
                   "Se um atributo muda o preço, ligue «Esse atributo afeta o preço» e informe o acréscimo de cada opção.")
        if no_banco:
            st.caption("A quantidade dos itens já cadastrados só muda no gerenciador de estoque (o bot desconta a "
                       "cada venda). Variação nova entra com quantidade 0.")
        acr_salvos = {} if novo else acrescimos_do_produto(loja, id_produto)
        acrescimos = {}      # {tipo: {"afeta": bool, "opcoes": {opção: acréscimo}}}
        for tipo in tipos_visiveis:
            opcoes_tipo = ce.VARIANTES[tipo]
            salvo_t = acr_salvos.get(tipo) or {}
            col_sel, col_afeta = st.columns([3, 1])
            with col_sel:
                selecionadas = st.multiselect(
                    ce.ROTULOS.get(tipo, tipo.capitalize()), opcoes_tipo,
                    default=estado["tipos"].get(tipo, []), key=k(f"tipo_{tipo}"),
                )
            with col_afeta:
                afeta = st.checkbox("Esse atributo afeta o preço", value=bool(salvo_t.get("afeta")),
                                    disabled=not selecionadas, key=k(f"afeta_{tipo}"))
            if not selecionadas:
                continue
            tipos_escolhidos[tipo] = selecionadas
            valores_op = {}
            if afeta:
                cols = st.columns(min(len(selecionadas), 4))
                for i, opcao in enumerate(selecionadas):
                    with cols[i % len(cols)]:
                        valores_op[opcao] = st.number_input(
                            f"{opcao}: acréscimo (R$)", min_value=0.0, step=0.5, format="%.2f",
                            value=float((salvo_t.get("opcoes") or {}).get(opcao, 0.0)),
                            key=k(f"acr_{tipo}_{opcao}"))
            acrescimos[tipo] = {"afeta": bool(afeta), "opcoes": valores_op}

        if tipos_escolhidos and not acr_salvos and not novo:
            salvos = {vv["preco"] for vv in estado["valores"].values() if vv.get("preco") is not None}
            if len(salvos) > 1:
                st.warning("Este produto foi salvo com preços diferentes por variação, antes dos acréscimos existirem. "
                           "Ao salvar, o preço de cada variação passa a ser o preço base + os acréscimos configurados aqui.")

        if tipos_escolhidos:
            try:
                combinacoes = planilha_esp.gerar_combinacoes(tipos_escolhidos)
                # A chave inclui as opções marcadas: mudar as opções recomeça o editor (sem editar a linha errada).
                # O que a pessoa já digitou fica em `edicoes`, por combinação, e reaparece se a combinação voltar.
                # o preço de cada SKU é CALCULADO (base + acréscimos): quando ele muda, a grade recomeça,
                # e a quantidade/ilimitado já digitados voltam pelo `edicoes`
                precos = {planilha_esp.chave_atributos(a): preco_do_sku(preco_catalogo, a, acrescimos)
                          for a in combinacoes}
                assinatura = abs(hash(tuple(sorted(precos.items())))) % 10**6
                chave = planilha_esp.chave_grade(f"{loja.slug}_{kp}", v, tipos_escolhidos) + f"_p{assinatura}"
                edicoes = st.session_state.setdefault(k("edicoes"), {})
                if f"base_{chave}" not in st.session_state:   # os dados de partida não mudam enquanto a chave é a mesma
                    valores = planilha_esp.mesclar_valores(estado["valores"], edicoes)
                    for chave_comb, preco_comb in precos.items():
                        valores.setdefault(chave_comb, {})["preco"] = preco_comb
                    st.session_state[f"base_{chave}"] = planilha_esp.montar_dados_grade(
                        id_produto or "NOVO", combinacoes, valores, preco_catalogo)
                editados = st.data_editor(
                    st.session_state[f"base_{chave}"], hide_index=True, use_container_width=True,
                    disabled=["SKU", "Variação", "preco"] + (["quantidade", "ilimitado"] if no_banco else []),
                    key=chave,
                    column_config={"preco": st.column_config.NumberColumn("Preço (base + acréscimos)", format="%.2f"),
                                   "quantidade": st.column_config.NumberColumn("Quantidade atual" if no_banco else "Quantidade inicial",
                                                                               min_value=0, step=1),
                                   "ilimitado": st.column_config.CheckboxColumn("Estoque ilimitado")})
                registros = editados.to_dict("records") if hasattr(editados, "to_dict") else editados
                for atributos, linha in zip(combinacoes, registros):
                    digitado = {"quantidade": linha.get("quantidade", 0), "ilimitado": linha.get("ilimitado", False)}
                    edicoes[planilha_esp.chave_atributos(atributos)] = digitado
                    linhas_estoque.append({"atributos": atributos, **digitado, "imagem": "",
                                           "preco": precos[planilha_esp.chave_atributos(atributos)]})
            except (ValueError, TypeError, planilha_esp.PlanilhaInvalida) as e:
                st.error(str(e))
        else:
            simples = estado["simples"]
            ilimitado = st.checkbox("Estoque ilimitado", value=bool(simples["ilimitado"]),
                                    disabled=no_banco, key=k("ilimitado"))
            quantidade = st.number_input(
                "Quantidade atual" if no_banco else "Quantidade inicial", min_value=0,
                value=int(simples["quantidade"]), step=1, disabled=ilimitado or no_banco, key=k("qtd"),
            )
            linhas_estoque = [{"atributos": {}, "preco": preco_catalogo, "quantidade": quantidade,
                               "ilimitado": ilimitado, "imagem": ""}]

    # ---- fotos: gerais do item + uma aba por opção de variação marcada ----
    st.divider()
    st.subheader("Fotos")
    fotos = []
    com_fotos = {}     # {tipo: opções que têm fotos neste produto}
    if tipos_escolhidos:
        tipos_lista = list(tipos_escolhidos)
        rot = lambda t: ce.ROTULOS.get(t, t)
        if len(tipos_lista) > 1:
            padrao = tipo_principal_salvo(loja, id_produto, tipos_escolhidos) or tipos_lista[0]
            principal = st.selectbox(
                "Atributo principal: ganha fotos de TODAS as opções", tipos_lista, format_func=rot,
                index=tipos_lista.index(padrao), key=k("principal_" + "|".join(tipos_lista)),
                help="Ex.: numa cueca, a cor: uma foto para cada cor.")
        else:
            principal = tipos_lista[0]
        com_fotos[principal] = list(tipos_escolhidos[principal])
        for t in tipos_lista:     # os demais atributos: só 1 ou 2 opções recebem fotos
            if t == principal:
                continue
            ops = tipos_escolhidos[t]
            salvas = [o for o in ops if id_produto and listar_imagens(loja.pasta_atributo(id_produto, t, o))]
            escolhidas = st.multiselect(
                f"{rot(t)}: quais opções terão fotos? (até 2)", ops, default=salvas[:2], max_selections=2,
                key=k(f"comfotos_{t}_" + "|".join(ops)),
                help="Ex.: dois tipos de tecido. As outras opções usam só as fotos gerais e as do atributo principal.")
            if escolhidas:
                com_fotos[t] = escolhidas
        st.caption("Dica: para tirar as fotos de uma opção, remova-as na aba dela antes de desmarcar a opção.")
        grupos = [(None, None)] + [(t, o) for t, ops in com_fotos.items() for o in ops]
        rotulos = ["Geral do item"] + [f"{ce.ROTULOS.get(t, t)}: {o}" for t, o in grupos[1:]]
        for aba, (t, o), rotulo in zip(st.tabs(rotulos), grupos, rotulos):
            with aba:
                fotos.append(bloco_fotos(loja, id_produto, t, o, k(f"g_{t}_{o}")))
    else:
        fotos.append(bloco_fotos(loja, id_produto, None, None, k("g_geral")))

    total = sum(g["existentes"] - len(g["remover"]) + len(g["arquivos"]) for g in fotos)
    if total <= 0:
        st.warning("Este produto vai ficar sem fotos (a landing page usará uma imagem padrão).")

    # ---- salvar ----
    if st.button("✅ Salvar produto", type="primary"):
        erros = []
        if novo:
            if id_produto.upper() in ids_em_uso(loja, ids):   # outra sessão pode ter criado o mesmo ID
                erros.append(f"O ID {id_produto} acabou de ser usado nesta loja. Recarregue a página para gerar outro.")
        if not nome.strip():
            erros.append("Digite o nome do produto.")
        if not categoria:
            erros.append("Escolha uma categoria. Para criar uma nova, use a barra lateral («Categorias e atributos»).")
        if not descricao.strip():
            erros.append("Escreva a descrição.")
        if not linhas_estoque:
            erros.append("Configure pelo menos uma combinação válida de estoque.")

        # valida TUDO antes de gravar qualquer coisa (pasta, fotos, bancos)
        if id_produto and nome.strip() and linhas_estoque:
            erros += banco_loja.validar_antes_de_gravar(
                loja.banco_estoque(modo), id_produto, nome.strip(), linhas_estoque, modo)
        for e in erros:
            st.error(e)

        if not erros:
            pasta_produto = loja.pasta_produto(id_produto)
            try:
                # 1) pasta + fotos
                novos = repetidos = n_removidas = 0
                pasta_produto.mkdir(parents=True, exist_ok=True)
                for g in fotos:
                    pasta_g = (pasta_produto if g["tipo"] is None
                               else loja.pasta_atributo(id_produto, g["tipo"], g["opcao"]))
                    if pasta_g is None:
                        raise ValueError(f"A opção '{g['opcao']}' não serve como nome de pasta.")
                    pasta_g.mkdir(parents=True, exist_ok=True)
                    for f in g["remover"]:
                        f.unlink()
                    n_removidas += len(g["remover"])
                    n, r = salvar_imagens(pasta_g, g["arquivos"])
                    novos += n
                    repetidos += r
                # 2) acréscimos de preço (modo especializado) e catalogo.db: relê as fotos e os acréscimos acima
                if modo == MODO_ESP:
                    gravar_acrescimos_produto(loja, id_produto, acrescimos if tipos_escolhidos else {})
                gravar_produto_catalogo(loja, id_produto, nome.strip(), preco_catalogo,
                                        descricao.strip(), categoria)
                # 3) estoque direto no banco do bot: cada SKU leva as fotos gerais + as das suas opções
                for linha_estoque in linhas_estoque:
                    linha_estoque["imagem"] = ";".join(
                        fotos_do_sku(loja, id_produto, linha_estoque["atributos"], list(ce.VARIANTES), com_fotos))
                if modo == MODO_ESP:
                    banco_loja.gravar_esp(loja.banco_estoque(MODO_ESP), id_produto, nome.strip(), linhas_estoque)
                else:
                    unica = linhas_estoque[0]
                    banco_loja.gravar_simples_db(loja.banco_estoque(MODO_SIMPLES), id_produto, nome.strip(),
                                                 preco_catalogo, unica["quantidade"], unica["ilimitado"])
            except PermissionError as e:
                st.error(str(e) or "Não consegui gravar. Algum arquivo está aberto em outro programa; feche e tente de novo.")
                st.stop()
            except sqlite3.Error as e:
                st.error(f"Não consegui gravar no banco ({e}). Ele pode estar aberto em outro programa. "
                         "Se o produto já apareceu na lista, salve de novo pela opção «Editar produto existente».")
                st.stop()
            except (ValueError, OSError) as e:
                st.error(f"Não consegui salvar o produto: {e}")
                st.stop()

            produtos_novos = ler_catalogo(loja)

            partes = [f"{novos} foto(s) nova(s) salva(s)"]
            if repetidos:
                partes.append(f"{repetidos} repetida(s) ignorada(s)")
            if n_removidas:
                partes.append(f"{n_removidas} removida(s)")
            st.session_state["msg"] = (f"{id_produto} {'adicionado' if novo else 'atualizado'} em «{loja.nome}»: "
                                       + ", ".join(partes) + ".")
            if not novo:   # produto novo -> continua em "Adicionar" (cadastro em sequência)
                st.session_state["ir_para"] = proximo_pendente(produtos_novos, id_produto)
            st.session_state["v"] = v + 1
            st.rerun()


if __name__ == "__main__":
    main()
