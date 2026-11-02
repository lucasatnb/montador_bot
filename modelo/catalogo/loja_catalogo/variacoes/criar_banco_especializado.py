"""Banco do estoque ESPECIALIZADO (produtos_especializados.db): criação, dados de exemplo e validação.

Uso (na pasta do bot):
    python criar_banco_especializado.py              cria o banco vazio (não mexe se já existir)
    python criar_banco_especializado.py --exemplo    cria e preenche com produtos de exemplo
    python criar_banco_especializado.py --validar    confere o banco contra constantes_especializado.py

Modelo: um PRODUTO (o que o cliente pede: "Pizza de Frango") tem uma ou mais SKUs (cada combinação
vendável: "Pizza de Frango, G, Catupiry"), e cada SKU tem preço e estoque próprios.
Produto sem variação (ex.: uma lata de refrigerante) é um produto com UMA sku e atributos {}.

    produtos(id, nome, ativo, atualizado_em)
    skus(sku, produto_id, atributos, preco, quantidade, ilimitado, ativo, atualizado_em)
    imagens(produto_id, ordem, url)

`skus.atributos` é um JSON com as chaves em ordem alfabética, ex.: {"cor":"Azul","tamanho":"M"}.
Sempre monte esse texto com atributos_json(): assim a restrição UNIQUE(produto_id, atributos) barra
combinação repetida do mesmo produto.

O SKU segue o formato ID[_CODIGO...], por exemplo P010_M_AZ. O item de carrinho segue
ID_QTD_CODIGO... (por exemplo P010_2_M_AZ) e deve ser decodificado contra as SKUs do catálogo.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

from pathlib import Path
for _pai in Path(__file__).resolve().parents:      # raiz do bot: a pasta que tem o pacote estoque/
    if (_pai / "estoque").is_dir():
        sys.path.insert(0, str(_pai))
        break
from variacoes import constantes_especializado as ce
from estoque.utilidades import normalizar

CAMINHO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "produtos_especializados.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    id            TEXT PRIMARY KEY,
    nome          TEXT NOT NULL,
    ativo         INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS skus (
    sku           TEXT PRIMARY KEY CHECK (sku NOT GLOB '*[ ,]*' AND length(sku) > 0),
    produto_id    TEXT NOT NULL REFERENCES produtos(id),
    atributos     TEXT NOT NULL DEFAULT '{}',
    preco         REAL NOT NULL CHECK (preco >= 0),
    quantidade    INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
    ilimitado     INTEGER NOT NULL DEFAULT 0,
    ativo         INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (produto_id, atributos)
);
CREATE TABLE IF NOT EXISTS imagens (
    produto_id TEXT NOT NULL REFERENCES produtos(id),
    ordem      INTEGER NOT NULL,
    url        TEXT NOT NULL,
    PRIMARY KEY (produto_id, ordem)
);
CREATE INDEX IF NOT EXISTS idx_skus_produto ON skus(produto_id);
"""


def atributos_json(atributos: dict) -> str:
    """Texto canônico gravado em skus.atributos (chaves ordenadas, sem espaços)."""
    return json.dumps(atributos, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def conectar(caminho: str = CAMINHO) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def criar(caminho: str = CAMINHO) -> None:
    con = conectar(caminho)
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ dados de exemplo
# (id, nome) e (sku, produto_id, atributos, preco, quantidade)
_PRODUTOS = [("P010", "Blusa"), ("P011", "Calça Jeans"), ("P020", "Pizza de Frango"), ("P030", "Refrigerante Lata")]
_SKUS = [
    ("P010_M_AZ", "P010", {"tamanho": "M", "cor": "Azul"}, 89.90, 5),
    ("P010_M_AM", "P010", {"tamanho": "M", "cor": "Amarelo"}, 89.90, 3),
    ("P010_G_AZ", "P010", {"tamanho": "G", "cor": "Azul"}, 89.90, 0),
    ("P010_G_AM", "P010", {"tamanho": "G", "cor": "Amarelo"}, 89.90, 4),
    ("P010_GG_AM", "P010", {"tamanho": "GG", "cor": "Amarelo"}, 99.90, 2),
    ("P011_40_PT", "P011", {"numeracao": "40", "cor": "Preto"}, 159.90, 6),
    ("P011_42_PT", "P011", {"numeracao": "42", "cor": "Preto"}, 159.90, 2),
    ("P011_42_AZ", "P011", {"numeracao": "42", "cor": "Azul"}, 159.90, 1),
    ("P020_M_SB", "P020", {"tamanho": "M", "borda": "Sem borda"}, 38.00, 10),
    ("P020_M_CA", "P020", {"tamanho": "M", "borda": "Catupiry"}, 43.00, 10),
    ("P020_G_SB", "P020", {"tamanho": "G", "borda": "Sem borda"}, 52.00, 10),
    ("P020_G_CA", "P020", {"tamanho": "G", "borda": "Catupiry"}, 58.00, 10),
    ("P030", "P030", {}, 6.00, 40),
]


def preencher_exemplo(caminho: str = CAMINHO) -> None:
    con = conectar(caminho)
    try:
        con.executemany("INSERT OR IGNORE INTO produtos (id, nome) VALUES (?, ?)", _PRODUTOS)
        con.executemany(
            "INSERT OR IGNORE INTO skus (sku, produto_id, atributos, preco, quantidade) VALUES (?, ?, ?, ?, ?)",
            [(s, p, atributos_json(a), preco, q) for s, p, a, preco, q in _SKUS])
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ validação
RE_ID = re.compile(r"^[A-Z][0-9]{3}$")
RE_SKU = re.compile(r"^[A-Z][0-9]{3}(?:_[A-Z0-9]+)*$")


def validar(caminho: str = CAMINHO) -> list:
    """Confere o banco contra constantes_especializado.py. Devolve uma lista de problemas em texto
    (vazia = tudo certo). Serve também para o repositório chamar ao carregar o catálogo."""
    problemas = []

    # as próprias constantes
    for tipo, opcoes in ce.VARIANTES.items():
        if tipo != normalizar(tipo).replace(" ", ""):
            problemas.append(f"constantes: o tipo '{tipo}' deve ser minúsculo, sem acento e sem espaço")
        if len(set(opcoes)) != len(opcoes):
            problemas.append(f"constantes: o tipo '{tipo}' tem opção repetida")
    todas = {o for ops in ce.VARIANTES.values() for o in ops}
    for tipo, opcoes in ce.VARIANTES.items():
        mapa = ce.CODIGOS.get(tipo, {})
        faltam_codigos = [o for o in opcoes if o not in mapa]
        if faltam_codigos:
            problemas.append(f"constantes: faltam códigos para {tipo}: {', '.join(faltam_codigos)}")
        codigos = [mapa[o] for o in opcoes if o in mapa]
        if any(not re.fullmatch(r"[A-Z0-9]+", str(c)) for c in codigos):
            problemas.append(f"constantes: códigos de '{tipo}' devem conter apenas A-Z e 0-9, sem underline")
        if len(set(codigos)) != len(codigos):
            problemas.append(f"constantes: há códigos repetidos no tipo '{tipo}'")
    if set(ce.CODIGOS) - set(ce.VARIANTES):
        problemas.append("constantes: CODIGOS contém tipos ausentes em VARIANTES")
    for texto, oficial in ce.SINONIMOS.items():
        if texto != normalizar(texto):
            problemas.append(f"constantes: o sinônimo '{texto}' deve estar sem acento e em minúsculas")
        if oficial not in todas:
            problemas.append(f"constantes: o sinônimo '{texto}' aponta para '{oficial}', que não existe em VARIANTES")

    # o banco
    con = conectar(caminho)
    try:
        linhas = con.execute("SELECT s.sku, s.produto_id, s.atributos FROM skus s "
                             "JOIN produtos p ON p.id = s.produto_id WHERE s.ativo = 1 AND p.ativo = 1").fetchall()
        orfas = con.execute("SELECT sku FROM skus WHERE produto_id NOT IN (SELECT id FROM produtos)").fetchall()
        sem_sku = con.execute("SELECT id, nome FROM produtos WHERE ativo = 1 AND id NOT IN "
                              "(SELECT produto_id FROM skus WHERE ativo = 1)").fetchall()
    finally:
        con.close()

    for (sku,) in orfas:
        problemas.append(f"sku '{sku}': o produto dela não existe")
    for pid, nome in sem_sku:
        problemas.append(f"produto {pid} ({nome}): não tem nenhuma sku ativa, então o bot não consegue vendê-lo")

    tipos_por_produto: dict = {}
    for sku, pid, texto in linhas:
        if not RE_ID.fullmatch(pid):
            problemas.append(f"produto '{pid}': ID inválido; esperado uma letra e três dígitos (ex.: P001)")
        if not RE_SKU.fullmatch(sku):
            problemas.append(f"sku '{sku}': formato inválido; esperado ID[_CODIGO...], sem hífens nem espaços")
        if not sku.startswith(pid):
            problemas.append(f"sku '{sku}': não começa com o ID do produto '{pid}'")
        try:
            atributos = json.loads(texto)
            if not isinstance(atributos, dict):
                raise ValueError
        except ValueError:
            problemas.append(f"sku '{sku}': atributos não é um JSON de objeto: {texto!r}")
            continue
        if atributos_json(atributos) != texto:
            problemas.append(f"sku '{sku}': atributos fora do formato canônico (use atributos_json()); "
                             f"esperado {atributos_json(atributos)!r}")
        for tipo, opcao in atributos.items():
            if tipo not in ce.VARIANTES:
                problemas.append(f"sku '{sku}': o tipo '{tipo}' não existe em VARIANTES")
            elif opcao not in ce.VARIANTES[tipo]:
                parecida = next((o for o in ce.VARIANTES[tipo] if normalizar(o) == normalizar(str(opcao))), None)
                dica = f" (você quis dizer '{parecida}'?)" if parecida else ""
                problemas.append(f"sku '{sku}': a opção '{opcao}' não existe em VARIANTES['{tipo}']{dica}")
        tipos_por_produto.setdefault(pid, {}).setdefault(frozenset(atributos), []).append(sku)

    # todas as skus de um produto precisam ter os MESMOS tipos, senão o bot não sabe o que perguntar
    for pid, grupos in tipos_por_produto.items():
        if len(grupos) > 1:
            descricao = "; ".join(f"{sorted(t) or 'sem variação'}: {', '.join(skus)}" for t, skus in grupos.items())
            problemas.append(f"produto {pid}: as skus não têm os mesmos tipos de variação ({descricao})")
    return problemas


# ------------------------------------------------------------------ linha de comando
def _principal(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exemplo", action="store_true", help="preenche com produtos de exemplo")
    ap.add_argument("--validar", action="store_true", help="só valida o banco existente")
    ap.add_argument("--caminho", default=CAMINHO, help="arquivo do banco (padrão: produtos_especializados.db)")
    args = ap.parse_args(argv)

    if args.validar:
        if not os.path.exists(args.caminho):
            print(f"Não achei '{args.caminho}'. Rode sem --validar para criá-lo.")
            return 1
    else:
        existia = os.path.exists(args.caminho)
        criar(args.caminho)
        print(f"Banco {'já existia (tabelas conferidas)' if existia else 'criado'}: {args.caminho}")
        if args.exemplo:
            preencher_exemplo(args.caminho)
            print("Produtos de exemplo inseridos (os que já existiam foram mantidos).")

    problemas = validar(args.caminho)
    if problemas:
        print(f"\n{len(problemas)} problema(s):")
        for p in problemas:
            print(" -", p)
        return 1
    print("Validação: tudo certo.")
    return 0


if __name__ == "__main__":
    sys.exit(_principal())
