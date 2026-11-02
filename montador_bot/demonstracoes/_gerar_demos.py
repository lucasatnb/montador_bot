"""Gera as lojas de demonstração (catálogo + site + bot) em demonstracoes/.

Cada demo tem dados fictícios, imagens ilustrativas e um bot pronto para receber um token
do Telegram. Rode de qualquer lugar:

    python demonstracoes/_gerar_demos.py

As imagens já baixadas são reaproveitadas. Se a geração de uma imagem falhar, o script
cria uma capa simples com a inicial do produto (e avisa) para a demo não ficar quebrada.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "catalogo"))
sys.path.insert(0, str(REPO / "criador_site"))

from nucleo import banco_loja as bl  # noqa: E402
from nucleo import gerar_pastas as gp  # noqa: E402
from nucleo import grupos as gr  # noqa: E402
from variacoes import constantes_especializado as ce  # noqa: E402
from variacoes import planilha_especializada as pe  # noqa: E402

import gerador_site as gs  # noqa: E402
import montador  # noqa: E402

WHATSAPP_DEMO = "5585999990000"   # fictício: troque pelo número real antes de usar

DEMOS = [
    {
        "slug": "otica-visione",
        "nome": "Visioné Ótica",
        "orcamento": True,
        "tema": {"cores": {"fundo": "#F3EFE7", "secundaria": "#FFFFFF", "destaque": "#1F5C4A"}, "molde": 3},
        "molde": 3,
        "saudacao": "Olá! 👓 Bem-vindo(a) à Visioné Ótica. Vou te ajudar com armações, lentes e óculos de sol. Como posso te chamar?",
        "mensagem_site": "Olá! Vim pelo site da Visioné e gostaria de um atendimento.",
        "logo": """<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
<circle cx="60" cy="60" r="56" fill="#1F5C4A"/>
<text x="60" y="80" font-family="Georgia, serif" font-size="66" fill="#F3EFE7" text-anchor="middle">V</text>
</svg>""",
        "atributos": {"cor": {"rotulo": "Cor", "opcoes": {
            "Preto": "PT", "Tartaruga": "TT", "Dourado": "DR", "Prata": "PR",
            "Azul": "AZ", "Rosa": "RS", "Marrom": "MR"}}},
        "grupos": {
            "Óculos de grau": ["Armações", "Lentes"],
            "Óculos de sol": ["Solar Masculino", "Solar Feminino"],
            "Acessórios": ["Estojos"],
        },
        "produtos": [
            {"id": "A000", "nome": "Armação Aurora", "categoria": "Armações", "preco": 890.0,
             "descricao": "Armação em acetato italiano, leve e confortável, com lentes de demonstração. Disponível em preto e tartaruga.",
             "variacoes": {"cor": ["Preto", "Tartaruga"]}, "estoque": 2, "seed": 101,
             "prompt": "black acetate eyeglasses frame, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A001", "nome": "Armação Íris", "categoria": "Armações", "preco": 790.0,
             "descricao": "Armação redonda em metal, fina e elegante. Ideal para quem busca um visual clássico com leveza.",
             "variacoes": {"cor": ["Dourado", "Prata"]}, "estoque": 2, "seed": 102,
             "prompt": "gold round metal eyeglasses frame, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A002", "nome": "Armação Delta", "categoria": "Armações", "preco": 690.0,
             "descricao": "Armação quadrada de perfil marcante, com hastes flexíveis e acabamento fosco.",
             "variacoes": {"cor": ["Preto", "Azul"]}, "estoque": 2, "seed": 103,
             "prompt": "square black eyeglasses frame, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A003", "nome": "Solar Riviera", "categoria": "Solar Masculino", "preco": 990.0,
             "descricao": "Óculos de sol estilo aviador, lentes escuras com proteção UV400 e armação metálica.",
             "variacoes": {"cor": ["Preto", "Tartaruga"]}, "estoque": 2, "seed": 104,
             "prompt": "aviator sunglasses with dark lenses, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A004", "nome": "Solar Atlântica", "categoria": "Solar Feminino", "preco": 890.0,
             "descricao": "Óculos de sol estilo gatinho, com lentes degradê e armação em acetato.",
             "variacoes": {"cor": ["Tartaruga", "Rosa"]}, "estoque": 2, "seed": 105,
             "prompt": "cat eye sunglasses with gradient lenses, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A005", "nome": "Solar Náutica", "categoria": "Solar Feminino", "preco": 590.0,
             "descricao": "Óculos de sol redondos com armação fina e lentes espelhadas. Leve e versátil.",
             "variacoes": {"cor": ["Dourado", "Preto"]}, "estoque": 2, "seed": 106,
             "prompt": "round sunglasses with gold frame, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A006", "nome": "Lentes Multifocais", "categoria": "Lentes", "preco": 0.0,
             "descricao": "Lentes multifocais personalizadas, com tratamento antirreflexo e proteção contra luz azul. Valor sob consulta.",
             "variacoes": {}, "estoque": 10, "seed": 107,
             "prompt": "single clear eyeglass lens macro product photo, white background, soft studio light, no people, no text, no logo, no watermark"},
            {"id": "A007", "nome": "Estojo Executivo", "categoria": "Estojos", "preco": 89.0,
             "descricao": "Estojo rígido revestido em couro sintético, com fechamento magnético e flanela interna.",
             "variacoes": {"cor": ["Preto", "Marrom"]}, "estoque": 3, "seed": 108,
             "prompt": "premium leather eyeglasses case, product only, centered on warm beige background, luxury optical catalog photo, soft studio lighting, no people, no text, no logo, no watermark"},
        ],
    },
    {
        "slug": "atelie-norte",
        "nome": "Ateliê Norte",
        "orcamento": False,
        "tema": {"cores": {"fundo": "#F2EEE8", "secundaria": "#FFFFFF", "destaque": "#B55236"}, "molde": 4},
        "molde": 4,
        "saudacao": "Olá! 👕 Bem-vindo(a) ao Ateliê Norte. Vou te mostrar as peças e montar seu pedido. Como posso te chamar?",
        "mensagem_site": "Olá! Vim pelo site do Ateliê Norte e gostaria de fazer um pedido.",
        "logo": """<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
<rect x="4" y="4" width="112" height="112" rx="16" fill="#B55236"/>
<text x="60" y="76" font-family="Georgia, serif" font-size="44" fill="#F2EEE8" text-anchor="middle">AN</text>
</svg>""",
        "atributos": {
            "tamanho": {"rotulo": "Tamanho", "opcoes": {"P": "P", "M": "M", "G": "G", "GG": "GG"}},
            "cor": {"rotulo": "Cor", "opcoes": {
                "Off White": "OW", "Preto": "PT", "Azul": "AZ", "Caqui": "CQ",
                "Verde": "VD", "Branco": "BR", "Marrom": "MR"}},
            "numeracao": {"rotulo": "Numeração", "opcoes": {
                "39": "39", "40": "40", "41": "41", "42": "42", "43": "43"}},
        },
        "grupos": {
            "Roupas": ["Camisetas", "Camisas", "Calças", "Bermudas", "Jaquetas"],
            "Calçados": ["Tênis"],
            "Acessórios": ["Bonés", "Cintos"],
        },
        "produtos": [
            {"id": "A000", "nome": "Camiseta Essential", "categoria": "Camisetas", "preco": 89.9,
             "descricao": "Camiseta em algodão penteado, modelagem regular e toque macio. Peça coringa para o dia a dia.",
             "variacoes": {"tamanho": ["P", "M", "G", "GG"], "cor": ["Off White", "Preto"]}, "estoque": 4, "seed": 201,
             "prompt": "folded cream cotton t-shirt, flat lay on light neutral background, minimalist e-commerce product photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A001", "nome": "Camisa de Linho", "categoria": "Camisas", "preco": 189.9,
             "descricao": "Camisa de linho com caimento leve, botões naturais e bolso frontal. Perfeita para dias quentes.",
             "variacoes": {"tamanho": ["P", "M", "G", "GG"], "cor": ["Off White", "Azul"]}, "estoque": 3, "seed": 202,
             "prompt": "light blue linen shirt on a hanger, product photo on warm neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A002", "nome": "Calça Cargo", "categoria": "Calças", "preco": 219.9,
             "descricao": "Calça cargo em sarja resistente, com bolsos laterais e ajuste no tornozelo.",
             "variacoes": {"tamanho": ["P", "M", "G", "GG"], "cor": ["Preto", "Caqui"]}, "estoque": 3, "seed": 203,
             "prompt": "black cargo pants, product photo on light neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A003", "nome": "Bermuda Sarja", "categoria": "Bermudas", "preco": 129.9,
             "descricao": "Bermuda em sarja com lavagem suave e comprimento acima do joelho. Conforto e estilo.",
             "variacoes": {"tamanho": ["P", "M", "G", "GG"], "cor": ["Caqui", "Azul"]}, "estoque": 3, "seed": 204,
             "prompt": "beige chino shorts, product photo on light neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A004", "nome": "Jaqueta Corta-Vento", "categoria": "Jaquetas", "preco": 299.9,
             "descricao": "Jaqueta leve com capuz, zíper frontal e bolsos. Proteção para dias de vento e chuva fina.",
             "variacoes": {"tamanho": ["P", "M", "G", "GG"], "cor": ["Preto", "Verde"]}, "estoque": 3, "seed": 205,
             "prompt": "black windbreaker jacket, product photo on light neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A005", "nome": "Tênis Urbano", "categoria": "Tênis", "preco": 249.9,
             "descricao": "Tênis minimalista em couro sintético, solado leve e palmilha confortável para o dia inteiro.",
             "variacoes": {"numeracao": ["39", "40", "41", "42", "43"], "cor": ["Branco", "Preto"]}, "estoque": 2, "seed": 206,
             "prompt": "single white minimalist sneaker side view, product photo on light gray background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A006", "nome": "Boné Aba Reta", "categoria": "Bonés", "preco": 79.9,
             "descricao": "Boné de aba reta com ajuste traseiro e bordado discreto. Acabamento em algodão.",
             "variacoes": {"cor": ["Preto", "Azul"]}, "estoque": 5, "seed": 207,
             "prompt": "black baseball cap, product photo on light neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A007", "nome": "Cinto de Couro", "categoria": "Cintos", "preco": 99.9,
             "descricao": "Cinto em couro legítimo com fivela metálica e acabamento artesanal. Largura de 3,5 cm.",
             "variacoes": {"cor": ["Preto", "Marrom"]}, "estoque": 5, "seed": 208,
             "prompt": "brown leather belt coiled, product photo on light neutral background, soft studio lighting, no people, no text, no logo, no watermark"},
        ],
    },
    {
        "slug": "bicho-e-cia",
        "nome": "Bicho & Cia",
        "orcamento": False,
        "tema": {"cores": {"fundo": "#F7F1E3", "secundaria": "#FFFFFF", "destaque": "#2F7D6B"}, "molde": 3},
        "molde": 3,
        "saudacao": "Olá! 🐾 Bem-vindo(a) à Bicho & Cia. Vou te ajudar com ração, acessórios e higiene. Como posso te chamar?",
        "mensagem_site": "Olá! Vim pelo site da Bicho & Cia e gostaria de fazer um pedido.",
        "logo": """<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
<circle cx="60" cy="60" r="56" fill="#2F7D6B"/>
<g fill="#F7F1E3">
  <ellipse cx="42" cy="48" rx="9" ry="12" transform="rotate(-20 42 48)"/>
  <ellipse cx="60" cy="41" rx="9" ry="12"/>
  <ellipse cx="78" cy="48" rx="9" ry="12" transform="rotate(20 78 48)"/>
  <ellipse cx="90" cy="64" rx="8" ry="11" transform="rotate(35 90 64)"/>
  <path d="M60 58c-16 0-27 13-27 25 0 8 7 14 16 14 6 0 9-3 11-6 2 3 5 6 11 6 9 0 16-6 16-14 0-12-11-25-27-25z"/>
</g>
</svg>""",
        "atributos": {
            "tamanho": {"rotulo": "Tamanho", "opcoes": {"P": "P", "M": "M", "G": "G"}},
            "cor": {"rotulo": "Cor", "opcoes": {
                "Preto": "PT", "Marrom": "MR", "Verde": "VD", "Laranja": "LJ",
                "Cinza": "CZ", "Bege": "BG", "Azul": "AZ", "Vermelho": "VM"}},
        },
        "grupos": {
            "Alimentos": ["Ração", "Petiscos"],
            "Acessórios": ["Coleiras", "Brinquedos", "Camas", "Roupas"],
            "Higiene": ["Shampoos", "Tapetes higiênicos"],
        },
        "produtos": [
            {"id": "A000", "nome": "Ração Premium 15kg", "categoria": "Ração", "preco": 189.9,
             "descricao": "Ração seca premium para cães adultos, com proteínas de alta qualidade e ômega 3. Embalagem de 15 kg.",
             "variacoes": {}, "estoque": 8, "seed": 301,
             "prompt": "plain kraft paper bag of dog food, unbranded, on warm cream background, product photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A001", "nome": "Petiscos Naturais", "categoria": "Petiscos", "preco": 39.9,
             "descricao": "Petiscos naturais assados, sem corantes artificiais. Ideal para treino e recompensa.",
             "variacoes": {}, "estoque": 12, "seed": 302,
             "prompt": "natural dog treats in a plain ceramic bowl, warm cream background, product photo, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A002", "nome": "Coleira de Couro", "categoria": "Coleiras", "preco": 79.9,
             "descricao": "Coleira em couro com fivela metálica e argola reforçada. Disponível em três tamanhos.",
             "variacoes": {"tamanho": ["P", "M", "G"], "cor": ["Preto", "Marrom"]}, "estoque": 4, "seed": 303,
             "prompt": "brown leather dog collar with metal buckle, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A003", "nome": "Brinquedo Mordedor", "categoria": "Brinquedos", "preco": 49.9,
             "descricao": "Mordedor em borracha atóxica, resistente e fácil de limpar. Ajuda na saúde dental.",
             "variacoes": {"cor": ["Verde", "Laranja"]}, "estoque": 6, "seed": 304,
             "prompt": "green rubber dog chew toy, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A004", "nome": "Cama Aconchego", "categoria": "Camas", "preco": 159.9,
             "descricao": "Cama redonda com borda alta e enchimento macio, forro removível para lavar.",
             "variacoes": {"tamanho": ["P", "M", "G"], "cor": ["Cinza", "Bege"]}, "estoque": 3, "seed": 305,
             "prompt": "round beige pet bed, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A005", "nome": "Shampoo Neutro", "categoria": "Shampoos", "preco": 39.9,
             "descricao": "Shampoo neutro para cães e gatos, com pH balanceado e extrato de aveia. 500 ml.",
             "variacoes": {}, "estoque": 10, "seed": 306,
             "prompt": "white unbranded pet shampoo bottle, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A006", "nome": "Tapete Higiênico 30un", "categoria": "Tapetes higiênicos", "preco": 49.9,
             "descricao": "Tapete higiênico superabsorvente com proteção contra vazamentos. Pacote com 30 unidades.",
             "variacoes": {}, "estoque": 10, "seed": 307,
             "prompt": "stack of white puppy training pads, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
            {"id": "A007", "nome": "Roupinha de Frio", "categoria": "Roupas", "preco": 59.9,
             "descricao": "Roupinha de frio em malha macia, com abertura para coleira. Disponível em três tamanhos.",
             "variacoes": {"tamanho": ["P", "M", "G"], "cor": ["Azul", "Vermelho"]}, "estoque": 4, "seed": 308,
             "prompt": "small blue dog sweater, product photo on warm cream background, soft studio lighting, no people, no text, no logo, no watermark"},
        ],
    },
]


def _fallback(nome: str, cor: str, destino: Path) -> None:
    """Capa simples (gradiente + inicial) caso a geração da imagem falhe."""
    w, h = 900, 645
    im = Image.new("RGB", (w, h), cor)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(c * (0.82 + 0.18 * t)) for c in im.getpixel((0, 0))))
    d.ellipse((w * 0.18, h * 0.12, w * 0.82, h * 0.9), fill=(255, 255, 255, 40))
    d.text((w // 2, h // 2), (nome.strip()[:1] or "?").upper(), fill="#ffffff", anchor="mm")
    im.save(destino, "JPEG", quality=88)


def baixar_imagem(prompt: str, seed: int, destino: Path, cor_fallback: str) -> None:
    """Baixa uma imagem ilustrativa, corta a marca d'água do rodapé e salva em JPG."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_file() and destino.stat().st_size > 8_000:
        return
    url = ("https://image.pollinations.ai/prompt/" + requests.utils.quote(prompt) +
           f"?width=900&height=700&nologo=true&seed={seed}")
    for tentativa in range(4):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 402:
                time.sleep(12 + tentativa * 8)
                continue
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            w, h = im.size
            if h > 80:
                im = im.crop((0, 0, w, h - 55))   # tira a marca d'água do rodapé
            im.save(destino, "JPEG", quality=88)
            print(f"  imagem {destino.parent.name}: ok ({destino.stat().st_size // 1024} KB)")
            return
        except Exception as e:  # noqa: BLE001
            print(f"  imagem {destino.parent.name}: tentativa {tentativa + 1} falhou ({e})")
            time.sleep(4 + tentativa * 4)
    _fallback(destino.parent.name, cor_fallback, destino)
    print(f"  imagem {destino.parent.name}: usando capa de reserva")


def _config_loja(loja, nome: str, orcamento: bool) -> None:
    cfg = {}
    if loja.arquivo_config.is_file():
        try:
            cfg = json.loads(loja.arquivo_config.read_text(encoding="utf-8"))
        except ValueError:
            cfg = {}
    cfg.update({"nome": nome, "modo": gp.MODO_ESP, "orcamento": bool(orcamento)})
    loja.arquivo_config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def criar_loja(demo: dict) -> Path:
    raiz = AQUI / demo["slug"] / "loja"
    if raiz.exists():
        # preserva as imagens já baixadas/ajustadas; recria só catálogo, config e site
        for item in raiz.iterdir():
            if item.name == "imagens":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        raiz.mkdir(parents=True)
    loja = gp.Loja(raiz)
    loja.imagens.mkdir(exist_ok=True)
    _config_loja(loja, demo["nome"], demo["orcamento"])

    atributos = {"tipos": demo["atributos"], "sinonimos": {}}
    loja.arquivo_atributos.write_text(json.dumps(atributos, ensure_ascii=False, indent=2), encoding="utf-8")
    ce.carregar(loja.arquivo_atributos)

    print(f"\n== {demo['nome']} ==")
    for produto in demo["produtos"]:
        pid = produto["id"]
        pasta = loja.pasta_produto(pid)
        pasta.mkdir(parents=True, exist_ok=True)
        baixar_imagem(produto["prompt"], produto["seed"], pasta / "01.jpg", demo["tema"]["cores"]["fundo"])

        gp.gravar_produto_catalogo(loja, pid, produto["nome"], produto["preco"],
                                   produto["descricao"], produto["categoria"])
        variacoes = produto.get("variacoes") or {}
        combos = pe.gerar_combinacoes(variacoes) if variacoes else [{}]
        linhas = [{
            "atributos": combo,
            "preco": produto["preco"],
            "quantidade": produto["estoque"],
            "ilimitado": False,
            "imagem": f"imagens/{pid}/01.jpg",
        } for combo in combos]
        bl.gravar_esp(loja.banco_estoque(gp.MODO_ESP), pid, produto["nome"], linhas)

    gr.gravar(loja, demo["grupos"])
    print(f"  catálogo: {len(demo['produtos'])} produtos, {len(demo['grupos'])} grupos")
    return raiz


def gerar_site(demo: dict, raiz: Path) -> None:
    pasta = gs.PastaDados(raiz)
    cfg = gs.gravar_cfg(pasta, {
        "nome": demo["nome"],
        "whatsapp": WHATSAPP_DEMO,
        "mensagem_inicial": demo["mensagem_site"],
        "usar_estoque": True,
        "pedido_so_nomes": True,
    })
    gs.gravar_tema(pasta, demo["tema"])
    gs.salvar_logo(pasta, "logo.svg", demo["logo"].encode("utf-8"))
    res = gs.gerar_site(pasta, molde=demo["molde"], tema=demo["tema"],
                        cfg={**cfg, "telegram_usuario": ""})
    print(f"  site: molde {res['molde']} ({res['produtos']} produtos)")

    destino = AQUI / demo["slug"] / "site"
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(raiz / "site", destino)
    zip_path = AQUI / demo["slug"] / "site.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted((raiz / "site").rglob("*")):
            if arq.is_file():
                z.write(arq, arq.relative_to(raiz / "site").as_posix())
    print(f"  site copiado para {destino.relative_to(REPO)} e zipado")


def montar_bot(demo: dict, raiz: Path, bot_dir: Path) -> None:
    if bot_dir.exists():
        shutil.rmtree(bot_dir)
    cfg = montador.config_padrao()
    cfg["canal"] = "telegram"
    cfg["textos"]["SAUDACAO"] = demo["saudacao"]
    cfg["pix"] = {
        "chave": f"demo@{demo['slug']}.com.br",
        "nome": demo["nome"][:25],
        "cidade": "Fortaleza",
    }
    res = montador.montar(str(raiz), str(AQUI / demo["slug"]), "bot", cfg, testar=True)
    print(f"  bot: {res.pasta.relative_to(REPO)}")
    for aviso in res.avisos:
        if "token" not in aviso.lower() and "vendedor" not in aviso.lower():
            print(f"    aviso: {aviso}")


def escrever_como_usar(demo: dict) -> None:
    guias = {
        "otica-visione": (
            "No Telegram: `/start` → seu nome → `óculos de sol` → `solar riviera` → escolha a cor → "
            "o bot pede o endereço (modo orçamento) e registra a visita."
        ),
        "atelie-norte": (
            "No Telegram: `/start` → seu nome → `roupas` → `camisetas` → `camiseta essential preta m` → "
            "`sim` → o bot gera o PIX de demonstração."
        ),
        "bicho-e-cia": (
            "No Telegram: `/start` → seu nome → `alimentos` → `ração` → `ração premium 15kg` → "
            "`sim` → o bot gera o PIX de demonstração."
        ),
    }
    texto = f"""# {demo['nome']} — demonstração

> **Dados fictícios.** Produtos, preços, endereço, PIX e WhatsApp são de demonstração.
> Troque tudo antes de usar com um cliente real.

## Site
- Abra `site/index.html` no navegador (ou hospede a pasta `site/`).
- O `site.zip` é a mesma pasta pronta para subir em Vercel/Cloudflare Pages.
- O botão de pedido usa o WhatsApp fictício `{WHATSAPP_DEMO}`. Troque no montador (aba 2) antes de divulgar.

## Bot (Telegram)
1. Crie um bot no @BotFather e copie o token.
2. Abra `bot/bot_config.json` e preencha `telegram > token`.
3. Rode `bot/iniciar_bot.bat` (Windows) ou `python bot/iniciar.py`.
4. {guias[demo['slug']]}

O bot está com o canal **Telegram** por padrão. Para WhatsApp oficial, use a aba 3 do montador
e uma conta Cloud API da Meta; o canal não oficial (Evolution) é só para teste e pode banir o número.

## Estrutura
- `loja/` — catálogo, imagens, grupos e site gerado.
- `site/` — cópia pronta para hospedar.
- `bot/` — bot montado com uma cópia da loja.
- `site.zip` — pacote do site.

## Observação
As imagens são ilustrativas, geradas para a demonstração. Para o cliente real, use as fotos
dos produtos dele; isso muda muito a conversão.
"""
    (AQUI / demo["slug"] / "COMO-USAR.md").write_text(texto, encoding="utf-8")


def escrever_showcase() -> None:
    cards = []
    for demo in DEMOS:
        primeira = demo["produtos"][0]["id"]
        cards.append(f"""
        <a class="card" href="{demo['slug']}/site/index.html">
          <div class="card-top" style="background:{demo['tema']['cores']['destaque']}">
            <span>{demo['nome']}</span>
          </div>
          <div class="card-body">
            <p>{'Ótica com orçamento e visita' if demo['orcamento'] else 'Catálogo com pedido no WhatsApp'}</p>
            <strong>Abrir demonstração →</strong>
          </div>
        </a>""")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demonstrações — catálogo + atendente</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; background: #f4f1ea; color: #1d2a26; }}
  header {{ max-width: 1000px; margin: 0 auto; padding: 50px 24px 20px; }}
  h1 {{ font-family: Georgia, serif; font-size: clamp(2rem, 5vw, 3.4rem); margin: 0 0 10px; letter-spacing: -1px; }}
  header p {{ color: #5c6b66; max-width: 640px; line-height: 1.55; }}
  .grid {{ max-width: 1000px; margin: 20px auto 60px; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; }}
  .card {{ background: #fff; border: 1px solid #ddd8cd; border-radius: 12px; overflow: hidden; text-decoration: none; color: inherit; box-shadow: 0 6px 18px rgba(0,0,0,.06); transition: transform .2s; }}
  .card:hover {{ transform: translateY(-4px); }}
  .card-top {{ height: 110px; display: flex; align-items: flex-end; padding: 16px; color: #fff; font-weight: 700; font-size: 1.3rem; }}
  .card-body {{ padding: 16px; }}
  .card-body p {{ margin: 0 0 12px; color: #5c6b66; font-size: .9rem; }}
  .card-body strong {{ color: #0d7c6b; }}
  .nota {{ max-width: 1000px; margin: 0 auto 40px; padding: 0 24px; color: #7d8a85; font-size: .8rem; }}
</style></head>
<body>
<header>
  <h1>Demonstrações</h1>
  <p>Três lojas fictícias com catálogo, site e bot de atendimento. Clique para abrir a vitrine.
  Os dados são de demonstração; troque WhatsApp, PIX e produtos antes de usar com um cliente.</p>
</header>
<div class="grid">{''.join(cards)}</div>
<p class="nota">Imagens ilustrativas. Para o cliente real, use fotos dos produtos dele. O bot de cada loja está em <code>bot/</code> com instruções no <code>COMO-USAR.md</code>.</p>
</body></html>"""
    (AQUI / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    print("Gerando demonstrações em", AQUI)
    for demo in DEMOS:
        raiz = criar_loja(demo)
        gerar_site(demo, raiz)
        montar_bot(demo, raiz, AQUI / demo["slug"] / "bot")
        escrever_como_usar(demo)
    escrever_showcase()
    print("\nPronto. Abra demonstracoes/index.html")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
