"""Estoque REAL de uma loja: o banco que o bot usa (e desconta a cada venda), para a interface de monitoramento.

    lojas/<loja>/produtos.db                    modo simples        (tabela produtos)
    lojas/<loja>/produtos_especializados.db     modo especializado  (tabelas produtos + skus)

Regras de segurança (o bot escreve nesse mesmo banco enquanto a interface está aberta):
  - toda escrita é uma transação BEGIN IMMEDIATE (a mesma trava que o bot usa);
  - editar um item só vale se ele ainda está como estava quando a pessoa abriu a tela; se o bot vendeu
    nesse meio tempo, é um CONFLITO e o item não é sobrescrito (senão a venda sumiria do estoque);
  - "zerar" grava antes uma cópia do estado anterior (estoque_snapshots/), então dá para DESFAZER;
  - toda alteração fica no registro_estoque.jsonl da loja.

Este módulo não usa Streamlit.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from nucleo.gerar_pastas import MODO_ESP


class EstoqueIndisponivel(Exception):
    """Banco ausente, em formato inesperado ou sem pré-requisito, com mensagem em linguagem simples."""


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _texto_variacao(atributos_json, rotulos):
    try:
        atributos = json.loads(atributos_json or "{}")
    except ValueError:
        return str(atributos_json)
    rotulos = rotulos or {}
    return " / ".join(f"{rotulos.get(t, t.capitalize())}: {o}" for t, o in atributos.items())


class EstoqueLoja:
    def __init__(self, loja, modo=None):
        self.loja = loja
        self.modo = modo or loja.modo
        self.caminho = loja.banco_estoque(self.modo)
        self.pasta_snapshots = loja.raiz / "estoque_snapshots"
        self.arquivo_log = loja.raiz / "registro_estoque.jsonl"

    # ------------------------------------------------------------ infraestrutura
    def existe(self):
        return self.caminho.exists()

    def _alvo(self):
        """(tabela, coluna-chave, coluna que liga ao produto)."""
        return ("skus", "sku", "produto_id") if self.modo == MODO_ESP else ("produtos", "id", "id")

    def _conectar(self):
        if not self.existe():
            raise EstoqueIndisponivel(f"Não achei o banco '{self.caminho.name}' desta loja. Salve um produto na interface do catálogo primeiro.")
        con = sqlite3.connect(str(self.caminho), timeout=10, isolation_level=None)   # transações manuais
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @staticmethod
    def _rollback(con):
        if con is not None and con.in_transaction:
            con.execute("ROLLBACK")

    def _registrar(self, **evento):
        """Anexa uma linha ao registro. Falha ao registrar nunca impede a operação."""
        try:
            with open(self.arquivo_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"quando": _agora(), **evento}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------ leitura
    def ler(self, rotulos=None):
        """Todos os itens do estoque. Cada item é um dict:
        chave (id ou sku), produto_id, produto, variacao, preco, quantidade, ilimitado, ativo, produto_ativo."""
        if self.modo == MODO_ESP:
            consulta = ("SELECT s.sku, s.produto_id, p.nome, s.atributos, s.preco, s.quantidade, s.ilimitado, "
                        "s.ativo, p.ativo FROM skus s JOIN produtos p ON p.id = s.produto_id ORDER BY s.rowid")
        else:
            consulta = ("SELECT id, id, nome, '{}', preco, quantidade, ilimitado, ativo, 1 "
                        "FROM produtos ORDER BY rowid")
        con = self._conectar()
        try:
            linhas = con.execute(consulta).fetchall()
        except sqlite3.Error as e:
            raise EstoqueIndisponivel(f"O banco '{self.caminho.name}' não está no formato esperado ({e}).") from e
        finally:
            con.close()
        return [{"chave": c, "produto_id": pid, "produto": nome, "variacao": _texto_variacao(attrs, rotulos),
                 "preco": float(preco), "quantidade": int(qtd), "ilimitado": bool(ilim), "ativo": bool(ativo),
                 "produto_ativo": bool(pativo)}
                for c, pid, nome, attrs, preco, qtd, ilim, ativo, pativo in linhas]

    # ------------------------------------------------------------ edição item a item
    def salvar_edicoes(self, mudancas):
        """mudancas: [{"chave", "antes": (quantidade, ilimitado, ativo), "depois": (...)}].
        Devolve (chaves aplicadas, chaves em conflito). Conflito = o item já não está como em "antes"
        (o bot vendeu ou outra pessoa mexeu): nada é gravado para ele."""
        tabela, col, _ = self._alvo()
        aplicadas, conflitos = [], []
        con = self._conectar()
        try:
            con.execute("BEGIN IMMEDIATE")
            for m in mudancas:
                qa, ia, aa = m["antes"]
                qd, id_, ad = m["depois"]
                qd = 0 if id_ else max(0, int(qd))      # estoque ilimitado guarda quantidade 0
                cur = con.execute(
                    f"UPDATE {tabela} SET quantidade = ?, ilimitado = ?, ativo = ?, atualizado_em = ? "
                    f"WHERE {col} = ? AND quantidade = ? AND ilimitado = ? AND ativo = ?",
                    (qd, int(id_), int(ad), _agora(), m["chave"], int(qa), int(ia), int(aa)))
                (aplicadas if cur.rowcount == 1 else conflitos).append(m["chave"])
            con.execute("COMMIT")
        except sqlite3.Error as e:
            self._rollback(con)
            raise EstoqueIndisponivel(f"Erro ao gravar no banco: {e}") from e
        finally:
            con.close()
        depois_por_chave = {m["chave"]: m for m in mudancas}
        for chave in aplicadas:
            m = depois_por_chave[chave]
            self._registrar(acao="edição", item=chave, antes=list(m["antes"]), depois=list(m["depois"]))
        return aplicadas, conflitos

    # ------------------------------------------------------------ zerar (com desfazer)
    def zerar(self, produto_ids=None, incluir_ilimitados=True):
        """Zera a quantidade de TODOS os itens (ou só dos produtos em `produto_ids`).
        Itens de estoque ilimitado: com incluir_ilimitados deixam de ser ilimitados (quantidade 0); senão ficam como estão.
        Grava um snapshot do estado anterior ANTES de alterar (dentro da mesma transação).
        Devolve {"itens", "unidades", "snapshot"} (snapshot None se nada precisou mudar)."""
        tabela, col, col_prod = self._alvo()
        consulta = f"SELECT {col}, quantidade, ilimitado, ativo FROM {tabela}"
        params = []
        if produto_ids is not None:
            ids = list(produto_ids)
            if not ids:
                return {"itens": 0, "unidades": 0, "snapshot": None}
            consulta += f" WHERE {col_prod} IN ({','.join('?' * len(ids))})"
            params = ids
        con = self._conectar()
        arquivo = None
        try:
            con.execute("BEGIN IMMEDIATE")           # a partir daqui o bot não escreve: o snapshot é fiel
            itens, unidades = [], 0
            for chave, qtd, ilim, ativo in con.execute(consulta, params).fetchall():
                if ilim and not incluir_ilimitados:
                    continue
                novo_ilim = 0
                if qtd == 0 and not ilim:
                    continue                          # já está zerado
                itens.append({"chave": chave, "antes": [int(qtd), int(ilim), int(ativo)],
                              "depois": [0, novo_ilim, int(ativo)]})
                unidades += 0 if ilim else int(qtd)
            if not itens:
                con.execute("ROLLBACK")
                return {"itens": 0, "unidades": 0, "snapshot": None}
            self.pasta_snapshots.mkdir(parents=True, exist_ok=True)
            arquivo = self.pasta_snapshots / f"zerar_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
            arquivo.write_text(json.dumps({
                "criado_em": _agora(), "modo": self.modo,
                "escopo": "tudo" if produto_ids is None else list(produto_ids),
                "incluiu_ilimitados": bool(incluir_ilimitados), "itens": itens, "restaurado_em": None,
            }, ensure_ascii=False), encoding="utf-8")
            agora = _agora()
            con.executemany(f"UPDATE {tabela} SET quantidade = 0, ilimitado = 0, atualizado_em = ? WHERE {col} = ?",
                            [(agora, i["chave"]) for i in itens])
            con.execute("COMMIT")
        except (sqlite3.Error, OSError) as e:
            self._rollback(con)
            if arquivo is not None:
                arquivo.unlink(missing_ok=True)
            raise EstoqueIndisponivel(f"Não consegui zerar o estoque (nada foi alterado): {e}") from e
        finally:
            con.close()
        self._registrar(acao="zerar tudo" if produto_ids is None else "zerar produtos", itens=len(itens),
                        unidades=unidades, snapshot=arquivo.name, produtos=None if produto_ids is None else list(produto_ids))
        return {"itens": len(itens), "unidades": unidades, "snapshot": arquivo.name}

    def zerar_pendente(self):
        """(arquivo, dados) do zerar mais recente que ainda não foi desfeito, ou None."""
        if not self.pasta_snapshots.is_dir():
            return None
        for arq in sorted(self.pasta_snapshots.glob("zerar_*.json"), reverse=True):
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not dados.get("restaurado_em"):
                return arq, dados
        return None

    def desfazer_zerar(self):
        """Devolve o estoque ao que era antes do último zerar. Um item só volta se continua zerado: se alguém
        mexeu nele depois (editou, reimportou, o bot estornou), é conflito e fica como está.
        Devolve {"restaurados", "conflitos": [chaves]}."""
        pendente = self.zerar_pendente()
        if pendente is None:
            raise EstoqueIndisponivel("Não há nenhum «zerar» para desfazer.")
        arquivo, dados = pendente
        tabela, col, _ = self._alvo()
        restaurados, conflitos = 0, []
        con = self._conectar()
        try:
            con.execute("BEGIN IMMEDIATE")
            agora = _agora()
            for it in dados["itens"]:
                qa, ia, _ = it["antes"]
                qd, id_, _ = it["depois"]
                cur = con.execute(
                    f"UPDATE {tabela} SET quantidade = ?, ilimitado = ?, atualizado_em = ? "
                    f"WHERE {col} = ? AND quantidade = ? AND ilimitado = ?",
                    (qa, ia, agora, it["chave"], qd, id_))
                if cur.rowcount == 1:
                    restaurados += 1
                else:
                    conflitos.append(it["chave"])
            con.execute("COMMIT")
        except sqlite3.Error as e:
            self._rollback(con)
            raise EstoqueIndisponivel(f"Não consegui desfazer (nada foi alterado): {e}") from e
        finally:
            con.close()
        dados["restaurado_em"] = _agora()
        try:
            arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self._registrar(acao="desfazer zerar", itens=restaurados, conflitos=len(conflitos), snapshot=arquivo.name)
        return {"restaurados": restaurados, "conflitos": conflitos}

    # ------------------------------------------------------------ registro
    def historico(self, limite=100):
        """Últimos eventos do registro, mais novos primeiro."""
        if not self.arquivo_log.exists():
            return []
        eventos = []
        try:
            linhas = self.arquivo_log.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for linha in reversed(linhas):
            try:
                eventos.append(json.loads(linha))
            except ValueError:
                continue
            if len(eventos) >= limite:
                break
        return eventos
