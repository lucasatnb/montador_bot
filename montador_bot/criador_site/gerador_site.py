"""
gerador_site.py  --  Gera o SITE (landing page estática) a partir do catálogo e dos SKUs.

No montador, a pasta de dados é a loja do catálogo (catalogo/loja/). Depende SOMENTE do que está nela (as três coisas ficam sempre juntas):
    catalogo.db                  produtos, fotos gerais e fotos de variação
    produtos_especializados.db   SKUs (cor x tamanho...), preço de cada SKU e estoque
    imagens/                     as fotos; os bancos guardam o caminho relativo a esta pasta (imagens/A000/01.webp)

Nada de atributos.json, categorias_ui.json, acrescimos.json, lojas/<slug>/ ou config_site.json. Do config.json da loja só se
leem, se existirem, o "nome" (nome padrão do site) e o "orcamento" (loja por orçamento: o site mostra "A combinar" no lugar dos preços):
  - rótulos e ordem das variações, ordem das categorias -> vêm da ordem em que aparecem nos bancos;
  - preço por variação                                  -> já está no preço de cada SKU (produtos_especializados.db);
  - modo (simples/especializado)                        -> especializado se o banco de SKUs tiver SKUs ativas;
  - nome da loja, WhatsApp, cores, molde e logo         -> ficam em duas tabelas do próprio catalogo.db
                                                           (site_config e site_logo), criadas na primeira gravação.

Escreve em <pasta de dados>/site/ :  index.html, style.css, core.js, script.js, dados.js, logo.*, imagens/...
O site é estático: abre direto no navegador, sem servidor.

Os 4 moldes (HTML/CSS/JS) ficam em moldes_site/, ao lado deste arquivo.

Link do pedido: por padrão o botão do carrinho abre o WhatsApp. Se `cfg["telegram_usuario"]` vier preenchido (o montador passa o
@usuario do bot quando o canal é o Telegram), abre https://t.me/<usuario>?start=<carrinho> (o bot troca "-" por ","). Esse campo NÃO
é gravado no catalogo.db: quem manda é o montador, a cada geração.

Uso pela linha de comando:   python gerador_site.py [pasta-dos-dados] [molde 1-4]
(sem a pasta, usa a loja do catálogo: catalogo/loja/)
"""
import base64
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# --- onde estão as coisas -----------------------------------------------------
PASTA_DADOS = Path(os.environ.get("SITE_PASTA_DADOS") or Path(__file__).resolve().parents[1] / "catalogo" / "loja")
PASTA_MOLDES = Path(__file__).resolve().parent / "moldes_site"
WHATSAPP_EXEMPLO = "5585999999999"
RE_USUARIO_TELEGRAM = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
EXTENSOES_LOGO = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

NOMES_MOLDE = {
    1: "Molde 1 — sem categorias (lista de blocos)",
    2: "Molde 2 — 2 categorias (tela dividida)",
    3: "Molde 3 — 3 ou mais categorias (carrosséis)",
    4: "Molde 4 — muitas categorias e itens (busca + abas)",
}

# cortes que escolhem o molde recomendado (antes ficavam no config_site.json)
MOLDES_CFG = {
    "itens_minimos_por_categoria": 20,
    "categorias_com_itens_minimos": 3,
    "minimo_categorias_molde_3": 3,
    "minimo_categorias_molde_4": 4,
}

CFG_PADRAO = {"nome": None, "whatsapp": "", "mensagem_inicial": "", "usar_estoque": False, "pedido_so_nomes": False}

# Texto pronto do pedido quando "só o nome dos produtos" está ligado (a mensagem inicial da loja, se houver, vira a abertura).
PEDIDO_ABERTURA_PADRAO = "Olá! 👋 Tudo bem? Quero fazer um pedido com estes itens:"
PEDIDO_FECHAMENTO_PADRAO = "Fico no aguardo para combinarmos pagamento e entrega. Obrigado(a)! 😊"

TEMA_PADRAO = {
    "cores": {"fundo": "#f5f6fa", "secundaria": "#ffffff", "destaque": "#0984e3"},
    "molde": None,       # None = usar o recomendado
}


class ErroDados(Exception):
    """Problema que a pessoa consegue resolver (mensagem em linguagem simples)."""


# ============================== a pasta de dados ==============================

def pastas_de_dados(base=None):
    """Pastas com um catalogo.db dentro de `base` (padrão: a loja do catálogo): a própria `base`, se o
    catalogo.db estiver direto nela, e depois cada subpasta, em ordem alfabética."""
    base = Path(base or PASTA_DADOS)
    achadas = [base] if (base / "catalogo.db").is_file() else []
    if base.is_dir():
        achadas += [p for p in sorted(base.iterdir(), key=lambda p: p.name.lower())
                    if p.is_dir() and not p.name.startswith((".", "_")) and (p / "catalogo.db").is_file()]
    return achadas


def pasta_padrao():
    """A loja do catálogo (ou a primeira pasta com catalogo.db dentro de SITE_PASTA_DADOS, se essa variável apontar para uma)."""
    achadas = pastas_de_dados()
    return achadas[0] if achadas else PASTA_DADOS


@dataclass(frozen=True)
class PastaDados:
    raiz: Path

    @property
    def catalogo(self):
        return self.raiz / "catalogo.db"

    @property
    def estoque(self):
        return self.raiz / "produtos_especializados.db"

    @property
    def imagens(self):
        return self.raiz / "imagens"

    @property
    def site(self):
        return self.raiz / "site"


def config_da_loja(pasta):
    """config.json da loja (o do catálogo), ou {} se não existe / não é legível. Só leitura."""
    try:
        d = json.loads((pasta.raiz / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


GRUPOS_NOME = "grupos_categorias.json"


def ler_grupos(pasta):
    """{grupo: [categorias]} do grupos_categorias.json da loja ({} se não existe / é ilegível)."""
    try:
        bruto = json.loads((pasta.raiz / GRUPOS_NOME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(bruto, dict):
        return {}
    saida = {}
    for grupo, categorias in bruto.items():
        g = " ".join(str(grupo or "").split())
        lista = [" ".join(str(c or "").split()) for c in categorias] if isinstance(categorias, list) else []
        lista = [c for c in lista if c]
        if g:
            saida[g] = lista
    return saida


def nome_padrao(pasta):
    """Nome do site quando ninguém digitou um: o nome da loja no config.json, senão o nome da pasta."""
    nome = " ".join(str(config_da_loja(pasta).get("nome") or "").split())
    return nome or pasta.raiz.name


def usuario_telegram(cfg):
    """@usuario do bot sem o @, ou '' se vazio ou inválido (5 a 32 letras, números ou _)."""
    u = str((cfg or {}).get("telegram_usuario") or "").strip().lstrip("@")
    return u if RE_USUARIO_TELEGRAM.fullmatch(u) else ""


def aprovado(produto):
    return bool(str(produto["descricao"] or "").strip() and str(produto["categoria"] or "").strip())


# ============================ leitura / escrita nos bancos ====================

def _consulta(caminho, sql, params=()):
    """Linhas de uma consulta (somente leitura) ou [] se o banco/tabela/coluna não existe."""
    if not Path(caminho).exists():
        return []
    try:
        con = sqlite3.connect(f"{Path(caminho).resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        if "no such table" in str(e) or "no such column" in str(e):
            return []
        raise ErroDados(f"Não consegui ler {Path(caminho).name} ({e}). Ele está aberto em outro programa?") from None


def _escrever(pasta, operacao):
    """Roda operacao(con) no catalogo.db, criando antes as tabelas do site se ainda não existirem."""
    if not pasta.catalogo.is_file():
        raise ErroDados(f"Não encontrei o catalogo.db em {pasta.raiz}.")
    try:
        con = sqlite3.connect(pasta.catalogo, timeout=10)
        try:
            with con:
                con.execute("CREATE TABLE IF NOT EXISTS site_config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
                con.execute("CREATE TABLE IF NOT EXISTS site_logo "
                            "(id INTEGER PRIMARY KEY CHECK (id = 1), nome TEXT NOT NULL, dados BLOB NOT NULL)")
                operacao(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        raise ErroDados(f"Não consegui gravar no catalogo.db ({e}). Ele está aberto em outro programa?") from None


def _ler_chave(pasta, chave):
    linhas = _consulta(pasta.catalogo, "SELECT valor FROM site_config WHERE chave = ?", (chave,))
    if not linhas:
        return {}
    try:
        d = json.loads(linhas[0][0])
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _guardar_chave(pasta, chave, valor):
    texto = json.dumps(valor, ensure_ascii=False)
    _escrever(pasta, lambda con: con.execute(
        "INSERT INTO site_config (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, texto)))


def ler_catalogo(pasta):
    """Produtos do catalogo.db, na ordem em que foram cadastrados."""
    if not pasta.catalogo.is_file():
        raise ErroDados(f"Não encontrei o catalogo.db em {pasta.raiz}.")
    linhas = _consulta(pasta.catalogo, "SELECT id, nome, preco, descricao, categoria FROM produtos ORDER BY rowid")
    return [{"id": i, "nome": n, "preco": pr, "descricao": d, "categoria": c} for i, n, pr, d, c in linhas]


# ============================ configurações do site ===========================

def limpar_numero(texto):
    """'+55 (85) 99999-9999' -> '5585999999999'."""
    return re.sub(r"\D", "", str(texto or ""))


def numero_whatsapp(cfg):
    """(número só com dígitos ou '', aviso ou '')."""
    bruto = cfg.get("whatsapp")
    n = limpar_numero(bruto)
    if not n:
        return "", "Nenhum número de WhatsApp configurado."
    if not 10 <= len(n) <= 15:
        return "", f"O número de WhatsApp '{bruto}' parece inválido (use código do país + DDD + número)."
    if n == WHATSAPP_EXEMPLO:
        return n, "O número de WhatsApp ainda é o de EXEMPLO. Troque pelo número real."
    return n, ""


def ler_cfg(pasta):
    """nome, WhatsApp, mensagem inicial e 'usar estoque' gravados no catalogo.db (com padrões onde faltar)."""
    cfg = dict(CFG_PADRAO)
    lido = _ler_chave(pasta, "config")
    if isinstance(lido.get("nome"), str) and lido["nome"].strip():
        cfg["nome"] = lido["nome"].strip()
    cfg["whatsapp"] = limpar_numero(lido.get("whatsapp"))
    cfg["mensagem_inicial"] = str(lido.get("mensagem_inicial") or "")
    cfg["usar_estoque"] = bool(lido.get("usar_estoque"))
    cfg["pedido_so_nomes"] = bool(lido.get("pedido_so_nomes"))
    return cfg


def gravar_cfg(pasta, cfg):
    n = limpar_numero(cfg.get("whatsapp"))
    if n and not 10 <= len(n) <= 15:
        raise ErroDados("Número inválido. Use código do país + DDD + número, ex.: 5585999999999.")
    limpo = {
        "nome": " ".join(str(cfg.get("nome") or "").split()) or None,
        "whatsapp": n,
        "mensagem_inicial": str(cfg.get("mensagem_inicial") or "").strip(),
        "usar_estoque": bool(cfg.get("usar_estoque")),
        "pedido_so_nomes": bool(cfg.get("pedido_so_nomes")),
    }
    _guardar_chave(pasta, "config", limpo)
    return limpo


def _hex_ok(valor, padrao):
    v = str(valor or "").strip()
    return v.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else padrao


def ler_tema(pasta):
    """Cores e molde escolhido (gravados no catalogo.db), com padrões onde faltar."""
    tema = json.loads(json.dumps(TEMA_PADRAO))
    lido = _ler_chave(pasta, "tema")
    cores_lidas = lido.get("cores") if isinstance(lido.get("cores"), dict) else {}
    for k, v in cores_lidas.items():
        if k in tema["cores"]:
            tema["cores"][k] = _hex_ok(v, tema["cores"][k])
    if lido.get("molde") in (1, 2, 3, 4):
        tema["molde"] = lido["molde"]
    return tema


def gravar_tema(pasta, tema):
    limpo = {
        "cores": {k: _hex_ok((tema.get("cores") or {}).get(k), TEMA_PADRAO["cores"][k]) for k in TEMA_PADRAO["cores"]},
        "molde": tema.get("molde") if tema.get("molde") in (1, 2, 3, 4) else None,
    }
    _guardar_chave(pasta, "tema", limpo)
    return limpo


def ler_logo(pasta):
    """(nome do arquivo, bytes) da logo gravada no catalogo.db, ou None."""
    linhas = _consulta(pasta.catalogo, "SELECT nome, dados FROM site_logo WHERE id = 1")
    return (linhas[0][0], bytes(linhas[0][1])) if linhas else None


def salvar_logo(pasta, nome_arquivo, dados):
    """Grava a logo dentro do catalogo.db (substitui a anterior) e devolve o nome (logo.<ext>)."""
    ext = Path(nome_arquivo).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in EXTENSOES_LOGO:
        raise ErroDados("Formato de logo não aceito. Use PNG, JPG, WEBP ou SVG.")
    nome = f"logo{ext}"
    _escrever(pasta, lambda con: con.execute(
        "INSERT INTO site_logo (id, nome, dados) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, dados = excluded.dados", (nome, dados)))
    return nome


# ------------------------------- cores e contraste ----------------------------

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def _lum(h):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = _lum(a), _lum(b)
    claro, escuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (escuro + 0.05)


def _misturar(a, b, t):
    """a*(1-t) + b*t"""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x * (1 - t) + y * t for x, y in zip(ra, rb)))


def _texto_sobre(fundo, minimo_branco=4.5):
    """Branco ou grafite, o que ler melhor sobre `fundo` (prefere branco se ele passar de `minimo_branco`:1)."""
    if contraste("#ffffff", fundo) >= minimo_branco:
        return "#ffffff"
    return "#ffffff" if contraste("#ffffff", fundo) >= contraste("#1e272e", fundo) else "#1e272e"


def _suave(texto, fundo):
    """Texto 'apagado' (secundário) que ainda passa de 4.5:1 de contraste com o fundo."""
    for t in (0.4, 0.3, 0.2, 0.1, 0.0):
        c = _misturar(texto, fundo, t)
        if contraste(c, fundo) >= 4.5:
            return c
    return texto


def css_tema(cores):
    """Bloco :root com as 3 cores (60% fundo / 30% secundária / 10% destaque) e os derivados calculados."""
    fundo, sec, dest = (_hex_ok(cores.get(k), TEMA_PADRAO["cores"][k]) for k in ("fundo", "secundaria", "destaque"))
    t_fundo, t_sec, t_dest = _texto_sobre(fundo), _texto_sobre(sec), _texto_sobre(dest, 3.0)   # destaque = texto grande/negrito
    v = OrderedDict([
        ("--cor-fundo", fundo), ("--cor-secundaria", sec), ("--cor-destaque", dest),
        ("--texto-fundo", t_fundo), ("--texto-sec", t_sec), ("--texto-destaque", t_dest),
        ("--texto-suave", _suave(t_sec, sec)), ("--texto-suave-fundo", _suave(t_fundo, fundo)),
        ("--borda", _misturar(t_sec, sec, 0.82)), ("--borda-fundo", _misturar(t_fundo, fundo, 0.78)),
        ("--fundo-alt", _misturar(fundo, t_fundo, 0.06)),
        # destaque como cor de preço/link só se ele for legível sobre a cor dos cartões
        ("--cor-preco", dest if contraste(dest, sec) >= 3 else t_sec),
        ("--sombra", "0 4px 6px rgba(0,0,0,0.12)"),
    ])
    return ":root {\n" + "".join(f"    {k}: {x};\n" for k, x in v.items()) + "}\n"


def extrair_cores(dados_logo, quantas=3):
    """As `quantas` cores mais frequentes da logo (ignora transparência e o branco de fundo).
    Devolve lista de '#rrggbb' (da mais para a menos frequente) ou None se não deu para ler a imagem."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(dados_logo)).convert("RGBA")
    except Exception:
        return None
    im.thumbnail((200, 200))
    baldes = {}
    for r, g, b, a in im.getdata():
        if a < 128 or (r > 235 and g > 235 and b > 235):
            continue
        chave = (r // 32, g // 32, b // 32)
        s = baldes.setdefault(chave, [0, 0, 0, 0])
        s[0] += 1; s[1] += r; s[2] += g; s[3] += b
    escolhidas = []
    for n, sr, sg, sb in sorted(baldes.values(), key=lambda s: -s[0]):
        cor = (sr / n, sg / n, sb / n)
        if all(sum((x - y) ** 2 for x, y in zip(cor, outra)) > 60 ** 2 for outra in escolhidas):
            escolhidas.append(cor)
        if len(escolhidas) == quantas:
            break
    if not escolhidas:
        return None
    padrao = list(TEMA_PADRAO["cores"].values())
    cores = [_hex(c) for c in escolhidas]
    return cores + padrao[len(cores):quantas]


# ============================ moldes: recomendação ============================

def contar_categorias(produtos):
    """{categoria: nº de itens}, na ordem em que aparecem."""
    cont = OrderedDict()
    for p in produtos:
        cont[p["categoria"]] = cont.get(p["categoria"], 0) + 1
    return cont


def recomendar_molde(contagem):
    """(nº do molde, motivo em português). Regra:
       0 ou 1 categoria -> 1 | exatamente 2 -> 2 | 3 ou mais -> 3 |
       e molde 4 se houver 'minimo_categorias_molde_4' ou mais categorias e pelo menos
       'categorias_com_itens_minimos' delas com 'itens_minimos_por_categoria' itens ou mais."""
    m = MOLDES_CFG
    c = len(contagem)
    total = sum(contagem.values())
    if c == 0:
        return 1, f"A loja não tem categorias ({total} itens): lista única."
    if c == 1:
        return 1, f"A loja tem 1 categoria só ({total} itens): não há o que separar, então lista única."
    if c == 2:
        return 2, f"A loja tem exatamente 2 categorias ({total} itens): tela dividida."
    grandes = [k for k, n in contagem.items() if n >= m["itens_minimos_por_categoria"]]
    if c >= m["minimo_categorias_molde_4"] and len(grandes) >= m["categorias_com_itens_minimos"]:
        return 4, (f"{c} categorias, e {len(grandes)} delas têm {m['itens_minimos_por_categoria']} itens ou mais "
                   f"(precisa de {m['categorias_com_itens_minimos']}): busca + abas.")
    if c >= m["minimo_categorias_molde_3"]:
        extra = ""
        if c >= m["minimo_categorias_molde_4"]:
            extra = (f" Só {len(grandes)} categoria(s) com {m['itens_minimos_por_categoria']}+ itens "
                     f"(o molde 4 pede {m['categorias_com_itens_minimos']}).")
        return 3, f"{c} categorias ({total} itens): carrosséis.{extra}"
    return 1, f"{c} categorias ({total} itens): lista única."


def molde_possivel(molde, contagem):
    """(ok, mensagem). O molde 2 só funciona com exatamente 2 categorias; os outros aceitam qualquer loja."""
    if molde not in NOMES_MOLDE:
        return False, "Molde desconhecido."
    if molde == 2 and len(contagem) != 2:
        return False, f"O molde 2 precisa de exatamente 2 categorias (a loja tem {len(contagem)})."
    return True, ""


# ============================ leitura dos dados da loja =======================

def _bonito(nome):
    nome = " ".join(str(nome).split())
    return nome[:1].upper() + nome[1:]


def modo_da_pasta(pasta):
    """'especializado' se o banco de SKUs tem pelo menos uma SKU ativa; senão 'simples' (preço do catálogo)."""
    return "especializado" if _consulta(pasta.estoque, "SELECT 1 FROM skus WHERE ativo = 1 LIMIT 1") else "simples"


def coletar_dados(pasta, cfg, mapear_foto):
    """Monta o dicionário que vira o dados.js. `mapear_foto(caminho_relativo)` devolve o endereço da foto no site
    (ou None se o arquivo não existe na pasta de imagens). Devolve (dados, avisos, contagem_de_categorias)."""
    avisos = []
    catalogo = ler_catalogo(pasta)
    modo = modo_da_pasta(pasta)
    esp = modo == "especializado"

    # --- fotos (catalogo.db é a fonte; o banco de SKUs só entra se o catálogo não tiver foto) ---
    gerais = {}
    for pid, _o, caminho in _consulta(pasta.catalogo, "SELECT id_produto, ordem, caminho FROM imagens ORDER BY id_produto, ordem"):
        gerais.setdefault(str(pid).upper(), []).append(caminho)
    variacao = {}
    for pid, tipo, opcao, _o, caminho in _consulta(
            pasta.catalogo,
            "SELECT id_produto, tipo, opcao, ordem, caminho FROM imagens_variacao ORDER BY id_produto, tipo, opcao, ordem"):
        variacao.setdefault((str(pid).upper(), str(tipo).casefold(), str(opcao).casefold()), []).append(caminho)
    gerais_esp = {}
    for pid, _o, url in _consulta(pasta.estoque, "SELECT produto_id, ordem, url FROM imagens ORDER BY produto_id, ordem"):
        gerais_esp.setdefault(str(pid).upper(), []).append(url)
    fotos_sku_esp = {}
    for sku, _o, url in _consulta(pasta.estoque, "SELECT sku, ordem, url FROM imagens_sku ORDER BY sku, ordem"):
        fotos_sku_esp.setdefault(str(sku).upper(), []).append(url)

    def fotos(lista, rotulo):
        saida = []
        for c in lista:
            url = mapear_foto(c)
            if url is None:
                avisos.append(f"Foto não encontrada na pasta de imagens: {c} ({rotulo}) — ficou de fora.")
            elif url not in saida:
                saida.append(url)
        return saida

    # --- SKUs (produtos_especializados.db) ---
    skus_por_produto = {}
    if esp:
        linhas = _consulta(
            pasta.estoque,
            "SELECT s.produto_id, s.sku, s.atributos, s.preco, s.quantidade, s.ilimitado FROM skus s "
            "JOIN produtos p ON p.id = s.produto_id WHERE s.ativo = 1 AND p.ativo = 1 ORDER BY s.rowid")
        for pid, sku, atributos, preco, qtd, ilim in linhas:
            try:
                at = json.loads(atributos or "{}")
                if not isinstance(at, dict):
                    raise ValueError
            except ValueError:
                avisos.append(f"SKU {sku}: atributos ilegíveis, ignorada.")
                continue
            skus_por_produto.setdefault(str(pid).upper(), []).append(
                {"sku": str(sku).upper(), "atributos": at, "preco": float(preco), "qtd": qtd, "ilim": bool(ilim)})
    elif cfg.get("usar_estoque"):
        avisos.append("'Usar estoque' está ligado, mas não há SKUs ativas em produtos_especializados.db: o site não mostra estoque.")

    # --- categorias (grafia única; ordem = ordem em que aparecem no catálogo) ---
    canon = OrderedDict()
    pendentes = 0
    for p in catalogo:
        if not aprovado(p):
            pendentes += 1
            continue
        k = " ".join(str(p["categoria"]).split()).casefold()
        if k not in canon:
            canon[k] = _bonito(p["categoria"])

    produtos = []
    for p in catalogo:
        if not aprovado(p):
            continue
        pid = str(p["id"]).strip().upper()
        cat_chave = " ".join(str(p["categoria"]).split()).casefold()
        if esp:
            skus_bd = skus_por_produto.get(pid, [])
            if not skus_bd:
                avisos.append(f"{pid} ({p['nome']}): sem SKU ativa, ficou fora do site.")
                continue
        else:
            if p["preco"] is None:
                avisos.append(f"{pid} ({p['nome']}): sem preço, ficou fora do site.")
                continue
            skus_bd = [{"sku": pid, "atributos": {}, "preco": float(p["preco"]), "qtd": None, "ilim": True}]

        # tipos de variação e opções: na ordem em que aparecem nas SKUs (cor, tamanho... / verde, preto...)
        ordem = []
        for s in skus_bd:
            for t in s["atributos"]:
                if t not in ordem:
                    ordem.append(t)

        tipos = []
        for t in ordem:
            vistas = []
            for s in skus_bd:
                o = s["atributos"].get(t)
                if o is not None and o not in vistas:
                    vistas.append(o)
            tipos.append({
                "tipo": t,
                "rotulo": t,
                "opcoes": [{"nome": o, "fotos": fotos(variacao.get((pid, str(t).casefold(), str(o).casefold()), []), f"{pid} {t}/{o}")}
                           for o in vistas],
            })

        gerais_p = fotos(gerais.get(pid) or gerais_esp.get(pid, []), pid)
        skus = []
        for s in skus_bd:
            lista = list(gerais_p)
            for t in ordem:
                o = s["atributos"].get(t)
                if o is None:
                    continue
                for url in next((x["fotos"] for tt in tipos if tt["tipo"] == t for x in tt["opcoes"] if x["nome"] == o), []):
                    if url not in lista:
                        lista.append(url)
            if not lista:   # nada no catálogo: usa a galeria que o banco de SKUs guardou para esta SKU
                lista = fotos(fotos_sku_esp.get(s["sku"], []), s["sku"])
            item = {"sku": s["sku"], "atributos": s["atributos"], "preco": round(s["preco"], 2), "fotos": lista}
            if cfg.get("usar_estoque") and esp:
                item["estoque"] = {"quantidade": int(s["qtd"] or 0), "ilimitado": s["ilim"]}
            skus.append(item)

        base = float(p["preco"]) if p["preco"] is not None else min(s["preco"] for s in skus)
        produtos.append({
            "id": pid, "nome": p["nome"], "preco": round(base, 2),
            "descricao": str(p["descricao"] or "").strip(), "categoria": canon[cat_chave],
            "imagens": gerais_p, "tipos": tipos, "skus": skus,
        })

    if pendentes:
        avisos.append(f"{pendentes} produto(s) ainda não aprovados (sem descrição ou categoria) ficaram fora do site.")
    categorias = [nome for nome in canon.values() if any(p["categoria"] == nome for p in produtos)]
    contagem = contar_categorias(produtos)
    numero, aviso_zap = numero_whatsapp(cfg)
    telegram = usuario_telegram(cfg)
    if aviso_zap and not (telegram and not numero):   # com o Telegram ligado, faltar o WhatsApp não é problema
        avisos.append(aviso_zap)
    if str(cfg.get("telegram_usuario") or "").strip() and not telegram:
        avisos.append("O @usuario do bot do Telegram é inválido (5 a 32 letras, números ou _): o site vai pedir pelo WhatsApp.")
    orcamento = bool(config_da_loja(pasta).get("orcamento"))

    # grupos (subcategorias): {grupo: [categorias]} da loja; só entram categorias com produtos no site
    grupos_saida = []
    for grupo, cats in ler_grupos(pasta).items():
        presentes = []
        for c in cats:
            bonito = canon.get(c.casefold())
            if bonito and bonito in categorias and bonito not in presentes:
                presentes.append(bonito)
        if presentes:
            grupos_saida.append({"nome": grupo, "categorias": presentes})

    dados = {
        "nome": cfg.get("nome") or nome_padrao(pasta), "modo": modo, "whatsapp": numero,
        # loja por orçamento (config.json da loja): o site mostra "A combinar" no lugar dos preços
        "orcamento": orcamento,
        # só preenchido quando o montador manda o @usuario do bot: o botão do carrinho abre o Telegram em vez do WhatsApp
        "telegram": telegram,
        "mensagem_inicial": str(cfg.get("mensagem_inicial") or ""),
        "usar_estoque": bool(cfg.get("usar_estoque")) and esp,
        # pedido só com o nome dos produtos (sem ID/SKU): vale para o site inteiro
        "pedido_so_nomes": bool(cfg.get("pedido_so_nomes")),
        "texto_pedido": {
            "abertura": str(cfg.get("mensagem_inicial") or "").strip() or PEDIDO_ABERTURA_PADRAO,
            "fechamento": PEDIDO_FECHAMENTO_PADRAO,
        },
        "categorias": categorias, "produtos": produtos,
        "grupos": grupos_saida,
    }
    return dados, avisos, contagem


# ============================= montagem dos arquivos ==========================

def _ler(caminho):
    return Path(caminho).read_text(encoding="utf-8")


def _json_js(dados):
    # "</" vira "<\/" para o dados.js também poder ser embutido numa tag <script> (preview)
    return "window.LOJA = " + json.dumps(dados, ensure_ascii=False, indent=1).replace("</", "<\\/") + ";\n"


def _montar_arquivos(molde, tema, dados, logo_src):
    pasta = PASTA_MOLDES / f"molde{molde}"
    comum = PASTA_MOLDES / "_comum"
    if not pasta.is_dir():
        raise ErroDados(f"Não encontrei a pasta do molde: {pasta}")
    nome = html.escape(dados["nome"])
    logo_tag = f'<img src="{html.escape(logo_src, quote=True)}" alt="">' if logo_src else ""
    cabecalho = _ler(comum / "cabecalho.html").replace("{{LOGO}}", logo_tag).replace("{{NOME}}", nome)
    pagina = (_ler(pasta / "index.html").replace("{{CABECALHO}}", cabecalho)
              .replace("{{GAVETA}}", _ler(comum / "gaveta.html")).replace("{{TITULO}}", nome)
              .replace("{{RODAPE}}", _ler(comum / "rodape.html")))
    return {
        "index.html": pagina,
        "style.css": css_tema(tema["cores"]) + "\n" + _ler(comum / "base.css") + "\n" + _ler(pasta / "layout.css"),
        "core.js": _ler(comum / "core.js"),
        "script.js": _ler(pasta / "script.js"),
        "dados.js": _json_js(dados),
    }


def _foto_dentro_das_imagens(pasta, caminho):
    """Arquivo da foto se ele existe E está dentro da pasta de imagens (senão None)."""
    arq = pasta.raiz / str(caminho).replace("\\", "/")
    try:
        arq.resolve().relative_to(pasta.imagens.resolve())
    except ValueError:
        return None
    return arq if arq.is_file() else None


def _preparar(pasta, molde=None, tema=None, cfg=None, preview=False):
    cfg = cfg or ler_cfg(pasta)
    tema = tema or ler_tema(pasta)
    usados = {}

    def mapear(caminho):
        arq = _foto_dentro_das_imagens(pasta, caminho)
        if arq is None:
            return None
        rel = str(caminho).replace("\\", "/")
        usados[rel] = arq
        return _data_uri(arq.read_bytes(), arq.name, reduzir=True) if preview else rel

    dados, avisos, contagem = coletar_dados(pasta, cfg, mapear)
    if not dados["produtos"]:
        raise ErroDados("Nenhum produto aprovado ainda: cadastre descrição e categoria dos produtos na interface do catálogo.")
    recomendado, motivo = recomendar_molde(contagem)
    molde = molde or tema.get("molde") or recomendado
    ok, msg = molde_possivel(molde, contagem)
    if not ok:
        raise ErroDados(msg)

    logo = ler_logo(pasta)
    logo_src = (_data_uri(logo[1], logo[0]) if preview else logo[0]) if logo else ""
    dados["logo"] = logo_src or None
    arquivos = _montar_arquivos(molde, tema, dados, logo_src)

    h = hashlib.sha1()
    h.update(json.dumps({"molde": molde, "css": arquivos["style.css"], "dados": dados}, sort_keys=True, ensure_ascii=False).encode())
    for nome in ("index.html", "core.js", "script.js"):
        h.update(arquivos[nome].encode())
    for caminho, arq in sorted(usados.items()):
        st = arq.stat()
        h.update(f"{caminho}|{st.st_size}|{st.st_mtime_ns}".encode())
    if logo:
        h.update(logo[0].encode() + hashlib.sha1(logo[1]).digest())
    return {"molde": molde, "recomendado": recomendado, "motivo": motivo, "contagem": contagem, "dados": dados,
            "avisos": avisos, "arquivos": arquivos, "usados": usados, "logo": logo, "assinatura": h.hexdigest()}


def _data_uri(bruto, nome, reduzir=False):
    tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    if reduzir and tipo.startswith("image/") and tipo != "image/svg+xml":
        try:   # preview leve: miniatura de até 700 px
            from PIL import Image
            im = Image.open(io.BytesIO(bruto))
            im.thumbnail((700, 700))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=80)
            bruto, tipo = buf.getvalue(), "image/jpeg"
        except Exception:
            pass
    return f"data:{tipo};base64," + base64.b64encode(bruto).decode()


# =================================== API pública ==============================

def analisar_loja(pasta, molde=None, tema=None, cfg=None):
    """Para a interface: categorias, molde recomendado + motivo, avisos e se o site gerado está desatualizado.
    Não escreve nada em disco."""
    r = _preparar(pasta, molde=molde, tema=tema, cfg=cfg)
    return {k: r[k] for k in ("molde", "recomendado", "motivo", "contagem", "avisos", "assinatura")} | {
        "produtos": len(r["dados"]["produtos"]), "estado": estado_site(pasta, r["assinatura"])}


def estado_site(pasta, assinatura_atual=None):
    """{'gerado': bool, 'quando': str|None, 'desatualizado': bool|None, 'molde': int|None}"""
    try:
        info = json.loads((pasta.site / "gerado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    if not isinstance(info, dict) or not info or not (pasta.site / "index.html").is_file():
        return {"gerado": False, "quando": None, "desatualizado": None, "molde": None}
    return {"gerado": True, "quando": info.get("quando"), "molde": info.get("molde"),
            "desatualizado": None if assinatura_atual is None else info.get("assinatura") != assinatura_atual}


def gerar_site(pasta, molde=None, tema=None, cfg=None):
    """Escreve <pasta de dados>/site/. Devolve {'pasta','molde','produtos','avisos'}."""
    r = _preparar(pasta, molde=molde, tema=tema, cfg=cfg)
    destino = pasta.site
    try:
        destino.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(destino / "imagens", ignore_errors=True)
        for velho in destino.glob("logo.*"):
            velho.unlink()
        for nome, texto in r["arquivos"].items():
            (destino / nome).write_text(texto, encoding="utf-8")
        for caminho, origem in r["usados"].items():
            alvo = destino / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, alvo)
        if r["logo"]:
            (destino / r["logo"][0]).write_bytes(r["logo"][1])
        info = {"quando": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "molde": r["molde"],
                "assinatura": r["assinatura"], "produtos": len(r["dados"]["produtos"])}
        (destino / "gerado.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    except PermissionError:
        raise ErroDados("Não consegui gravar a pasta 'site'. Feche o site aberto em outro programa e tente de novo.") from None
    return {"pasta": destino, "molde": r["molde"], "produtos": info["produtos"], "avisos": r["avisos"]}


def html_preview(pasta, molde=None, tema=None, cfg=None):
    """O site inteiro numa página só (CSS, JS e fotos embutidos), para mostrar no preview da interface.
    Não escreve nada em disco e aceita tema/configurações ainda não salvos."""
    r = _preparar(pasta, molde=molde, tema=tema, cfg=cfg, preview=True)
    a = r["arquivos"]

    def inline_js(t):
        return "<script>\n" + t.replace("</script", "<\\/script") + "\n</script>"
    pagina = a["index.html"]
    pagina = pagina.replace('<link rel="stylesheet" href="style.css">', "<style>\n" + a["style.css"] + "\n</style>")
    for nome in ("dados.js", "core.js", "script.js"):
        pagina = pagina.replace(f'<script src="{nome}"></script>', inline_js(a[nome]))
    return pagina


if __name__ == "__main__":
    args = sys.argv[1:]
    molde_cli = next((int(a) for a in args if a.isdigit() and len(a) == 1), None)
    caminho = next((a for a in args if not (a.isdigit() and len(a) == 1)), None)
    try:
        res = gerar_site(PastaDados(Path(caminho).resolve() if caminho else pasta_padrao()), molde=molde_cli)
    except ErroDados as e:
        print("Erro:", e)
        sys.exit(1)
    print(f"Site gerado em {res['pasta']} (molde {res['molde']}, {res['produtos']} produtos)")
    for av in res["avisos"]:
        print(" aviso:", av)
