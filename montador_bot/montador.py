"""montador.py -- monta a pasta PRONTA de um bot a partir da loja cadastrada no catálogo (catalogo/loja/).

    streamlit run montador_ui.py                                (com telas; o catálogo é a aba 1)
    python montador.py --destino C:/bots --perfil meu_perfil.json
    python montador.py --destino C:/bots --loja C:/lojas/pizza-pepi.zip     (opcional: outra loja, pasta ou .zip)
    python montador.py --perfil-modelo meu_perfil.json        (cria um perfil com todos os padrões, para editar)

O que ele faz:
  1. abre a loja (a do catálogo, ou a pasta/.zip dado em --loja) e confere (config.json, banco, fotos);
  2. copia o modelo do bot (modelo/) para <destino>/<nome-do-bot>/ e a loja para <destino>/<nome-do-bot>/loja/
     (sem _arquivo/, backups/, estoque_snapshots/ nem o site/ gerado: o site é entregue à parte, pelo criador_site/);
  3. escreve o bot_config.json (pasta da loja, token, PIX, textos, anti-spam...) e os .bat para ligar tudo;
  4. liga o bot "de mentira" uma vez (só importa e lê a loja) para garantir que a configuração pegou.

Nunca escreve em cima de uma pasta que já existe. A pasta original da loja não é alterada.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import json
import os
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

AQUI = Path(__file__).resolve().parent
MODELO = AQUI / "modelo"
CATALOGO = AQUI / "catalogo"          # o programa de cadastro (faz parte do montador, não vai para o bot)
LOJA_CATALOGO = CATALOGO / "loja"     # a loja única cadastrada nele
CRIADOR_SITE = AQUI / "criador_site"  # o gerador do site da loja (também só do montador; lê a mesma loja)

# (chave em configuracao.py, título para a tela, dica). Os padrões vêm do próprio modelo (nada duplicado aqui).
TEXTOS = [
    ("SAUDACAO", "Saudação (1ª mensagem)", "Primeira mensagem que o cliente recebe. Troque os [colchetes]."),
    ("PERGUNTA_NOME", "Pergunta do nome", ""),
    ("NOME_NAO_ENTENDIDO", "Nome não entendido", ""),
    ("APOS_NOME", "Depois do nome (loja sem categorias)", "{nome} e {exemplo} são trocados pelo bot."),
    ("APOS_NOME_CATEGORIAS", "Depois do nome (antes da lista de categorias)", "{nome}"),
    ("TEXTO_CATEGORIAS_TOPO", "Lista de categorias: topo", ""),
    ("TEXTO_CATEGORIAS_RODAPE", "Lista de categorias: rodapé", ""),
    ("PEDIR_NOME_COM_CODIGO", "Pedido da página, pedindo o nome", ""),
    ("TEXTO_PEDIR_NOME_NO_FIM", "Pedido da página recebido, falta o nome", "{total} é o valor do pedido."),
    ("TEXTO_AGUARDANDO", "Aguardando pagamento", "Vai depois do PIX."),
    ("TEXTO_CONFIRMADA", "Pagamento confirmado", "{nome} e {numero}."),
    ("TEXTO_CANCELADA", "Comanda cancelada", "{numero}."),
    ("TEXTO_CARRINHO_EXPIRADO", "Carrinho parado expirou", ""),
    ("TEXTO_BLOQUEIO_REPETIDO", "Aviso: mensagens repetidas", "{minutos} = duração do bloqueio."),
    ("TEXTO_BLOQUEIO_SEM_SENTIDO", "Aviso: bot não entendeu", "{minutos} = duração do bloqueio."),
    ("TEXTO_AVISO_DONO", "Aviso de nova comanda (para o vendedor)", "{numero} {nome} {chave} {itens} {total}"),
    ("TEXTO_AJUDA_DONO", "Ajuda do vendedor", ""),
    ("TEXTO_VITRINE_TOPO", "Vitrine: topo", "{categoria}"),
    ("TEXTO_VITRINE_VARIAS", "Vitrine: várias categorias", "{exemplo}"),
    ("TEXTO_VITRINE_RODAPE", "Vitrine: rodapé", "{exemplo}"),
    ("TEXTO_VITRINE_VAZIA", "Vitrine: categoria sem itens", "{categoria}"),
    ("TEXTO_CATEGORIAS_GRUPOS", "Vitrine: título dos grupos", "Aparece antes da lista de grupos (subcategorias)."),
    ("TEXTO_CATEGORIAS_OUTRAS", "Vitrine: título das categorias soltas", "Categorias que não estão em grupo nenhum."),
    ("TEXTO_SUBCATEGORIAS_TOPO", "Vitrine: subcategorias do grupo", "{grupo} é trocado pelo nome do grupo."),
    ("TEXTO_SUBCATEGORIAS_RODAPE", "Vitrine: rodapé das subcategorias", ""),
    ("TEXTO_PIX_NAO_CONFIGURADO", "Aviso: PIX não configurado", ""),
    # loja por orçamento (só valem quando a loja está marcada como «por orçamento» no catálogo)
    ("TEXTO_PEDIR_ENDERECO", "Orçamento: pedir o endereço", ""),
    ("TEXTO_ENDERECO_INVALIDO", "Orçamento: endereço não entendido", ""),
    ("TEXTO_FECHADO_ORCAMENTO", "Orçamento: comanda fechada (cliente)", "{nome} {numero} {itens} {endereco}"),
    ("TEXTO_VISITA_CONFIRMADA", "Orçamento: visita confirmada (cliente)", "{nome} e {numero}."),
    ("TEXTO_AVISO_DONO_ORCAMENTO", "Orçamento: aviso de nova comanda (vendedor)",
     "{numero} {nome} {chave} {endereco} {itens} {minutos}"),
]
CHAVES_TEXTO = [t[0] for t in TEXTOS]


CANAIS = {"telegram": "Telegram (só para testes)",
          "whatsapp_oficial": "WhatsApp oficial (Cloud API da Meta)",
          "whatsapp_nao_oficial": "WhatsApp não oficial (Evolution API)"}
RE_TELEFONE = re.compile(r"\+?\d{10,15}")
RE_BSUID = re.compile(r"[A-Za-z]{2}\.[A-Za-z0-9.]{6,}")   # ex.: US.13491208655302741918


class ErroMontagem(Exception):
    """Algo impede de montar; a mensagem já está em linguagem simples."""


# ============================================================ padrões (lidos do próprio modelo)
@contextlib.contextmanager
def _modelo_importavel() -> Iterator[None]:
    """Deixa importar módulos do modelo sem sujar o processo (nem ler variáveis do seu ambiente)."""
    guardadas = {k: os.environ.pop(k) for k in list(os.environ)
                 if k.startswith("BOT_") or k in ("PIX_CHAVE", "PIX_NOME", "PIX_CIDADE")}
    antes = set(sys.modules)
    sys.path.insert(0, str(MODELO))
    try:
        yield
    finally:
        sys.path.remove(str(MODELO))
        for nome in set(sys.modules) - antes:
            sys.modules.pop(nome, None)
        os.environ.update(guardadas)


def _carregar_modulo(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def config_padrao() -> dict:
    """Configuração completa com os valores padrão do modelo."""
    with _modelo_importavel():
        c = _carregar_modulo("_cfg_modelo", MODELO / "atendimento" / "configuracao.py")
        textos = {k: getattr(c, k) for k in CHAVES_TEXTO}
        return {
            "loja": {"pasta": ""},
            "telegram": {"token": "", "donos": [], "usuario": ""},   # usuario = @do bot, só para montar o link do site
            "pix": {"chave": "", "nome": "", "cidade": ""},
            "canal": "telegram",   # telegram (só para testes) | whatsapp_oficial | whatsapp_nao_oficial
            "whatsapp_oficial": {"token": "", "phone_number_id": "", "app_secret": "", "verify_token": "",
                                 "versao_api": "v23.0", "donos": [], "porta": 8000,
                                 "template_aviso_nome": "", "template_aviso_idioma": "pt_BR"},
            "whatsapp_nao_oficial": {"url_api": "http://localhost:8080", "apikey": "", "instancia": "",
                                     "token_webhook": "", "donos": [], "porta": 8001},
            "textos": textos,
            "antispam": {"max_mensagens_iguais": c.MAX_MENSAGENS_IGUAIS, "max_sem_sentido": c.MAX_SEM_SENTIDO,
                         "timeout_min": c.TIMEOUT_BLOQUEIO_S // 60, "janela_min": c.JANELA_REPETICAO_S // 60},
            "carrinho_minutos": c.TEMPO_CARRINHO_S // 60,
            "orcamento_pausa_minutos": c.PAUSA_ORCAMENTO_S // 60,   # loja por orçamento: bot calado depois da comanda
            "trabalhadores": 8,
        }


def aplicar_perfil(base: dict, perfil: dict) -> dict:
    """Devolve `base` com os valores de `perfil` por cima. Só entram chaves que existem no padrão."""
    saida = copy.deepcopy(base)
    for secao, valor in (perfil or {}).items():
        if secao == "loja" or secao not in saida:
            continue   # a pasta da loja é sempre a do montador, nunca a de um perfil antigo
        if isinstance(saida[secao], dict) and isinstance(valor, dict):
            for k, v in valor.items():
                if k in saida[secao]:
                    saida[secao][k] = v
        elif not isinstance(saida[secao], dict):
            saida[secao] = valor
    return saida


def ler_perfil(caminho) -> dict:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ErroMontagem(f"Não consegui ler o perfil '{caminho}': {e}") from e
    if not isinstance(dados, dict):
        raise ErroMontagem(f"O perfil '{caminho}' precisa ser um objeto JSON.")
    return dados


# ============================================================ validação da configuração
def _limpar_donos(valor) -> list:
    return [str(d).strip().removeprefix("tg:").removeprefix("wa:") for d in (valor or []) if str(d).strip()]


def _porta_ok(valor) -> bool:
    try:
        return 1 <= int(valor) <= 65535
    except (TypeError, ValueError):
        return False


def _validar_canal(cfg: dict, canal: str, erros: list, avisos: list) -> None:
    if canal == "telegram":
        tg = cfg.get("telegram") or {}
        token = str(tg.get("token") or "").strip()
        if not token:
            avisos.append("Sem token do Telegram: o bot não liga até você preencher (bot_config.json > telegram > token).")
        elif not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", token):
            avisos.append("O token do Telegram não parece o formato do @BotFather (123456:ABC...). Confira.")
        usuario = str(tg.get("usuario") or "").strip().lstrip("@")
        if usuario and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", usuario):
            erros.append("O @usuario do bot do Telegram tem de ter 5 a 32 letras, números ou _ (ex.: MinhaLoja_bot).")
        donos = _limpar_donos(tg.get("donos"))
        ruins = [d for d in donos if not re.fullmatch(r"-?\d+", d)]
        if ruins:
            erros.append(f"Vendedor (chat id) precisa ser só número: {', '.join(ruins)}. Mande /id ao bot para descobrir o seu.")
        if not donos:
            avisos.append("Nenhum vendedor definido: ninguém confirma/cancela comandas pelo chat nem recebe o aviso de comanda nova "
                          "(com o bot ligado, mande /id para ele e depois preencha).")
        return
    chave = canal
    s = cfg.get(chave) or {}
    donos = _limpar_donos(s.get("donos"))
    if not _porta_ok(s.get("porta")):
        erros.append("A porta do webhook precisa ser um número entre 1 e 65535.")
    if canal == "whatsapp_oficial":
        for campo, rotulo in (("token", "o token de acesso"), ("phone_number_id", "o ID do número (phone_number_id)"),
                              ("app_secret", "o segredo do app (app_secret)")):
            if not str(s.get(campo) or "").strip():
                avisos.append(f"WhatsApp oficial sem {rotulo}: o bot não liga até você preencher (whatsapp_oficial > {campo}).")
        pni = str(s.get("phone_number_id") or "").strip()
        if pni and not pni.isdigit():
            erros.append("phone_number_id precisa ser só números (é o ID do número no painel da Meta, não o telefone).")
        if not re.fullmatch(r"v\d+\.\d+", str(s.get("versao_api") or "")):
            erros.append("versao_api precisa ter o formato v23.0.")
        ruins = [d for d in donos if not (RE_TELEFONE.fullmatch(d) or RE_BSUID.fullmatch(d))]
        if ruins:
            erros.append(f"Vendedor do WhatsApp oficial: use telefone com DDI e DDD (5585999999999) ou o BSUID (US.123...): {', '.join(ruins)}.")
        if str(s.get("template_aviso_nome") or "").strip() and not str(s.get("template_aviso_idioma") or "").strip():
            erros.append("Template de aviso: falta o idioma (ex.: pt_BR).")
    else:
        if not str(s.get("url_api") or "").startswith(("http://", "https://")):
            erros.append("url_api da Evolution precisa começar com http:// ou https://.")
        for campo in ("apikey", "instancia"):
            if not str(s.get(campo) or "").strip():
                avisos.append(f"WhatsApp não oficial sem {campo}: o bot não liga até você preencher (whatsapp_nao_oficial > {campo}).")
        ruins = [d for d in donos if not RE_TELEFONE.fullmatch(d)]
        if ruins:
            erros.append(f"Vendedor do WhatsApp não oficial: use o telefone com DDI e DDD (5585999999999): {', '.join(ruins)}.")
        avisos.append("Canal NÃO OFICIAL: viola os termos do WhatsApp e o número pode ser banido. Use um chip reserva, só para teste.")
    if not donos:
        avisos.append("Nenhum vendedor definido: ninguém confirma/cancela comandas pelo chat nem recebe o aviso de comanda nova "
                      "(com o bot ligado, mande 'id' para ele e depois preencha).")


def _campos(texto: str) -> list:
    return [nome for _, nome, _, _ in string.Formatter().parse(texto) if nome is not None]


def validar_config(cfg: dict) -> tuple:
    """(erros, avisos). Erro impede de montar; aviso só é mostrado."""
    erros, avisos = [], []
    padrao = config_padrao()

    # textos: um {campo} errado derrubaria o bot no meio de uma conversa, então é erro
    for chave, _, _ in TEXTOS:
        usado = (cfg.get("textos") or {}).get(chave)
        if not isinstance(usado, str) or not usado.strip():
            continue
        permitido = set(_campos(padrao["textos"][chave]))
        if not permitido:
            continue   # texto sem {campos}: o bot não usa .format nele, chaves são texto comum
        try:
            campos = _campos(usado)
            usado.format(**{c: "x" for c in permitido})
        except (ValueError, KeyError, IndexError, AttributeError) as e:
            erros.append(f"Texto {chave}: chaves {{ }} mal fechadas ou campo inválido ({e}).")
            continue
        invalidos = sorted(set(campos) - permitido)
        if invalidos:
            erros.append(f"Texto {chave}: o campo {{{invalidos[0]}}} não existe aqui. "
                         f"Campos válidos: {', '.join('{' + p + '}' for p in sorted(permitido))}.")
    saudacao = (cfg.get("textos") or {}).get("SAUDACAO", "")
    sobras = re.findall(r"\[[^\]\n]+\]", saudacao)
    if sobras:
        avisos.append(f"A saudação ainda tem trechos para preencher: {', '.join(sobras)}.")

    # canal (só o escolhido é cobrado; os outros ficam guardados no bot_config.json)
    canal = cfg.get("canal") or "telegram"
    if canal not in CANAIS:
        erros.append(f"Canal '{canal}' não existe. Use: {', '.join(CANAIS)}.")
    else:
        _validar_canal(cfg, canal, erros, avisos)

    # pix
    pix = cfg.get("pix") or {}
    preenchidos = [k for k in ("chave", "nome", "cidade") if str(pix.get(k) or "").strip()]
    if preenchidos and len(preenchidos) < 3:
        faltam = [k for k in ("chave", "nome", "cidade") if k not in preenchidos]
        erros.append(f"PIX incompleto: falta {', '.join(faltam)}. Preencha os três ou deixe os três vazios.")
    elif not preenchidos:
        avisos.append("PIX vazio: o bot fecha a comanda mas avisa o cliente que o PIX não está configurado.")
    else:
        if len(str(pix["nome"]).strip()) > 25:
            avisos.append("Nome do recebedor do PIX passa de 25 letras: o bot corta em 25.")
        if len(str(pix["cidade"]).strip()) > 15:
            avisos.append("Cidade do PIX passa de 15 letras: o bot corta em 15.")

    # números
    limites = [("antispam", "max_mensagens_iguais", 2, 50, "mensagens iguais seguidas"),
               ("antispam", "max_sem_sentido", 2, 50, "mensagens sem sentido seguidas"),
               ("antispam", "timeout_min", 1, 1440, "minutos de bloqueio"),
               ("antispam", "janela_min", 1, 1440, "janela de repetição (min)"),
               (None, "carrinho_minutos", 1, 1440, "minutos até o carrinho parado expirar"),
               (None, "orcamento_pausa_minutos", 1, 1440, "minutos de bot calado depois da comanda de orçamento"),
               (None, "trabalhadores", 1, 64, "atendimentos em paralelo")]
    for secao, chave, lo, hi, rotulo in limites:
        valor = (cfg.get(secao) or {}).get(chave) if secao else cfg.get(chave)
        try:
            n = int(valor)
            if not lo <= n <= hi:
                raise ValueError
        except (TypeError, ValueError):
            erros.append(f"'{rotulo}' precisa ser um número inteiro entre {lo} e {hi} (veio: {valor!r}).")
    return erros, avisos


# ============================================================ a loja (pasta ou zip)
def slug(texto: str, padrao: str = "bot") -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or padrao


@dataclass
class Loja:
    raiz: Path
    slug: str
    nome: str = ""
    modo: str = ""
    produtos: int = 0
    skus: int = 0
    avisos: list = field(default_factory=list)


def _modos() -> dict:
    try:
        with _modelo_importavel():
            return dict(_carregar_modulo("_const_modelo", MODELO / "estoque" / "constantes.py").DB_POR_MODO)
    except Exception:   # modelo mexido à mão: cai no que o bot original suporta
        return {"especializado": "produtos_especializados.db"}


def _ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _achar_raiz(base: Path) -> Path:
    """A pasta da loja é a que tem config.json com "modo". Procura até 3 níveis (zip com pasta dentro de pasta)."""
    direto = _ler_json(base / "config.json")
    if isinstance(direto, dict) and "modo" in direto:   # a própria pasta é a loja (caso do catálogo): sem varrer fotos
        return base
    achados = []
    for conf in sorted(base.rglob("config.json")):
        rel = conf.relative_to(base).parts
        if len(rel) > 4 or "__MACOSX" in rel:
            continue
        dados = _ler_json(conf)
        if isinstance(dados, dict) and "modo" in dados:
            achados.append(conf.parent)
    if not achados:
        raise ErroMontagem("Não achei uma loja ali: procurei um config.json com \"modo\" (a pasta que tem "
                           "produtos_especializados.db, atributos.json e imagens/).")
    achados.sort(key=lambda p: len(p.relative_to(base).parts))
    menor = len(achados[0].relative_to(base).parts)
    topo = [p for p in achados if len(p.relative_to(base).parts) == menor]
    if len(topo) > 1:
        raise ErroMontagem("Achei mais de uma loja nesse arquivo: " + ", ".join(p.name for p in topo)
                           + ". Aponte para a pasta de UMA loja.")
    return topo[0]


def _conferir_loja(raiz: Path, nome_padrao: str) -> Loja:
    conf = _ler_json(raiz / "config.json") or {}
    modos = _modos()
    modo = conf.get("modo", "")
    if modo not in modos:
        raise ErroMontagem(f"O modo '{modo}' do config.json não é suportado (suportados: {', '.join(modos)}).")
    loja = Loja(raiz=raiz, slug=slug(raiz.name if raiz.name else nome_padrao, slug(nome_padrao)),
                nome=str(conf.get("nome") or raiz.name), modo=modo)
    banco = raiz / modos[modo]
    if not banco.is_file():
        raise ErroMontagem(f"Falta o banco '{modos[modo]}' dentro da loja '{raiz.name}'.")
    if (raiz / "atributos.json").exists() and not isinstance(_ler_json(raiz / "atributos.json"), dict):
        raise ErroMontagem("O atributos.json da loja não é um JSON válido.")
    try:
        con = sqlite3.connect(banco.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            loja.produtos = con.execute("SELECT COUNT(*) FROM produtos WHERE ativo = 1").fetchone()[0]
            loja.skus = con.execute("SELECT COUNT(*) FROM skus WHERE ativo = 1").fetchone()[0]
            urls = [u for (u,) in con.execute("SELECT url FROM imagens UNION SELECT url FROM imagens_sku")]
        finally:
            con.close()
    except sqlite3.Error as e:
        raise ErroMontagem(f"Não consegui ler o banco da loja ({e}).") from e
    if loja.skus == 0:
        loja.avisos.append("A loja não tem nenhum item ativo à venda (skus ativos = 0): o bot vai responder que não achou nada.")
    faltando = [u for u in urls if "://" not in u and not os.path.isabs(u) and not (raiz / u).is_file()]
    if faltando:
        loja.avisos.append(f"{len(faltando)} foto(s) citada(s) no banco não estão na pasta (ex.: {', '.join(faltando[:3])}).")
    return loja


def _extrair_zip_seguro(arquivo: Path, destino: Path) -> None:
    base = destino.resolve()
    with zipfile.ZipFile(arquivo) as z:
        for membro in z.namelist():
            alvo = (destino / membro).resolve()
            if alvo != base and base not in alvo.parents:
                raise ErroMontagem(f"O zip tem um caminho suspeito ('{membro}') e não foi aberto.")
        z.extractall(destino)


@contextlib.contextmanager
def abrir_loja(origem) -> Iterator[Loja]:
    """Aceita a pasta da loja ou um .zip dela. Para zip, abre numa pasta temporária que some no fim."""
    origem = Path(str(origem).strip().strip('"')).expanduser()
    if not origem.exists():
        raise ErroMontagem(f"Não achei '{origem}'.")
    tmp = None
    try:
        if origem.is_file():
            if origem.suffix.lower() != ".zip":
                raise ErroMontagem("Só aceito a pasta da loja ou um arquivo .zip (o .rar precisa ser extraído antes).")
            tmp = Path(tempfile.mkdtemp(prefix="montador_"))
            try:
                _extrair_zip_seguro(origem, tmp)
            except zipfile.BadZipFile as e:
                raise ErroMontagem("Esse .zip está corrompido ou não é um zip de verdade.") from e
            base, nome_padrao = tmp, origem.stem
        else:
            base, nome_padrao = origem, origem.name
        raiz = _achar_raiz(base)
        loja = _conferir_loja(raiz, nome_padrao)
        if raiz == tmp:   # zip com os arquivos soltos (sem pasta dentro): o nome vem do zip
            loja.slug = slug(nome_padrao)
        yield loja
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ a montagem
@dataclass
class Resultado:
    pasta: Path
    pasta_loja: Path
    avisos: list
    passos: list


def _bat(linhas: list) -> str:
    return "\r\n".join(["@echo off", 'cd /d "%~dp0"'] + linhas + [""])


def _texto_link_site(usuario: str) -> str:
    u = usuario or "SEU_BOT"
    return (f"\nLIGAR O SITE AO TELEGRAM\n  Botão do site abre:  https://t.me/{u}?start=<carrinho>\n"
            "  <carrinho> = o mesmo código do WhatsApp, com \"-\" no lugar de \",\" (o Telegram não aceita vírgula).\n"
            f"  Ex.: https://t.me/{u}?start=2A001_PR_G-1A000_VE_M   (limite: 64 caracteres no carrinho).\n"
            f"  Carrinho maior: o site copia o código e abre https://t.me/{u}; o cliente cola na conversa.\n")


def _escrever_arquivos_de_apoio(destino: Path, nome_loja: str, usuario: str = "") -> None:
    (destino / "iniciar_bot.bat").write_text(_bat([
        "python -m pip install --quiet requests rapidfuzz",
        "python iniciar.py", "echo.", "echo O bot parou. Leia a mensagem acima.", "pause"]), encoding="utf-8", newline="")
    (destino / "abrir_painel.bat").write_text(_bat([
        "python -m pip install --quiet streamlit pandas",
        "python -m streamlit run interface_loja.py", "echo.", "echo O painel parou. Leia a mensagem acima.", "pause"]),
        encoding="utf-8", newline="")
    (destino / "alterar_loja.bat").write_text(_bat([
        "python alterar_loja.py", "echo.", "pause"]), encoding="utf-8", newline="")
    (destino / "requirements.txt").write_text("requests\nrapidfuzz\nstreamlit\npandas\n", encoding="utf-8")
    (destino / ".gitignore").write_text("bot_config.json\n*.db\n*.db-wal\n*.db-shm\n__pycache__/\n", encoding="utf-8")
    (destino / "LEIA-ME.txt").write_text(
        f"Bot da loja: {nome_loja}\n(montado pelo montador_bot)\n\n"
        "COMO USAR\n"
        "  iniciar_bot.bat       liga o bot no canal escolhido em bot_config.json (\"canal\")\n"
        "  abrir_painel.bat      painel do dono: comandas, mensagens, catálogo (adicionar, editar, remover produtos) e estoque\n"
        "  alterar_loja.bat      mudança simples: preço, nome, descrição e categoria dos produtos\n"
        "\nCANAIS (campo \"canal\" do bot_config.json; cada um também roda direto com python <arquivo>)\n"
        "  telegram              telegram_bot.py           só para testes, não precisa de servidor\n"
        "  whatsapp_oficial      whatsapp_oficial.py       Cloud API da Meta; precisa de URL pública HTTPS para o webhook\n"
        "  whatsapp_nao_oficial  whatsapp_nao_oficial.py   via Evolution API (QR code); risco de banimento, só para teste\n"
        "  O passo a passo de cada um está no começo do próprio arquivo .py.\n"
        + _texto_link_site(usuario) +
        "\nCONFIGURAÇÃO\n"
        "  Tudo que muda de uma loja para outra está em bot_config.json: token, vendedores, PIX, textos,\n"
        "  anti-spam e a pasta da loja. Pode editar com o bloco de notas; feche e abra o bot para valer.\n"
        "  Variáveis de ambiente (TELEGRAM_TOKEN, PIX_CHAVE...) têm prioridade sobre o arquivo.\n\n"
        "CUIDADO\n"
        "  bot_config.json tem o token do bot: não envie esta pasta para ninguém sem apagar o token antes.\n"
        "  comandas.db e mensagens.db (criados quando o bot roda) têm dados de clientes.\n", encoding="utf-8")


def _teste_de_fumaca(destino: Path, esperado: dict, avisos: list, passos: list) -> None:
    """Importa o bot gerado (como o telegram_bot.py faria) e confere que ele leu a loja e o bot_config.json."""
    try:
        import rapidfuzz  # noqa: F401
    except ImportError:
        avisos.append("Não testei o bot montado: falta instalar o rapidfuzz neste Python (pip install rapidfuzz). "
                      "Ele é instalado sozinho pelo iniciar_bot.bat.")
        return
    codigo = ("import json,sys\n"
              "import canal_comum, whatsapp_oficial, whatsapp_nao_oficial\n"
              "from atendimento import atendimento as a, configuracao as c\n"
              "print(json.dumps({'produtos': len(a.estoque.produtos), 'saudacao': c.SAUDACAO, 'pasta': c.PASTA_ESTOQUE}))\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOT_") and k not in ("PIX_CHAVE", "PIX_NOME", "PIX_CIDADE")}
    antes = {p for p in destino.glob("*.db*")}
    try:
        r = subprocess.run([sys.executable, "-c", codigo], cwd=destino, env=env, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        avisos.append("O teste do bot montado demorou demais e foi cancelado.")
        return
    finally:   # o teste não deve deixar bancos ou cache na pasta do cliente
        for p in set(destino.glob("*.db*")) - antes:
            p.unlink(missing_ok=True)
        for c in destino.rglob("__pycache__"):
            shutil.rmtree(c, ignore_errors=True)
    if r.returncode:
        avisos.append("O bot montado NÃO abriu no teste: " + (r.stderr.strip().splitlines() or ["erro desconhecido"])[-1])
        return
    try:
        dados = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        avisos.append("O teste do bot montado respondeu algo inesperado.")
        return
    if dados["saudacao"] != esperado["textos"]["SAUDACAO"]:
        avisos.append("O bot montado não está lendo a saudação do bot_config.json. Confira o modelo/.")
    else:
        passos.append(f"Teste do bot montado: abriu, leu a loja ({dados['produtos']} produtos) e o bot_config.json.")


def montar(origem_loja, pasta_destino, nome_bot: str, config: dict, testar: bool = True, exe: bool = False) -> Resultado:
    """Monta <pasta_destino>/<nome_bot>/ pronto para usar. Levanta ErroMontagem se algo impedir.
    `origem_loja`: pasta ou .zip de uma loja; None = a loja do catálogo (catalogo/loja/)."""
    erros, avisos = validar_config(config)
    if erros:
        raise ErroMontagem("Corrija antes de montar:\n- " + "\n- ".join(erros))
    if not MODELO.is_dir():
        raise ErroMontagem(f"Não achei a pasta modelo/ ao lado do montador ({MODELO}).")
    nome_pasta = slug(nome_bot, "bot")
    destino = Path(pasta_destino).expanduser().resolve() / nome_pasta
    if destino.exists() and any(destino.iterdir()):
        raise ErroMontagem(f"A pasta '{destino}' já existe e não está vazia. Por segurança não escrevo em cima "
                           "(pode ter comandas e conversas). Escolha outro nome ou apague a pasta antes.")
    passos = []
    with abrir_loja(origem_loja or LOJA_CATALOGO) as loja:
        avisos = list(loja.avisos) + avisos
        loja_orcamento = bool((_ler_json(loja.raiz / "config.json") or {}).get("orcamento"))
        if loja_orcamento:   # sem PIX: a comanda fecha como visita
            avisos = [a for a in avisos if not a.startswith("PIX vazio")]
        try:
            shutil.copytree(MODELO, destino, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
            passos.append("Copiei o modelo do bot.")
            rel_loja = Path("loja")
            pasta_loja = destino / rel_loja
            comuns = shutil.ignore_patterns("__pycache__", "*.pyc", "_arquivo", "backups", "estoque_snapshots")

            def ignorar(pasta_atual, nomes):   # o site/ gerado só sai da raiz da loja (nada com esse nome mais fundo)
                saida = set(comuns(pasta_atual, nomes))
                if Path(pasta_atual) == loja.raiz and "site" in nomes:
                    saida.add("site")
                return saida
            shutil.copytree(loja.raiz, pasta_loja, ignore=ignorar)
            passos.append(f"Copiei a loja '{loja.nome}' ({loja.produtos} produtos, {loja.skus} variações) para {rel_loja.as_posix()}/.")
            if loja_orcamento:
                passos.append("Loja por orçamento: o bot não mostra preços, pede o endereço e fecha a comanda como visita (sem PIX); "
                              f"depois de fechar fica calado com o cliente por {config['orcamento_pausa_minutos']} min ou até o atendente ligar.")
            final = copy.deepcopy(config)
            final["loja"] = {"pasta": rel_loja.as_posix()}
            final["telegram"]["usuario"] = str(final["telegram"].get("usuario") or "").strip().lstrip("@")
            final["telegram"]["donos"] = _limpar_donos(final["telegram"].get("donos"))
            for canal_ in ("whatsapp_oficial", "whatsapp_nao_oficial"):
                final[canal_]["donos"] = _limpar_donos(final[canal_].get("donos"))
            for canal_, campo in (("whatsapp_oficial", "verify_token"), ("whatsapp_nao_oficial", "token_webhook")):
                if not str(final[canal_].get(campo) or "").strip():
                    final[canal_][campo] = secrets.token_urlsafe(16)   # inventado aqui; cadastre o mesmo na Meta/Evolution
                    if canal_ == final.get("canal"):
                        passos.append(f"Gerei o {campo} do WhatsApp ({final[canal_][campo]}): use o mesmo ao cadastrar o webhook.")
            (destino / "bot_config.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
            passos.append("Escrevi o bot_config.json (pasta da loja, token, PIX, textos e ajustes).")
            _escrever_arquivos_de_apoio(destino, loja.nome, final['telegram']['usuario'])
            passos.append("Criei os atalhos .bat, o requirements.txt e o LEIA-ME.txt.")
            for py in destino.rglob("*.py"):   # sintaxe de tudo que foi copiado, sem gravar cache
                compile(py.read_text(encoding="utf-8"), str(py), "exec")
            if testar:
                _teste_de_fumaca(destino, final, avisos, passos)
            if exe:   # por último: depois do teste, troca o código-fonte por executáveis
                import construir_exe
                try:
                    construir_exe.converter(destino, passos, avisos)
                except RuntimeError as e:
                    raise ErroMontagem(str(e)) from e
        except BaseException:
            shutil.rmtree(destino, ignore_errors=True)   # montagem pela metade não fica para trás
            raise
    return Resultado(pasta=destino, pasta_loja=pasta_loja, avisos=avisos, passos=passos)


# ============================================================ linha de comando
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Monta a pasta pronta de um bot a partir da loja do catálogo.")
    ap.add_argument("--loja", help="(opcional) pasta ou .zip de outra loja; sem isto vale a loja do catálogo (catalogo/loja)")
    ap.add_argument("--destino", help="pasta onde criar o bot (ele vira uma subpasta)")
    ap.add_argument("--nome", help="nome da pasta do bot (padrão: bot-<nome da loja>)")
    ap.add_argument("--perfil", help="bot_config.json de outro bot, para reaproveitar as configurações")
    ap.add_argument("--perfil-modelo", metavar="ARQUIVO", help="grava um perfil com todos os padrões e sai")
    ap.add_argument("--canal", choices=list(CANAIS), help="canal do bot (padrão: telegram)")
    ap.add_argument("--usuario-telegram", help="@do bot do Telegram (para o link do site)")
    ap.add_argument("--token"), ap.add_argument("--donos", help="vendedores (do canal escolhido), separados por vírgula")
    ap.add_argument("--pix-chave"), ap.add_argument("--pix-nome"), ap.add_argument("--pix-cidade")
    ap.add_argument("--saudacao")
    ap.add_argument("--sem-teste", action="store_true", help="não abrir o bot montado para testar")
    ap.add_argument("--exe", action="store_true", help="entregar só executáveis (sem código-fonte); precisa do PyInstaller, no Windows")
    a = ap.parse_args(argv)
    try:
        if a.perfil_modelo:
            Path(a.perfil_modelo).write_text(json.dumps(config_padrao(), indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Perfil padrão gravado em {a.perfil_modelo}")
            return 0
        if not a.destino:
            ap.error("--destino é obrigatório")
        cfg = config_padrao()
        if a.perfil:
            cfg = aplicar_perfil(cfg, ler_perfil(a.perfil))
        if a.canal:
            cfg["canal"] = a.canal
        secao = cfg["canal"]   # o nome do canal é também o nome da seção no bot_config.json
        if a.token:   # credencial principal do canal: token (telegram, oficial) ou apikey (não oficial)
            cfg[secao]["apikey" if secao == "whatsapp_nao_oficial" else "token"] = a.token
        if a.usuario_telegram:
            cfg["telegram"]["usuario"] = a.usuario_telegram
        if a.donos:
            cfg[secao]["donos"] = [d for d in a.donos.split(",") if d.strip()]
        for campo, valor in (("chave", a.pix_chave), ("nome", a.pix_nome), ("cidade", a.pix_cidade)):
            if valor:
                cfg["pix"][campo] = valor
        if a.saudacao:
            cfg["textos"]["SAUDACAO"] = a.saudacao
        with abrir_loja(a.loja or LOJA_CATALOGO) as l:
            nome = a.nome or f"bot-{slug(l.nome, l.slug)}"
        r = montar(a.loja, a.destino, nome, cfg, testar=not a.sem_teste, exe=a.exe)
    except ErroMontagem as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"Bot montado em: {r.pasta}\n")
    print("\n".join(f"  OK {p}" for p in r.passos))
    if r.avisos:
        print("\nAtenção:\n" + "\n".join(f"  ! {w}" for w in r.avisos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
