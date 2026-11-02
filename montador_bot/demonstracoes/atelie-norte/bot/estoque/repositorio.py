"""Repositório do estoque: TODO o SQL do bot fica isolado aqui.

O formato do banco é detectado sozinho (existe a tabela `skus`?). Dois formatos:

(A) Modo "especializado" (variações cor/tamanho/...): produtos_especializados.db
    produtos(id, nome, ativo, atualizado_em)                  -> produto-base ("Blusa")
    skus(sku, produto_id, atributos JSON, preco, quantidade,
         ilimitado, ativo, atualizado_em)                     -> o que é VENDIDO ("A001_PR_G")
    imagens(produto_id, ordem, url)                           -> imagens do produto-base
    imagens_sku(sku, ordem, url)                              -> imagens de cada SKU

(B) Formato simples (sem variações):
    produtos(id, nome, preco, quantidade, ilimitado, ativo, atualizado_em)
    imagens(produto_id, ordem, url)
    Cada produto vira um produto-base com UM SKU de mesmo id e sem atributos: o resto do bot
    (busca, código do carrinho, confirmação) funciona igual, só não pergunta cor/tamanho.

- O banco é a fonte da verdade. Este módulo mantém uma cópia do catálogo em memória
  (um "snapshot" imutável, `Catalogo`) e só a relê quando o arquivo do banco muda
  (os.path.getmtime), em vez de reler tudo a cada mensagem.
- O cliente PROCURA pelo produto-base e COMPRA um SKU: preço, estoque e baixa são sempre do SKU.
  O preço do SKU já inclui o acréscimo (acrescimos.json), então o bot não precisa dele.
- O desconto de estoque é atômico e tudo-ou-nada, direto no banco.
- Opcional: se existir catalogo.db na mesma pasta, a categoria de cada produto é usada para
  distinguir produtos com o MESMO nome (ex.: "BLUSA" masculina e "Blusa" feminina).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from .constantes import ARQ_CATALOGO, JANELA_RELEITURA_S, RE_E_MAIS_PALAVRA
from .modelos import BancoInvalido, Produto
from .utilidades import nome_variacao, normalizar


class Catalogo(NamedTuple):
    """Fotografia do catálogo num instante. É trocada por inteiro (nunca editada pela metade),
    então quem pegou uma referência sempre enxerga um conjunto consistente."""
    produtos: list                # [Produto-base] com ao menos um SKU ativo, na ordem do banco
    por_id: dict                  # id do produto-base -> Produto-base
    nomes: list                   # nome normalizado (original) de cada produto-base, mesmo índice de `produtos`
    nomes_com_conectivo: list     # [(índice, nome normalizado)] dos nomes que contêm " e "/" mais "
    ids_casefold: dict            # sku.casefold() -> [Produto-SKU]  (usado pelo código do carrinho)
    skus: dict                    # sku -> Produto-SKU


_VAZIO = Catalogo([], {}, [], [], {}, {})


def _mtime(caminho: str) -> float:
    try:
        return os.path.getmtime(caminho)
    except OSError:
        return 0.0


class EstoqueRepository:
    def __init__(self, caminho: str, caminho_catalogo: Optional[str] = None,
                 base_imagens: Optional[str] = None):
        self.caminho = caminho
        pasta = os.path.dirname(os.path.abspath(caminho))
        self.caminho_catalogo = caminho_catalogo or os.path.join(pasta, ARQ_CATALOGO)
        self.base_imagens = base_imagens or pasta   # as imagens do banco são caminhos relativos a esta pasta
        self._catalogo: Catalogo = _VAZIO
        self._especializado = True                 # formato detectado na última leitura (ver _carregar)
        self._assinatura: Optional[tuple] = None   # mtimes (banco, -wal, catalogo.db) na última leitura
        self._trava = threading.RLock()            # protege só a releitura/troca do catálogo
        self._carregar()                           # falha cedo (BancoInvalido) se o banco não existir

    # ================= acesso ao catálogo em memória =================
    @property
    def catalogo(self) -> Catalogo:
        return self._catalogo

    @property
    def produtos(self) -> list:
        return self._catalogo.produtos

    @property
    def por_id(self) -> dict:
        return self._catalogo.por_id

    @property
    def skus(self) -> dict:
        return self._catalogo.skus

    # ================= conexão =================
    def _conectar(self) -> sqlite3.Connection:
        """Abre uma conexão curta (uma por operação). Não cria o arquivo se ele não existir."""
        if not os.path.exists(self.caminho):
            raise BancoInvalido(f"não achei o banco '{self.caminho}'. Gere o banco antes de iniciar o bot.")
        con = sqlite3.connect(self.caminho, timeout=10, isolation_level=None)  # transações manuais
        con.execute("PRAGMA foreign_keys = ON")
        return con

    # ================= cache de leitura (mtime) =================
    def _ler_assinatura(self) -> tuple:
        """(mtime do .db, mtime do -wal, mtime do catalogo.db). Se o banco usa WAL, as escritas
        aparecem primeiro no arquivo -wal; olhar só o .db deixaria o cache velho passar despercebido."""
        try:
            principal = os.path.getmtime(self.caminho)
        except OSError:
            raise BancoInvalido(f"não achei o banco '{self.caminho}'. Gere o banco antes de iniciar o bot.")
        return (principal, _mtime(self.caminho + "-wal"), _mtime(self.caminho_catalogo))

    def atualizar(self) -> bool:
        """Relê o banco SÓ se o arquivo mudou desde a última leitura (ou mudou há pouquíssimo
        tempo; ver JANELA_RELEITURA_S). Devolve True se releu. Barato no caso comum: alguns stat()."""
        assinatura = self._ler_assinatura()
        if assinatura == self._assinatura and (time.time() - max(assinatura)) > JANELA_RELEITURA_S:
            return False
        with self._trava:
            # outra thread pode ter relido enquanto esperávamos a trava
            assinatura = self._ler_assinatura()
            if assinatura == self._assinatura and (time.time() - max(assinatura)) > JANELA_RELEITURA_S:
                return False
            self._carregar()
            return True

    def _caminho_imagem(self, url: str) -> str:
        """Imagem do banco ('imagens/A001/01.webp') -> caminho completo. URLs e caminhos absolutos passam direto."""
        if "://" in url or os.path.isabs(url):
            return url
        return os.path.normpath(os.path.join(self.base_imagens, url))

    def _ler_categorias(self) -> dict:
        """id do produto -> categoria, lida do catalogo.db (somente leitura). Opcional: {} se não existir."""
        if not os.path.exists(self.caminho_catalogo):
            return {}
        try:
            con = sqlite3.connect(Path(self.caminho_catalogo).resolve().as_uri() + "?mode=ro",
                                  uri=True, timeout=10)
            try:
                return {i: (c or "").strip() for i, c in con.execute("SELECT id, categoria FROM produtos")}
            finally:
                con.close()
        except sqlite3.Error:
            logging.warning("não consegui ler as categorias em '%s'; sigo sem elas", self.caminho_catalogo)
            return {}

    def _carregar(self):
        """(Re)lê os produtos e SKUs ativos. Atualiza os objetos Produto já existentes NO LUGAR,
        para que conversas pendentes (que guardam esses objetos) enxerguem o estoque atual."""
        with self._trava:
            # A assinatura é lida ANTES da consulta: se o arquivo mudar durante a leitura,
            # a próxima chamada de atualizar() percebe e relê.
            assinatura = self._ler_assinatura()
            con = self._conectar()
            try:
                self._especializado = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'skus'").fetchone() is not None
                img_base: dict[str, list] = {}
                img_sku: dict[str, list] = {}
                if self._especializado:
                    bases_db = con.execute("SELECT id, nome FROM produtos WHERE ativo = 1 ORDER BY rowid").fetchall()
                    skus_db = con.execute("SELECT sku, produto_id, atributos, preco, quantidade, ilimitado "
                                          "FROM skus WHERE ativo = 1 ORDER BY rowid").fetchall()
                    for sku, url in con.execute("SELECT sku, url FROM imagens_sku ORDER BY sku, ordem"):
                        img_sku.setdefault(sku, []).append(url)
                else:   # formato simples: cada produto é um produto-base com um único SKU (mesmo id)
                    linhas = con.execute("SELECT id, nome, preco, quantidade, ilimitado FROM produtos "
                                         "WHERE ativo = 1 ORDER BY rowid").fetchall()
                    bases_db = [(i, n) for i, n, *_ in linhas]
                    skus_db = [(i, i, "{}", preco, qtd, ilim) for i, _, preco, qtd, ilim in linhas]
                for pid, url in con.execute("SELECT produto_id, url FROM imagens ORDER BY produto_id, ordem"):
                    img_base.setdefault(pid, []).append(url)
            except sqlite3.Error as e:
                raise BancoInvalido(f"o banco '{self.caminho}' não está no formato esperado ({e}).")
            finally:
                con.close()
            categorias = self._ler_categorias()

            nome_da_base = dict(bases_db)
            skus_da_base: dict[str, list] = {}
            for sku, pid, atrib_json, preco, qtd, ilim in skus_db:
                if pid not in nome_da_base:
                    continue   # SKU ativo de produto desativado: não é vendável
                try:
                    atributos = json.loads(atrib_json)
                    if not isinstance(atributos, dict):
                        raise ValueError("não é um objeto")
                except ValueError:
                    logging.warning("SKU '%s' ignorado: atributos inválidos (%r)", sku, atrib_json)
                    continue
                skus_da_base.setdefault(pid, []).append((sku, atributos, preco, qtd, ilim))

            ordem = [(id_, nome) for id_, nome in bases_db if id_ in skus_da_base]   # base sem SKU não vende
            # Nomes repetidos (ex.: "BLUSA" e "Blusa") precisam de um rótulo para o cliente distinguir.
            repetidos = {n for n, c in Counter(normalizar(nome) for _, nome in ordem).items() if c > 1}

            antigos_bases, antigos_skus = self._catalogo.por_id, self._catalogo.skus
            produtos, skus, nomes = [], {}, []
            for id_, nome in ordem:
                extra = f" ({categorias.get(id_) or id_})" if normalizar(nome) in repetidos else ""
                variacoes = []
                for sku, atributos, preco, qtd, ilim in skus_da_base[id_]:
                    s = antigos_skus.get(sku) or Produto(id=sku)
                    s.nome = nome_variacao(nome, atributos) + extra
                    s.preco = float(preco)
                    s.ilimitado = bool(ilim)
                    s.quantidade = float("inf") if ilim else int(qtd)
                    s.atributos, s.base_id, s.nome_base = atributos, id_, nome
                    s.imagens = [self._caminho_imagem(u) for u in (img_sku.get(sku) or img_base.get(id_, []))]
                    s.variacoes = []
                    skus[sku] = s
                    variacoes.append(s)
                b = antigos_bases.get(id_) or Produto(id=id_)
                b.nome = nome + extra
                b.variacoes = variacoes
                b.preco = min(v.preco for v in variacoes)                 # base: o MENOR preço entre os SKUs
                b.ilimitado = any(v.ilimitado for v in variacoes)
                b.quantidade = float("inf") if b.ilimitado else sum(v.quantidade for v in variacoes)
                b.imagens = [self._caminho_imagem(u) for u in img_base.get(id_, [])]
                produtos.append(b)
                nomes.append(normalizar(nome))   # a busca usa o nome ORIGINAL (sem o rótulo de desempate)

            ids_casefold: dict[str, list] = {}
            for s in skus.values():
                ids_casefold.setdefault(s.id.casefold(), []).append(s)
            self._catalogo = Catalogo(
                produtos=produtos,
                por_id={p.id: p for p in produtos},
                nomes=nomes,
                nomes_com_conectivo=[(i, n) for i, n in enumerate(nomes) if RE_E_MAIS_PALAVRA.search(n)],
                ids_casefold=ids_casefold,
                skus=skus,
            )
            self._assinatura = assinatura

    def _recarregar_apos_escrita(self):
        """Depois de uma escrita nossa o cache está velho por definição: relê já.
        Se a releitura falhar, a escrita JÁ foi confirmada; só invalida o cache para
        a próxima mensagem tentar de novo."""
        try:
            self._carregar()
        except BancoInvalido:
            logging.exception("escrita confirmada, mas não consegui reler o catálogo")
            self._assinatura = None

    # ================= escrita =================
    @staticmethod
    def _agora() -> str:
        return datetime.now().isoformat(timespec="seconds")   # mesmo formato do atualizado_em do painel

    def baixar(self, pedidos) -> Optional[Produto]:
        """Desconta do banco, tudo ou nada. `pedidos` = [(Produto-SKU, qtd)] (estoque infinito não é descontado).
        O UPDATE só vale se ainda houver a quantidade pedida: protege contra venda a mais
        caso o estoque tenha mudado desde que o cliente foi consultado.
        Devolve None se deu certo, ou o Produto cujo estoque mudou (nada foi descontado).
        Erros de banco sobem como BancoInvalido."""
        con = None
        falhou = None
        try:
            con = self._conectar()
            con.execute("BEGIN IMMEDIATE")
            agora = self._agora()
            for p, q in pedidos:
                if p.ilimitado:
                    continue
                if self._especializado:
                    cur = con.execute("UPDATE skus SET quantidade = quantidade - ?, atualizado_em = ? "
                                      "WHERE sku = ? AND ativo = 1 AND ilimitado = 0 AND quantidade >= ? "
                                      "AND produto_id IN (SELECT id FROM produtos WHERE ativo = 1)",
                                      (q, agora, p.id, q))
                else:
                    cur = con.execute("UPDATE produtos SET quantidade = quantidade - ? "
                                      "WHERE id = ? AND ativo = 1 AND ilimitado = 0 AND quantidade >= ?",
                                      (q, p.id, q))
                if cur.rowcount != 1:   # acabou/mudou nesse meio tempo: desfaz tudo
                    con.execute("ROLLBACK")
                    falhou = p
                    break
            else:
                con.execute("COMMIT")
        except sqlite3.Error as e:
            if con is not None and con.in_transaction:
                con.execute("ROLLBACK")
            raise BancoInvalido(f"erro ao descontar o estoque em '{self.caminho}': {e}") from e
        finally:
            if con is not None:
                con.close()
        self._recarregar_apos_escrita()   # reflete o novo estoque nos objetos (r.estoques)
        return falhou

    def estornar(self, sku: str, qtd: int = 1) -> bool:
        """Devolve unidades de um SKU ao estoque (ex.: pagamento não confirmado).
        Para um pedido com vários itens, chame uma vez para cada (Produto, qtd) de r.itens."""
        try:
            con = self._conectar()
            try:
                tabela, chave = ("skus", "sku") if self._especializado else ("produtos", "id")
                linha = con.execute(f"SELECT ilimitado FROM {tabela} WHERE {chave} = ?", (sku,)).fetchone()
                if linha is None:
                    raise KeyError(sku)
                if linha[0]:
                    return True  # estoque infinito: nada a devolver
                con.execute("BEGIN IMMEDIATE")
                con.execute(f"UPDATE {tabela} SET quantidade = quantidade + ? WHERE {chave} = ?", (qtd, sku))
                if self._especializado:
                    con.execute("UPDATE skus SET atualizado_em = ? WHERE sku = ?", (self._agora(), sku))
                con.execute("COMMIT")
            finally:
                con.close()   # fecha a conexão; transação aberta (se houve erro) é descartada
        except (sqlite3.Error, BancoInvalido):
            return False
        self._recarregar_apos_escrita()
        return True
