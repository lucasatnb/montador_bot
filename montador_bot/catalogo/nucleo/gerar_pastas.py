"""
gerar_pastas.py  --  Camada de dados do catálogo. O montador tem UMA loja só: catalogo/loja/.

Para montar o bot de outro cliente, use "Zerar loja" na aba do catálogo (nada é apagado: vai para _arquivo/).

    loja/
        config.json                      nome da loja e modo de estoque (simples | especializado)
        catalogo.db                      FONTE do catálogo: produtos, fotos, acréscimos (gravado direto pela interface)
        produtos.db                      estoque do modo simples (o bot usa; gravado direto pela interface)
        produtos_especializados.db       estoque do modo especializado (idem)
        imagens/<ID>/01.jpg ...          fotos GERAIS do item (só desta loja)
        imagens/<ID>/<tipo>/<opção>/     fotos de uma variação, ex.: imagens/P001/cor/Verde/01.jpg
                                         (modo especializado; cada SKU usa as gerais + as das suas opções)
        acrescimos.json                  acréscimos de preço por opção de variação (modo especializado)
        atributos.json                   categorias/opções/códigos de variação da loja (só cresce; ver atributos_loja.py)
        site/                            o site gerado pelo criador de site (criador_site/); NÃO vai para dentro do bot
        backups/  _arquivo/              cópias de segurança / dados zerados (nada é apagado)

Quem usa isto é a interface_catalogo.py (ela cria a loja, as pastas e os bancos sozinha).

"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# --- configuração -----------------------------------------------------------
BASE = Path(__file__).resolve().parents[1]      # pasta catalogo/ (onde ficam loja/ e atributos_padrao.json)
PASTA_LOJA = BASE / "loja"                      # a única loja do montador
EXTENSOES = {".jpg", ".jpeg", ".png", ".webp"}

MODO_SIMPLES = "simples"
MODO_ESP = "especializado"
NOMES_MODO = {MODO_SIMPLES: "Simples", MODO_ESP: "Especializado (com variações)"}

# arquivos que pertencem a uma loja (usado para zerar e para copiar o catálogo antigo)
ARQUIVOS_DA_LOJA = (
    "catalogo.db", "produtos.db", "produtos_especializados.db", "acrescimos.json",
    "grupos_categorias.json",
)
# -----------------------------------------------------------------------------


class ErroDados(Exception):
    """Problema que a pessoa consegue resolver (mensagem em linguagem simples)."""


# ================================ textos e números ============================

def sem_acento(texto):
    s = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def nome_pasta(id_produto):
    """Troca caracteres que o Windows não aceita em nome de pasta."""
    return re.sub(r'[\\/:*?"<>|]', "_", str(id_produto)).strip(" .")


# ==================================== LOJA ====================================

@dataclass(frozen=True)
class Loja:
    raiz: Path

    # --- caminhos (tudo dentro da pasta da loja) ---
    @property
    def slug(self):
        return self.raiz.name

    @property
    def db(self):
        return self.raiz / "catalogo.db"

    def banco_estoque(self, modo=None):
        """Banco que o BOT usa e desconta a cada venda (criado pelos importadores)."""
        return self.raiz / ("produtos_especializados.db" if (modo or self.modo) == MODO_ESP else "produtos.db")

    @property
    def arquivo_atributos(self):
        """Vocabulário de variações da loja (categorias, opções, códigos). NÃO é movido ao zerar a loja."""
        return self.raiz / "atributos.json"

    @property
    def arquivo_acrescimos(self):
        return self.raiz / "acrescimos.json"

    @property
    def imagens(self):
        return self.raiz / "imagens"

    @property
    def backups(self):
        return self.raiz / "backups"

    @property
    def arquivo_config(self):
        return self.raiz / "config.json"

    def pasta_produto(self, id_produto):
        """imagens/<ID>/ desta loja (None se o ID não serve como nome de pasta)."""
        nome = nome_pasta(id_produto)
        return self.imagens / nome if nome else None

    def caminho_pasta(self, id_produto):
        """Caminho relativo à pasta da loja, como vai nas planilhas: imagens/<ID>/"""
        return f"{self.imagens.name}/{nome_pasta(id_produto)}/"

    def pasta_atributo(self, id_produto, tipo, opcao):
        """imagens/<ID>/<tipo>/<opção>/ : fotos de UMA opção de variação (None se algum nome não serve de pasta)."""
        base = self.pasta_produto(id_produto)
        t, o = nome_pasta(tipo), nome_pasta(opcao)
        return base / t / o if base and t and o else None

    def caminho_relativo(self, arquivo):
        """Caminho de um arquivo relativo à pasta da loja, como vai nas planilhas (sempre com /)."""
        return Path(arquivo).relative_to(self.raiz).as_posix()

    # --- configuração ---
    def _config(self):
        try:
            dados = json.loads(self.arquivo_config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return dados if isinstance(dados, dict) else {}

    def _gravar_config(self, **novos):
        dados = self._config()
        dados.update(novos)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.arquivo_config.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def nome(self):
        return self._config().get("nome") or self.slug

    @property
    def modo(self):
        modo = self._config().get("modo")
        return modo if modo in NOMES_MODO else None

    @property
    def orcamento(self):
        """Loja POR ORÇAMENTO (a loja inteira, não item a item): o site mostra "A combinar" no lugar dos preços e o bot
        pede o endereço e fecha a comanda como visita. Fica em config.json ("orcamento": true); o site e o bot leem de lá."""
        return bool(self._config().get("orcamento"))

    def definir_orcamento(self, ligado):
        self._gravar_config(orcamento=bool(ligado))

    def definir_nome(self, nome):
        nome = " ".join(str(nome or "").split())
        if not nome:
            raise ValueError("o nome da loja não pode ficar vazio")
        self._gravar_config(nome=nome)

    def definir_modo(self, modo):
        if modo not in NOMES_MODO:
            raise ValueError(f"modo desconhecido: {modo}")
        self._gravar_config(modo=modo)


def loja_atual():
    """A loja do montador (catalogo/loja/), ou None se ainda não foi criada (falta config.json)."""
    loja = Loja(PASTA_LOJA)
    return loja if loja.arquivo_config.is_file() else None


def criar_loja(nome, modo=None):
    """Cria a loja única (config + pasta de imagens). Nunca sobrescreve: se já existe, avisa."""
    nome = " ".join(str(nome or "").split())
    if not nome:
        raise ErroDados("Digite um nome para a loja.")
    if modo is not None and modo not in NOMES_MODO:
        raise ValueError(f"modo desconhecido: {modo}")
    loja = Loja(PASTA_LOJA)
    if loja.arquivo_config.is_file():
        raise ErroDados("A loja já existe. Para começar outra, use «Zerar loja».")
    loja.raiz.mkdir(parents=True, exist_ok=True)
    loja.imagens.mkdir(exist_ok=True)
    loja._gravar_config(nome=nome, **({"modo": modo} if modo else {}))
    return loja


def zerar_loja(loja):
    """Recomeça a loja do zero SEM apagar nada: catálogo, fotos e bancos vão para _arquivo/<data>/.
    O nome, o modo e o vocabulário de atributos (atributos.json) ficam."""
    destino = loja.raiz / "_arquivo" / f"{datetime.now():%Y%m%d_%H%M%S}"
    destino.mkdir(parents=True)
    itens = [loja.raiz / n for n in ARQUIVOS_DA_LOJA] + [loja.imagens, loja.raiz / "site"]   # site/ = o site gerado
    try:
        for item in itens:
            if item.exists():
                shutil.move(str(item), str(destino / item.name))
    except PermissionError:
        raise PermissionError("Feche as planilhas no Excel e o catalogo.db em outros programas e tente de novo. "
                              "Se algo já foi movido, está em " + str(destino.relative_to(BASE))) from None
    loja.imagens.mkdir(exist_ok=True)
    return destino


# ================================ fotos =======================================

def chave_ordem(arquivo):
    """01.jpg, 02.jpg, ..., 10.jpg na ordem certa; nomes não numéricos vêm depois."""
    if arquivo.stem.isdigit():
        return (0, int(arquivo.stem), arquivo.name)
    return (1, 0, arquivo.name.lower())


def listar_imagens(pasta):
    if pasta is None or not pasta.is_dir():
        return []
    return sorted(
        (f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in EXTENSOES),
        key=chave_ordem,
    )


def salvar_imagens(pasta, arquivos):
    """Grava os uploads como 01.jpg, 02.png... Fotos idênticas às já existentes são ignoradas."""
    pasta.mkdir(parents=True, exist_ok=True)
    existentes = listar_imagens(pasta)
    hashes = {hashlib.md5(f.read_bytes()).hexdigest() for f in existentes}
    proximo = 1 + max((int(f.stem) for f in existentes if f.stem.isdigit()), default=0)
    novos = repetidos = 0
    for arq in arquivos:
        dados = arq.getvalue()
        h = hashlib.md5(dados).hexdigest()
        if h in hashes:
            repetidos += 1
            continue
        ext = Path(arq.name).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        (pasta / f"{proximo:02d}{ext}").write_bytes(dados)
        hashes.add(h)
        proximo += 1
        novos += 1
    return novos, repetidos


# ====================== preço por variação (acréscimos) ========================
# Preço de uma SKU = preço base do produto + soma dos acréscimos das opções dela, só nos atributos marcados
# como "afeta o preço". Guardado em acrescimos.json:
#   {"A000": {"cor": {"afeta": true, "opcoes": {"Verde": 0.0, "Amarela": 5.0}}, "modelo": {"afeta": false, "opcoes": {}}}}

def ler_acrescimos(loja):
    try:
        dados = json.loads(loja.arquivo_acrescimos.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def acrescimos_do_produto(loja, id_produto):
    """{tipo: {"afeta": bool, "opcoes": {opção: valor}}} do produto ({} se nunca foi configurado)."""
    return ler_acrescimos(loja).get(str(id_produto).strip().upper(), {})


def gravar_acrescimos_produto(loja, id_produto, acrescimos):
    """Grava (ou, se `acrescimos` está vazio, remove) a configuração de preço por variação do produto."""
    dados = ler_acrescimos(loja)
    chave = str(id_produto).strip().upper()
    if acrescimos:
        dados[chave] = acrescimos
    else:
        dados.pop(chave, None)
    loja.raiz.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="acrescimos_", suffix=".tmp", dir=str(loja.raiz))
    os.close(fd)
    try:
        Path(tmp).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, loja.arquivo_acrescimos)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def preco_do_sku(preco_base, atributos, acrescimos):
    """Preço base + acréscimos das opções da SKU (só dos atributos com 'afeta' ligado)."""
    total = float(preco_base)
    for tipo, opcao in atributos.items():
        regra = acrescimos.get(tipo) or {}
        if regra.get("afeta"):
            total += float((regra.get("opcoes") or {}).get(opcao, 0) or 0)
    return round(total, 2)


def _ids_do_banco(caminho, tabela):
    """IDs da coluna id de uma tabela de um banco (vazio se o banco/tabela não existe ou está travado)."""
    if not caminho.exists():
        return set()
    try:
        con = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        try:
            return {str(r[0]).strip().upper() for r in con.execute(f"SELECT id FROM {tabela}")}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def ids_em_uso(loja, ids_catalogo=()):
    """Todo ID que a loja já usa em algum lugar: catálogo, bancos de estoque ou pasta de fotos.
    Serve para o ID novo nunca colidir com um produto (ou fotos) que já existe."""
    usados = {str(i).strip().upper() for i in ids_catalogo}
    usados |= _ids_do_banco(loja.db, "produtos")
    usados |= _ids_do_banco(loja.banco_estoque(MODO_SIMPLES), "produtos")
    usados |= _ids_do_banco(loja.banco_estoque(MODO_ESP), "produtos")
    if loja.imagens.is_dir():
        usados |= {d.name.upper() for d in loja.imagens.iterdir() if d.is_dir()}
    return usados


def fotos_do_sku(loja, id_produto, atributos, ordem_tipos, so_opcoes=None):
    """Fotos de uma SKU: primeiro as gerais do item, depois as de cada opção dela (na ordem de `ordem_tipos`).
    `so_opcoes` ({tipo: opções que TÊM fotos neste produto}) limita quais pastas de variação entram:
    opção fora dele não contribui, mesmo que sobre uma pasta antiga. None = todas as pastas que existirem.
    Devolve caminhos relativos à loja. É aqui que se muda a regra, se um dia precisar."""
    arquivos = list(listar_imagens(loja.pasta_produto(id_produto)))
    for tipo in ordem_tipos:
        if tipo in atributos and (so_opcoes is None or atributos[tipo] in so_opcoes.get(tipo, ())):
            arquivos += listar_imagens(loja.pasta_atributo(id_produto, tipo, atributos[tipo]))
    return [loja.caminho_relativo(f) for f in arquivos]


def aprovado(produto):
    return bool(str(produto["descricao"] or "").strip() and str(produto["categoria"] or "").strip())


def ler_catalogo(loja):
    """Produtos da loja, lidos do catalogo.db (a fonte do catálogo). FileNotFoundError se a loja ainda está vazia."""
    if not loja.db.exists():
        raise FileNotFoundError(loja.db.name)
    try:
        con = sqlite3.connect(f"{loja.db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        try:
            linhas = con.execute("SELECT id, nome, preco, descricao, categoria FROM produtos ORDER BY rowid").fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        if "no such table" in str(e):
            raise FileNotFoundError(loja.db.name) from None
        raise ValueError(f"Não consegui ler o catalogo.db ({e}). Ele está aberto em outro programa?") from None
    return [{"id": i, "nome": n, "preco": pr, "descricao": d, "categoria": c} for i, n, pr, d, c in linhas]


# ================================ catalogo.db =================================

def _criar_tabelas(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS produtos (
               id         TEXT PRIMARY KEY,
               nome       TEXT NOT NULL,
               preco      REAL,
               descricao  TEXT,
               categoria  TEXT,
               aprovado   INTEGER NOT NULL DEFAULT 0
           )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS imagens (
               id_produto TEXT NOT NULL REFERENCES produtos(id),
               ordem      INTEGER NOT NULL,
               caminho    TEXT NOT NULL,
               PRIMARY KEY (id_produto, ordem)
           )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS imagens_variacao (
               id_produto TEXT NOT NULL REFERENCES produtos(id),
               tipo       TEXT NOT NULL,
               opcao      TEXT NOT NULL,
               ordem      INTEGER NOT NULL,
               caminho    TEXT NOT NULL,
               PRIMARY KEY (id_produto, tipo, opcao, ordem)
           )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS acrescimos_variacao (
               id_produto TEXT NOT NULL REFERENCES produtos(id),
               tipo       TEXT NOT NULL,
               opcao      TEXT NOT NULL,
               acrescimo  REAL NOT NULL,
               PRIMARY KEY (id_produto, tipo, opcao)
           )"""
    )


def _sincronizar_produto(con, loja, p, todos_acrescimos):
    """Grava (ou atualiza) UM produto e refaz as fotos e acréscimos dele a partir das pastas e do acrescimos.json."""
    con.execute(
        "INSERT INTO produtos (id, nome, preco, descricao, categoria, aprovado) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, preco = excluded.preco, "
        "descricao = excluded.descricao, categoria = excluded.categoria, aprovado = excluded.aprovado",
        (
            p["id"],
            p["nome"],
            p["preco"],
            str(p["descricao"]).strip() if p["descricao"] else None,
            str(p["categoria"]).strip() if p["categoria"] else None,
            1 if aprovado(p) else 0,
        ),
    )
    for tabela in ("acrescimos_variacao", "imagens_variacao", "imagens"):
        con.execute(f"DELETE FROM {tabela} WHERE id_produto = ?", (p["id"],))
    for tipo, regra in todos_acrescimos.get(p["id"].upper(), {}).items():
        if regra.get("afeta"):
            for opcao, valor in (regra.get("opcoes") or {}).items():
                con.execute("INSERT INTO acrescimos_variacao VALUES (?, ?, ?, ?)",
                            (p["id"], tipo, opcao, float(valor or 0)))
    pasta = loja.pasta_produto(p["id"])
    for ordem, f in enumerate(listar_imagens(pasta), 1):
        con.execute("INSERT INTO imagens VALUES (?, ?, ?)",
                    (p["id"], ordem, f"{loja.imagens.name}/{pasta.name}/{f.name}"))
    if pasta.is_dir():   # fotos por variação: imagens/<ID>/<tipo>/<opção>/
        for pasta_tipo in sorted(d for d in pasta.iterdir() if d.is_dir()):
            for pasta_opcao in sorted(d for d in pasta_tipo.iterdir() if d.is_dir()):
                for ordem, f in enumerate(listar_imagens(pasta_opcao), 1):
                    con.execute("INSERT INTO imagens_variacao VALUES (?, ?, ?, ?, ?)",
                                (p["id"], pasta_tipo.name, pasta_opcao.name, ordem, loja.caminho_relativo(f)))


def gravar_produto_catalogo(loja, id_produto, nome, preco, descricao, categoria):
    """Grava o produto direto no catalogo.db (sem planilha). Chame DEPOIS de salvar as fotos e o acrescimos.json:
    as fotos e os acréscimos do produto são relidos das pastas/arquivo neste momento."""
    con = sqlite3.connect(loja.db, timeout=10)
    try:
        with con:
            _criar_tabelas(con)
            _sincronizar_produto(
                con, loja,
                {"id": id_produto, "nome": nome, "preco": preco, "descricao": descricao, "categoria": categoria},
                ler_acrescimos(loja))
    finally:
        con.close()


def gerar_db(loja, produtos):
    """Recria o catalogo.db da loja do zero a partir de `produtos` (lista de dicts) e das pastas (imagens).
    Na interface, `produtos` vem do próprio catalogo.db: serve para ressincronizar fotos e acréscimos."""
    con = sqlite3.connect(loja.db)
    try:
        with con:
            for tabela in ("acrescimos_variacao", "imagens_variacao", "imagens", "produtos"):
                con.execute(f"DROP TABLE IF EXISTS {tabela}")
            _criar_tabelas(con)
            todos_acrescimos = ler_acrescimos(loja)
            for p in produtos:
                _sincronizar_produto(con, loja, p, todos_acrescimos)
    finally:
        con.close()
