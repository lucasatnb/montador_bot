"""
interface_loja.py  --  Painel do dono da loja (Streamlit): COMANDAS e ESTOQUE do bot.

  🧾 Comandas   lista as comandas e deixa o dono dizer se o pagamento foi CONFIRMADO ou se a comanda foi
                CANCELADA (cancelar devolve os itens ao estoque, igual ao comando "cancelar 7" do bot).
  💬 Mensagens  o dono acompanha as conversas dos clientes com o bot (atualiza sozinho) e pode ESCREVER para o
                cliente: a mensagem entra numa fila e o bot a envia pelo canal (Telegram/WhatsApp) que você registrar.
  🗂️ Catálogo   CRUD de produtos: adicionar, editar (nome, descrição, categoria, preço) e remover (catalogo_loja.py).
  📦 Estoque    📊 Monitorar (situação de cada item, atualiza sozinho) · ✏️ Editar (quantidade / ilimitado / ativo;
                se o bot vender um item enquanto você edita, ele NÃO é sobrescrito) · 🕘 Histórico.
                🚨 ZERAR TODO O ESTOQUE (ou só alguns produtos) guarda o estado anterior e dá para «Desfazer».

Lê e grava direto nos bancos do bot, então funciona com o bot ligado:
    <PASTA_LOJA>/config.json, atributos.json, produtos_especializados.db   (estoque; o "modo" vem do config.json)
    <CAMINHO_COMANDAS>                                                      (comandas.db)
O histórico do estoque vai para <PASTA_LOJA>/registro_estoque.jsonl e os "desfazer" para <PASTA_LOJA>/snapshots_zerar/.

Instalar:  pip install streamlit pandas
Rodar:     streamlit run interface_loja.py

Mensagens: o painel e o bot são programas separados; conversam pelo banco mensagens.db (registro_mensagens.py).
O bot precisa estar com o despachante ligado (notificacoes.iniciar_despachante() + registrar_enviador(...)); o painel
mostra "bot online" quando ele está. Sem isso, as mensagens ficam na fila e saem quando o bot voltar.
Ao confirmar/cancelar uma comanda aqui, o cliente é avisado por essa mesma fila (dá para desmarcar).
Atenção: se o cliente responder à mensagem do dono, quem recebe a resposta ainda é o bot (ele não "passa a vez").
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ======================== CONFIGURE AQUI ========================
PASTA_BOT = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_BOT)
import bot_config   # noqa: E402  (a pasta da loja vem do bot_config.json, igual ao bot)
PASTA_LOJA = os.environ.get("BOT_PASTA_ESTOQUE") or bot_config.pasta_loja() or os.path.join(PASTA_BOT, "loja")
# mesmas variáveis de ambiente do bot: se uma estiver definida, painel e bot enxergam o MESMO arquivo
CAMINHO_COMANDAS = os.path.abspath(os.environ.get("BOT_COMANDAS_DB") or os.path.join(PASTA_BOT, "comandas.db"))
CAMINHO_MENSAGENS = os.environ.get("BOT_CAMINHO_MENSAGENS") or os.path.join(PASTA_BOT, "mensagens.db")
# ================================================================

sys.path.insert(0, PASTA_BOT)
import registro_mensagens as rm   # noqa: E402  (a ponte com o bot; precisa estar na mesma pasta deste arquivo)

rm.CAMINHO_DB = CAMINHO_MENSAGENS
import catalogo_loja as cl   # noqa: E402  (CRUD de produtos; só biblioteca padrão)
try:   # os textos de aviso ao cliente são os do bot (atendimento/configuracao.py); sem ele, usa estes
    from atendimento import configuracao as _cfg   # noqa: E402
    TEXTO_CONFIRMADA, TEXTO_CANCELADA = _cfg.TEXTO_CONFIRMADA, _cfg.TEXTO_CANCELADA
except Exception:
    TEXTO_CONFIRMADA = "Pagamento confirmado, {nome}! Obrigado pela compra (comanda nº {numero}). 😊"
    TEXTO_CANCELADA = "Sua comanda nº {numero} foi cancelada e os itens voltaram ao estoque. Se quiser, é só fazer um novo pedido."

DB_POR_MODO = {"especializado": "produtos_especializados.db"}   # igual ao estoque/constantes.py do bot
ESGOTADO, BAIXO, OK, ILIMITADO, INATIVO = "🔴 Esgotado", "🟠 Baixo", "🟢 OK", "♾️ Ilimitado", "⚫ Inativo"
ORDEM = {ESGOTADO: 0, BAIXO: 1, OK: 2, ILIMITADO: 3, INATIVO: 4}
ICONE_ENVIO = {"pendente": "⏳ na fila", "enviando": "⏳ enviando", "enviada": "✓ enviada", "erro": "⚠️ falhou"}
ROTULO_STATUS = {"aguardando": "🟡 Aguardando", "confirmada": "🟢 Confirmada", "cancelada": "⚫ Cancelada"}
TELAS = ["🧾 Comandas", "💬 Mensagens", "🗂️ Catálogo", "📦 Estoque"]
VISOES = ["📊 Monitorar", "✏️ Editar estoque", "🕘 Histórico"]


class Indisponivel(Exception):
    """Banco ausente ou ilegível, com mensagem em linguagem simples."""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conectar(caminho) -> sqlite3.Connection:
    if not os.path.exists(caminho):
        raise Indisponivel(f"Não achei o banco '{caminho}'.")
    con = sqlite3.connect(caminho, timeout=10, isolation_level=None)   # transações manuais
    con.execute("PRAGMA foreign_keys = ON")
    return con


# ============================ estoque (banco da loja) ============================
class EstoqueLoja:
    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.arq_historico = self.pasta / "registro_estoque.jsonl"
        self.pasta_snapshots = self.pasta / "snapshots_zerar"
        self.nome, self.caminho = self.pasta.name, None
        try:
            with open(self.pasta / "config.json", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            raise Indisponivel(f"Não consegui ler '{self.pasta / 'config.json'}': {e}")
        self.nome = cfg.get("nome") or self.nome
        banco = DB_POR_MODO.get(cfg.get("modo"))
        if banco is None:
            raise Indisponivel(f"Modo '{cfg.get('modo')}' do config.json não é suportado (suportados: "
                               f"{', '.join(DB_POR_MODO)}).")
        self.caminho = str(self.pasta / banco)

    def _ler_json(self, nome, padrao):
        try:
            with open(self.pasta / nome, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return padrao

    # ---- leitura
    def ler(self) -> list:
        """[{chave (SKU), produto_id, produto, variacao, preco, quantidade, ilimitado, ativo, produto_ativo}]"""
        con = _conectar(self.caminho)
        try:
            linhas = con.execute(
                "SELECT s.sku, s.produto_id, p.nome, s.atributos, s.preco, s.quantidade, s.ilimitado, s.ativo, p.ativo "
                "FROM skus s JOIN produtos p ON p.id = s.produto_id ORDER BY s.rowid").fetchall()
        except sqlite3.Error as e:
            raise Indisponivel(f"O banco '{self.caminho}' não está no formato esperado ({e}).")
        finally:
            con.close()
        itens = []
        for sku, pid, nome, atrib, preco, qtd, ilim, ativo, p_ativo in linhas:
            try:
                valores = [str(v) for v in json.loads(atrib).values()]
            except (ValueError, AttributeError):
                valores = []
            itens.append({"chave": sku, "produto_id": pid, "produto": nome,
                          "variacao": " ".join(v.upper() if len(v) <= 2 else v for v in valores),
                          "preco": float(preco), "quantidade": int(qtd), "ilimitado": bool(ilim),
                          "ativo": bool(ativo), "produto_ativo": bool(p_ativo)})
        return itens

    # ---- histórico
    def _registrar(self, evento: dict):
        evento = {"quando": _agora(), **evento}
        self.pasta.mkdir(parents=True, exist_ok=True)
        with open(self.arq_historico, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")

    def _eventos(self) -> list:
        eventos = []
        try:
            with open(self.arq_historico, encoding="utf-8") as f:
                for linha in f:
                    try:
                        eventos.append(json.loads(linha))
                    except ValueError:
                        continue
        except OSError:
            pass
        return eventos

    def historico(self, n: int = 200) -> list:
        return list(reversed(self._eventos()))[:n]

    # ---- edição (sem sobrescrever o que o bot mexeu)
    def salvar_edicoes(self, mudancas: list):
        """mudancas = [{"chave", "antes": (qtd, ilim, ativo), "depois": (...)}]. Cada item só é gravado se o banco
        ainda estiver igual ao "antes". Devolve (aplicadas, conflitos) com as chaves."""
        aplicadas, conflitos = [], []
        con = _conectar(self.caminho)
        try:
            for m in mudancas:
                (q0, i0, a0), (q1, i1, a1) = m["antes"], m["depois"]
                cur = con.execute(
                    "UPDATE skus SET quantidade = ?, ilimitado = ?, ativo = ?, atualizado_em = ? "
                    "WHERE sku = ? AND quantidade = ? AND ilimitado = ? AND ativo = ?",
                    (q1, int(i1), int(a1), _agora(), m["chave"], q0, int(i0), int(a0)))
                (aplicadas if cur.rowcount == 1 else conflitos).append(m["chave"])
                if cur.rowcount == 1:
                    self._registrar({"acao": "edição", "item": m["chave"],
                                     "antes": [q0, bool(i0), bool(a0)], "depois": [q1, bool(i1), bool(a1)]})
        except sqlite3.Error as e:
            raise Indisponivel(f"Erro ao gravar no banco: {e}")
        finally:
            con.close()
        return aplicadas, conflitos

    def devolver(self, sku: str, qtd: int) -> bool:
        """Devolve unidades de um SKU (cancelamento de comanda). Estoque ilimitado não muda."""
        con = _conectar(self.caminho)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("UPDATE skus SET quantidade = quantidade + ?, atualizado_em = ? "
                        "WHERE sku = ? AND ilimitado = 0", (qtd, _agora(), sku))
            achou = con.execute("SELECT 1 FROM skus WHERE sku = ?", (sku,)).fetchone() is not None
            con.execute("COMMIT")
            return achou
        except sqlite3.Error:
            if con.in_transaction:
                con.execute("ROLLBACK")
            return False
        finally:
            con.close()

    # ---- zerar / desfazer
    def zerar(self, incluir_ilimitados: bool = True, produto_ids=None) -> dict:
        """Zera quantidade (e tira o ilimitado, se incluído). Guarda o estado anterior para «Desfazer»."""
        con = _conectar(self.caminho)
        try:
            con.execute("BEGIN IMMEDIATE")
            filtro, args = "", []
            if produto_ids:
                filtro = f" AND produto_id IN ({','.join('?' * len(produto_ids))})"
                args = list(produto_ids)
            linhas = con.execute(f"SELECT sku, quantidade, ilimitado, ativo FROM skus WHERE "
                                 f"(quantidade > 0 OR (ilimitado = 1 AND ?)){filtro}", [int(incluir_ilimitados)] + args).fetchall()
            for sku, *_ in linhas:
                con.execute("UPDATE skus SET quantidade = 0, ilimitado = 0, atualizado_em = ? WHERE sku = ?",
                            (_agora(), sku))
            con.execute("COMMIT")
        except sqlite3.Error as e:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise Indisponivel(f"Erro ao zerar o estoque: {e}")
        finally:
            con.close()
        unidades = sum(q for _, q, ilim, _ in linhas if not ilim)
        nome_snap = f"zerar_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        self.pasta_snapshots.mkdir(parents=True, exist_ok=True)
        with open(self.pasta_snapshots / nome_snap, "w", encoding="utf-8") as f:
            json.dump({"criado_em": _agora(), "itens": {s: [q, bool(i), bool(a)] for s, q, i, a in linhas}}, f,
                      ensure_ascii=False)
        evento = {"acao": "zerar produtos" if produto_ids else "zerar tudo", "itens": len(linhas),
                  "unidades": unidades, "snapshot": nome_snap}
        if produto_ids:
            evento["produtos"] = list(produto_ids)
        self._registrar(evento)
        return {"itens": len(linhas), "unidades": unidades}

    def zerar_pendente(self):
        """(nome do snapshot, dados) do último «zerar» ainda não desfeito, ou None."""
        desfeitos, ultimo = set(), None
        for e in self._eventos():
            if e.get("acao") == "desfazer zerar":
                desfeitos.add(e.get("snapshot"))
            elif str(e.get("acao", "")).startswith("zerar") and e.get("snapshot"):
                ultimo = e["snapshot"]
        if not ultimo or ultimo in desfeitos:
            return None
        try:
            with open(self.pasta_snapshots / ultimo, encoding="utf-8") as f:
                return ultimo, json.load(f)
        except (OSError, ValueError):
            return None

    def desfazer_zerar(self) -> dict:
        """Restaura o estado guardado. Item que já foi mexido depois do zerar (vendido, editado) fica como está."""
        pendente = self.zerar_pendente()
        if pendente is None:
            return {"restaurados": 0, "conflitos": []}
        nome_snap, dados = pendente
        restaurados, conflitos = 0, []
        con = _conectar(self.caminho)
        try:
            con.execute("BEGIN IMMEDIATE")
            for sku, (q, ilim, ativo) in dados["itens"].items():
                cur = con.execute("UPDATE skus SET quantidade = ?, ilimitado = ?, atualizado_em = ? "
                                  "WHERE sku = ? AND quantidade = 0 AND ilimitado = 0 AND ativo = ?",
                                  (q, int(ilim), _agora(), sku, int(ativo)))
                if cur.rowcount == 1:
                    restaurados += 1
                else:
                    conflitos.append(sku)
            con.execute("COMMIT")
        except sqlite3.Error as e:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise Indisponivel(f"Erro ao desfazer: {e}")
        finally:
            con.close()
        self._registrar({"acao": "desfazer zerar", "itens": restaurados, "conflitos": len(conflitos),
                         "snapshot": nome_snap})
        return {"restaurados": restaurados, "conflitos": conflitos}


# ============================ comandas (comandas.db) ============================
class Comandas:
    def __init__(self, caminho):
        self.caminho = str(caminho)

    def existe(self) -> bool:
        return os.path.exists(self.caminho)

    def listar(self) -> list:
        """Todas as comandas, da mais nova para a mais antiga, cada uma com seus itens."""
        con = _conectar(self.caminho)
        try:
            comandas = con.execute("SELECT id, cliente_nome, cliente_chave, total, fechada_em, status "
                                   "FROM comandas ORDER BY id DESC").fetchall()
            itens = con.execute("SELECT comanda_id, produto_id, produto_nome, quantidade, preco_unitario, subtotal "
                                "FROM comanda_itens ORDER BY comanda_id, rowid").fetchall()
        except sqlite3.Error as e:
            raise Indisponivel(f"O banco de comandas não está no formato esperado ({e}).")
        finally:
            con.close()
        por = {}
        for i in itens:
            por.setdefault(i[0], []).append({"sku": i[1], "nome": i[2], "qtd": i[3], "preco": i[4], "subtotal": i[5]})
        return [{"id": i, "nome": n, "chave": k, "total": t, "quando": q, "status": s, "itens": por.get(i, [])}
                for i, n, k, t, q, s in comandas]

    def _mudar_status(self, numero: int, de: str, para: str) -> bool:
        """Atômico: só muda se a comanda ainda está em `de` (duas pessoas não passam juntas)."""
        con = _conectar(self.caminho)
        try:
            cur = con.execute("UPDATE comandas SET status = ?, atualizada_em = ? WHERE id = ? AND status = ?",
                              (para, _agora(), numero, de))
            return cur.rowcount == 1
        finally:
            con.close()

    def confirmar(self, c: dict) -> tuple:
        if c["status"] != "aguardando":
            return "warning", f"A comanda nº {c['id']} não está mais aguardando (está {c['status']})."
        if not self._mudar_status(c["id"], "aguardando", "confirmada"):
            return "warning", f"A comanda nº {c['id']} acabou de mudar. Atualize a tela."
        return "success", f"Comanda nº {c['id']} confirmada ({c['nome']})."

    def cancelar(self, c: dict, est: EstoqueLoja) -> tuple:
        """Cancela e devolve os itens ao estoque. Troca o status ANTES de devolver: se duas pessoas cancelarem
        ao mesmo tempo, só uma passa e o estoque nunca é devolvido duas vezes."""
        if c["status"] != "aguardando":
            return "warning", f"A comanda nº {c['id']} não está mais aguardando (está {c['status']})."
        if not self._mudar_status(c["id"], "aguardando", "cancelada"):
            return "warning", f"A comanda nº {c['id']} acabou de mudar. Atualize a tela."
        falhas = []
        for it in c["itens"]:
            if est.devolver(it["sku"], it["qtd"]):
                est._registrar({"acao": "devolução (comanda cancelada)", "item": it["sku"],
                                "comanda": c["id"], "unidades": it["qtd"]})
            else:
                falhas.append(f"{it['qtd']}x {it['nome']}")
        if falhas:
            return "error", (f"Comanda nº {c['id']} cancelada, MAS não consegui devolver ao estoque: "
                             f"{', '.join(falhas)}. Ajuste à mão na tela de estoque.")
        return "success", f"Comanda nº {c['id']} cancelada ({c['nome']}); itens devolvidos ao estoque."


# ============================ lógica de tela (sem I/O) ============================
def reais(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
    if acao.startswith("devolução"):
        return f"{e.get('unidades', 0)}x {e.get('item')} (comanda nº {e.get('comanda')})"
    return ""


# ================================ telas: comandas ================================
def _tabela_comandas(com: Comandas, filtro: str):
    try:
        todas = com.listar()
    except Indisponivel as e:
        st.error(str(e))
        return
    aguard = [c for c in todas if c["status"] == "aguardando"]
    m = st.columns(4)
    m[0].metric("🟡 Aguardando", len(aguard), help="Itens já reservados (saíram do estoque).")
    m[1].metric("Valor aguardando", reais(sum(c["total"] for c in aguard)))
    m[2].metric("🟢 Confirmadas", sum(1 for c in todas if c["status"] == "confirmada"))
    m[3].metric("⚫ Canceladas", sum(1 for c in todas if c["status"] == "cancelada"))
    alvo = {"Aguardando": "aguardando", "Confirmada": "confirmada", "Cancelada": "cancelada"}.get(filtro)
    mostrar = [c for c in todas if alvo is None or c["status"] == alvo]
    if not mostrar:
        st.info("Nenhuma comanda nesse filtro.")
    else:
        st.dataframe(pd.DataFrame([{
            "Nº": c["id"], "Quando": c["quando"].replace("T", " "), "Cliente": c["nome"] or "(sem nome)",
            "Itens": "; ".join(f"{i['qtd']}x {i['nome']}" for i in c["itens"]), "Total": c["total"],
            "Status": ROTULO_STATUS.get(c["status"], c["status"])} for c in mostrar]),
            hide_index=True, use_container_width=True,
            column_config={"Total": st.column_config.NumberColumn(format="R$ %.2f")})
    st.caption(f"Atualizado às {datetime.now():%H:%M:%S}")


def painel_comandas(com: Comandas, est, auto, intervalo):
    if not com.existe():
        st.info("Ainda não há comandas: o banco é criado quando o bot fecha a primeira.")
        return
    filtro = st.radio("Mostrar", ["Aguardando", "Confirmada", "Cancelada", "Todas"], horizontal=True,
                      key="filtro_comandas", label_visibility="collapsed")
    try:
        st.fragment(run_every=intervalo if auto else None)(_tabela_comandas)(com, filtro)
    except (AttributeError, TypeError):   # Streamlit antigo
        _tabela_comandas(com, filtro)

    try:
        aguardando = [c for c in com.listar() if c["status"] == "aguardando"]
    except Indisponivel:
        return
    st.divider()
    st.subheader("Responder uma comanda")
    if not aguardando:
        st.success("Nenhuma comanda aguardando confirmação. 🎉")
        return
    por_id = {c["id"]: c for c in aguardando}
    numero = st.selectbox("Comanda aguardando", list(por_id), key="comanda_escolhida",
                          format_func=lambda n: f"nº {n} · {por_id[n]['nome'] or '(sem nome)'} · {reais(por_id[n]['total'])}")
    c = por_id[numero]

    def _com_aviso(acao, texto_aviso):
        """Executa confirmar/cancelar e, se marcado, põe o aviso ao cliente na fila de envio."""
        try:
            nivel, texto = acao()
            if nivel != "warning" and st.session_state.get("avisar_cliente", True):
                rm.enfileirar(c["chave"], texto_aviso, c["nome"])
                texto += " Aviso ao cliente na fila de envio."
            st.session_state["msg_comanda"] = (nivel, texto)
        except (Indisponivel, sqlite3.Error) as e:
            st.session_state["msg_comanda"] = ("error", str(e))
        st.rerun()

    with st.container(border=True):
        st.markdown(f"**Cliente:** {c['nome'] or '(sem nome)'} (`{c['chave']}`) · fechada em {c['quando'].replace('T', ' ')}")
        st.dataframe(pd.DataFrame([{"SKU": i["sku"], "Produto": i["nome"], "Qtd": i["qtd"],
                                    "Preço unit.": i["preco"], "Subtotal": i["subtotal"]} for i in c["itens"]]),
                     hide_index=True, use_container_width=True,
                     column_config={"Preço unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                                    "Subtotal": st.column_config.NumberColumn(format="R$ %.2f")})
        st.markdown(f"**Total: {reais(c['total'])}**")
        st.checkbox("📨 Avisar o cliente (mensagem automática pelo bot)", value=True, key="avisar_cliente")
        if st.session_state.get("cancelar_pendente") == numero:
            st.error("Cancelar devolve os itens ao estoque e não dá para desfazer. Confirma?")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("✅ Sim, cancelar e devolver ao estoque", type="primary", use_container_width=True):
                    st.session_state["cancelar_pendente"] = None
                    _com_aviso(lambda: com.cancelar(c, est), TEXTO_CANCELADA.format(numero=c["id"]))
            with b2:
                if st.button("Voltar", use_container_width=True):
                    st.session_state["cancelar_pendente"] = None
                    st.rerun()
        else:
            b1, b2 = st.columns(2)
            with b1:
                if st.button("✅ Pagamento CONFIRMADO", type="primary", use_container_width=True):
                    _com_aviso(lambda: com.confirmar(c), TEXTO_CONFIRMADA.format(nome=c["nome"], numero=c["id"]))
            with b2:
                if st.button("❌ Cancelar comanda", use_container_width=True):
                    st.session_state["cancelar_pendente"] = numero
                    st.rerun()


# ================================ telas: mensagens ================================
def estado_bot():
    """(online?, texto): o despachante do bot dá um sinal de vida a cada ~2 s enquanto há um canal registrado."""
    try:
        ultimo = rm.ultimo_batimento()
    except sqlite3.Error:
        ultimo = None
    if ultimo is None:
        return False, "🔴 Bot sem envio: o despachante nunca ligou (veja notificacoes.iniciar_despachante)."
    seg = int((datetime.now() - ultimo).total_seconds())
    if seg > 15:
        return False, f"🔴 Bot offline (último sinal há {seg // 60} min {seg % 60} s). As mensagens ficam na fila."
    return True, "🟢 Bot online: as mensagens saem em poucos segundos."


def _transcricao(chave: str):
    mensagens = rm.mensagens(chave)
    with st.container(height=480, border=True):
        if not mensagens:
            st.caption("Sem mensagens.")
        for m in mensagens:
            hora = m["quando"][11:16] if len(m["quando"]) >= 16 else ""
            if m["sentido"] == "cliente":
                papel, avatar = "user", None
            elif m["sentido"] == "bot":
                papel, avatar = "assistant", None
            else:
                papel, avatar = "dono", "🧑‍💼"
            with st.chat_message(papel, avatar=avatar):
                st.markdown(m["texto"].replace("\n", "  \n"))
                rodape = f"{hora}"
                if m["sentido"] == "dono":
                    rodape += " · você · " + ICONE_ENVIO.get(m["status"], m["status"])
                elif m["status"] == "erro":
                    rodape += " · ⚠️ aviso do bot não saiu"
                st.caption(rodape)
                if m["status"] == "erro" and m["sentido"] == "dono":
                    st.caption(f"Motivo: {m['erro']}")
                    if st.button("Tentar de novo", key=f"re_{m['id']}"):
                        rm.reenfileirar(m["id"])
                        st.rerun()


def painel_mensagens(auto, intervalo):
    online, texto_bot = estado_bot()
    (st.success if online else st.warning)(texto_bot)
    if not rm.existe():
        st.info("Ainda não há mensagens: o banco é criado quando o bot atende o primeiro cliente.")
        return
    try:
        conversas = rm.conversas()
    except sqlite3.Error as e:
        st.error(f"O banco de mensagens não está no formato esperado ({e}).")
        return
    if not conversas:
        st.info("Nenhuma conversa ainda.")
        return
    por = {c["chave"]: c for c in conversas}
    if st.session_state.get("conversa_escolhida") not in por:
        st.session_state["conversa_escolhida"] = next(iter(por))
    chave = st.selectbox(
        "Conversa", list(por), key="conversa_escolhida",
        format_func=lambda k: (f"{por[k]['nome'] or '(sem nome)'} · {k} · {por[k]['ultima'][5:16].replace('T', ' ')}"
                               f" · {por[k]['previa'][:40].replace(chr(10), ' ')}"))
    try:
        st.fragment(run_every=intervalo)(_transcricao)(chave)
    except (AttributeError, TypeError):   # Streamlit antigo
        _transcricao(chave)
    if rm.esta_pausado(chave):
        ate = rm.pausado_ate(chave)
        if ate:   # pausa com prazo (loja por orçamento, depois que a comanda fecha)
            st.warning(f"🧑‍💼 O bot está calado com este cliente (comanda de orçamento fechada). Ele volta sozinho às "
                       f"**{ate:%H:%M}**, ou assim que você ligar.")
        else:
            st.warning("🧑‍💼 Você está no comando: o bot **não responde** a este cliente até você liberar.")
        if st.button("✅ Ligar o bot para este cliente" if ate else "✅ Liberar o bot para este cliente", key=f"lib_{chave}"):
            rm.liberar(chave)
            st.rerun()
    else:
        st.caption("🤖 O bot está atendendo este cliente.")
        if st.button("✋ Assumir conversa (pausar o bot)", key=f"ass_{chave}"):
            rm.pausar(chave)
            st.rerun()
    if not online:
        st.caption("⚠️ O bot parece desligado: o que você escrever fica na fila e sai quando ele voltar.")
    texto = st.chat_input("Escreva para o cliente (sai pelo bot)…")
    if texto and texto.strip():
        rm.pausar(chave)   # escrever já assume a conversa: o bot não atravessa a sua resposta
        rm.enfileirar(chave, texto.strip(), por[chave]["nome"])
        st.rerun()


# ================================ telas: catálogo (CRUD) ================================
def _erro_catalogo(e):
    st.session_state["msg_catalogo"] = ("error", str(e))
    st.rerun()


def _form_novo_produto(pasta):
    cats = cl.categorias(pasta)
    with st.form("novo_produto", clear_on_submit=True):
        nome = st.text_input("Nome")
        descricao = st.text_area("Descrição", height=90)
        c1, c2 = st.columns(2)
        with c1:
            escolha = st.selectbox("Categoria", cats + ["➕ Nova categoria…"] if cats else ["➕ Nova categoria…"])
            nova = st.text_input("Nome da nova categoria (se escolheu «Nova»)")
        with c2:
            preco = st.number_input("Preço (R$)", min_value=0.0, step=1.0, format="%.2f")
            ilimitado = st.checkbox("Estoque ilimitado", value=True,
                                    help="Desmarque para controlar a quantidade (o bot só mostra itens com estoque).")
            qtd = st.number_input("Quantidade (se não for ilimitado)", min_value=0, step=1, value=0)
        if st.form_submit_button("➕ Adicionar produto", type="primary"):
            categoria = nova if escolha.startswith("➕") else escolha
            try:
                pid = cl.criar_produto(pasta, nome, descricao, categoria, preco, ilimitado, qtd)
            except cl.ErroLoja as e:
                _erro_catalogo(e)
            st.session_state["msg_catalogo"] = ("success", f"Produto {pid} adicionado. O bot já passa a mostrá-lo.")
            st.rerun()


def _editar_produto(pasta, p):
    cats = cl.categorias(pasta)
    with st.form(f"edit_{p['id']}"):
        nome = st.text_input("Nome", p["nome"])
        descricao = st.text_area("Descrição", p["descricao"], height=90)
        opcoes = cats if p["categoria"] in cats else cats + [p["categoria"]]
        categoria = st.selectbox("Categoria", opcoes + ["➕ Nova categoria…"],
                                 index=opcoes.index(p["categoria"]) if p["categoria"] in opcoes else 0)
        nova = st.text_input("Nome da nova categoria (se escolheu «Nova»)")
        st.markdown("**Preço (R$)**" + (" — um por variação" if len(p["skus"]) > 1 else ""))
        precos = {}
        for s in p["skus"]:
            rotulo = s["variacao"] or "preço"
            precos[s["sku"]] = st.number_input(rotulo, value=float(s["preco"]), min_value=0.0, step=1.0,
                                               format="%.2f", key=f"pr_{s['sku']}")
        if st.form_submit_button("💾 Salvar alterações", type="primary"):
            try:
                cl.editar_produto(pasta, p["id"], nome, descricao,
                                  nova if categoria.startswith("➕") else categoria, precos)
            except cl.ErroLoja as e:
                _erro_catalogo(e)
            st.session_state["msg_catalogo"] = ("success", f"Produto {p['id']} atualizado.")
            st.rerun()


def painel_catalogo(est):
    pasta = Path(est.pasta)
    msg = st.session_state.pop("msg_catalogo", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    try:
        produtos = cl.listar_produtos(pasta)
    except cl.ErroLoja as e:
        st.error(str(e))
        return
    st.caption("Mudanças valem na hora para o bot. O **site** é uma página pronta: depois de adicionar, remover ou "
               "mudar preço, gere o site de novo no montador. Variações (cor, tamanho) e fotos também se cadastram lá.")
    st.dataframe(pd.DataFrame([{"ID": p["id"], "Nome": p["nome"], "Categoria": p["categoria"],
                                "Descrição": p["descricao"], "Preço": p["preco"],
                                "Variações": len(p["skus"]) if len(p["skus"]) > 1 else 0} for p in produtos]),
                 hide_index=True, use_container_width=True,
                 column_config={"Preço": st.column_config.NumberColumn(format="R$ %.2f")})
    with st.expander("➕ Adicionar produto", expanded=not produtos):
        _form_novo_produto(pasta)
    if not produtos:
        return
    por_id = {p["id"]: p for p in produtos}
    escolhido = st.selectbox("Editar ou remover", list(por_id), key="produto_catalogo",
                             format_func=lambda i: f"{i} · {por_id[i]['nome']}")
    p = por_id[escolhido]
    with st.container(border=True):
        _editar_produto(pasta, p)
        if st.session_state.get("remover_pendente") == p["id"]:
            st.error(f"Remover «{p['nome']}»? Ele some do bot e do catálogo. O histórico de comandas fica.")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("✅ Sim, remover", type="primary", use_container_width=True):
                    st.session_state["remover_pendente"] = None
                    try:
                        cl.remover_produto(pasta, p["id"])
                    except cl.ErroLoja as e:
                        _erro_catalogo(e)
                    st.session_state["msg_catalogo"] = ("success", f"«{p['nome']}» removido.")
                    st.rerun()
            with b2:
                if st.button("Voltar", use_container_width=True, key="rem_voltar"):
                    st.session_state["remover_pendente"] = None
                    st.rerun()
        elif st.button("🗑️ Remover este produto"):
            st.session_state["remover_pendente"] = p["id"]
            st.rerun()


# ================================ telas: estoque ================================
def metricas(itens, limite):
    estados = [situacao(i, limite) for i in itens]
    unidades = sum(i["quantidade"] for i in itens if not i["ilimitado"] and i["ativo"] and i["produto_ativo"])
    c = st.columns(5)
    c[0].metric("Itens vendáveis", sum(1 for s in estados if s != INATIVO))
    c[1].metric("🔴 Esgotados", estados.count(ESGOTADO))
    c[2].metric("🟠 Estoque baixo", estados.count(BAIXO), help=f"Até {limite} unidade(s).")
    c[3].metric("♾️ Ilimitados", estados.count(ILIMITADO))
    c[4].metric("Unidades em estoque", unidades)


def painel_leitura(est, limite):
    try:
        itens = est.ler()
    except Indisponivel as e:
        st.error(str(e))
        return
    metricas(itens, limite)
    st.dataframe(pd.DataFrame([
        {"Situação": situacao(i, limite), "Item": i["chave"], "Produto": i["produto"], "Variação": i["variacao"],
         "Preço (R$)": i["preco"], "Quantidade": None if i["ilimitado"] else i["quantidade"]}
        for i in sorted(itens, key=lambda i: (ORDEM[situacao(i, limite)], i["quantidade"], i["produto"].casefold()))]),
        hide_index=True, use_container_width=True,
        column_config={"Preço (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                       "Quantidade": st.column_config.NumberColumn(format="%d")})
    st.caption(f"Atualizado às {datetime.now():%H:%M:%S}")


def painel_edicao(est):
    ver = st.session_state.setdefault("ver", 0)      # muda ao salvar/recarregar: a tela recomeça do banco
    chave_orig = f"orig_{ver}"
    if chave_orig not in st.session_state:
        try:
            st.session_state[chave_orig] = est.ler()
        except Indisponivel as e:
            st.error(str(e))
            return
    orig = st.session_state[chave_orig]
    st.caption("Mude **Quantidade**, **Ilimitado** ou **Ativo** e clique em Salvar. Esta tela não se atualiza sozinha "
               "(para não apagar o que você digitou): se o bot vender um item enquanto você edita, esse item vira "
               "conflito e **não é sobrescrito**.")
    df = pd.DataFrame([{"Item": i["chave"], "Produto": i["produto"], "Variação": i["variacao"],
                        "Preço (R$)": i["preco"], "Quantidade": i["quantidade"],
                        "Ilimitado": i["ilimitado"], "Ativo": i["ativo"]} for i in orig])
    editado = st.data_editor(
        df, hide_index=True, use_container_width=True, disabled=["Item", "Produto", "Variação", "Preço (R$)"],
        key=f"editor_{ver}",
        column_config={"Preço (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                       "Quantidade": st.column_config.NumberColumn(min_value=0, step=1, format="%d", required=True),
                       "Ilimitado": st.column_config.CheckboxColumn(help="Estoque infinito: a quantidade é ignorada."),
                       "Ativo": st.column_config.CheckboxColumn(help="Desmarcado = o bot não vende este item.")})
    mudancas = []
    for idx, it in enumerate(orig):
        linha = editado.iloc[idx]
        qtd = 0 if pd.isna(linha["Quantidade"]) else int(linha["Quantidade"])
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
            except Indisponivel as e:
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
    """Botão de emergência. Zerar guarda o estado anterior: dá para desfazer."""
    with st.container(border=True):
        st.markdown("#### 🚨 Emergência")
        if st.session_state.get("zerar_pendente"):
            incluir = st.checkbox("Incluir itens de estoque ilimitado (passam a ter 0)", value=True, key="zerar_incluir")
            afetados = [i for i in itens if i["quantidade"] > 0 or (incluir and i["ilimitado"])]
            unidades = sum(i["quantidade"] for i in afetados if not i["ilimitado"])
            st.error(f"Isso vai zerar **{len(afetados)} item(ns)** ({unidades} unidade(s)) de «{est.nome}». "
                     "O bot para de vender na hora. Logo depois dá para **desfazer** pelo botão «Desfazer».")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ CONFIRMAR: zerar tudo agora", type="primary", use_container_width=True):
                    try:
                        r = est.zerar(incluir_ilimitados=incluir)
                    except Indisponivel as e:
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
                    except Indisponivel as e:
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
                except Indisponivel as e:
                    st.error(str(e))
                    return
                st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                st.session_state["msg_estoque"] = (
                    "success", f"{r['itens']} item(ns) zerado(s) ({r['unidades']} unidade(s)). Dá para desfazer.")
                st.rerun()


def painel_estoque(est, limite, auto, intervalo):
    try:
        itens = est.ler()
    except Indisponivel as e:
        st.error(str(e))
        return
    msg = st.session_state.pop("msg_estoque", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    painel_emergencia(est, itens)
    visao = st.radio("Tela", VISOES, horizontal=True, label_visibility="collapsed", key="visao_estoque")
    if visao == VISOES[0]:
        try:
            st.fragment(run_every=intervalo if auto else None)(painel_leitura)(est, limite)
        except (AttributeError, TypeError):   # Streamlit antigo, sem atualização automática de trecho
            painel_leitura(est, limite)
    elif visao == VISOES[1]:
        metricas(itens, limite)
        painel_edicao(est)
    else:
        painel_historico(est)


def main():
    st.set_page_config(page_title="Painel da loja", page_icon="🛒", layout="wide")
    try:
        est = EstoqueLoja(PASTA_LOJA)
    except Indisponivel as e:
        st.title("🛒 Painel da loja")
        st.error(f"{e}\n\nConfira a variável PASTA_LOJA no começo do interface_loja.py (agora: `{PASTA_LOJA}`).")
        st.stop()
    com = Comandas(CAMINHO_COMANDAS)

    with st.sidebar:
        st.header(est.nome)
        st.caption(f"Loja: `{PASTA_LOJA}`\n\nComandas: `{CAMINHO_COMANDAS}`")
        limite = st.number_input("Estoque baixo: até (unidades)", min_value=0, value=5, step=1)
        auto = st.checkbox("Atualizar sozinho", value=True)
        intervalo = st.selectbox("A cada", [5, 10, 30, 60], index=1, format_func=lambda s: f"{s} segundos",
                                 disabled=not auto)
        if st.button("🔄 Atualizar agora"):
            st.rerun()
        st.divider()
        st.caption(estado_bot()[1])

    st.title(f"🛒 {est.nome}")
    tela = st.radio("Seção", TELAS, horizontal=True, label_visibility="collapsed", key="tela")
    intervalo = intervalo if auto else None
    if tela == TELAS[0]:
        msg = st.session_state.pop("msg_comanda", None)
        if msg:
            getattr(st, msg[0])(msg[1])
        painel_comandas(com, est, auto, intervalo)
    elif tela == TELAS[1]:
        painel_mensagens(auto, intervalo)
    elif tela == TELAS[2]:
        painel_catalogo(est)
    else:
        painel_estoque(est, limite, auto, intervalo)


if __name__ == "__main__":
    main()
