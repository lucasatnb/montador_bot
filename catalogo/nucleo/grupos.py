"""Grupos de categorias: um nível acima das categorias atuais.

As categorias de sempre (catalogo.db > produtos.categoria) viram "subcategorias"; este
arquivo só diz qual grupo fica acima de qual categoria:

    <loja>/grupos_categorias.json
    {"Roupas Masculinas": ["Camisetas", "Calças"], "Calçados": ["Tênis", "Sapatos"]}

Regras:
- cada categoria pertence a NO MÁXIMO um grupo;
- nomes de grupo não distinguem maiúsculas/minúsculas/acento;
- sem o arquivo (ou vazio) nada muda: todas as categorias ficam soltas, como hoje.
"""
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

NOME = "grupos_categorias.json"


class GruposInvalidos(ValueError):
    """Violação de regra dos grupos, com mensagem em linguagem simples."""


def _raiz(loja):
    """Path da pasta da loja (aceita objeto com .raiz ou o próprio Path)."""
    raiz = getattr(loja, "raiz", None) or loja
    return Path(raiz)


def arquivo(loja):
    return _raiz(loja) / NOME


def _chave(texto):
    """minúsculas, sem acento, espaços únicos (para comparar nomes sem ligar para grafia)."""
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", s.lower()).split())


def limpar(texto):
    return " ".join(str(texto or "").split())


def ler(loja):
    """{grupo: [categorias]} do arquivo da loja, ou {} se ele não existe / é ilegível."""
    caminho = arquivo(loja)
    if not caminho.is_file():
        return {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(bruto, dict):
        return {}
    dados = {}
    for grupo, categorias in bruto.items():
        g = limpar(grupo)
        lista = [limpar(c) for c in categorias] if isinstance(categorias, list) else []
        lista = [c for c in lista if c]
        if g:
            dados[g] = lista
    return dados


def validar(dados):
    """Lista de problemas (vazia = tudo certo). Uma categoria em dois grupos é erro."""
    problemas = []
    vistos = {}
    for grupo, categorias in dados.items():
        g = limpar(grupo)
        if not g:
            problemas.append("Grupo sem nome.")
            continue
        for c in categorias:
            c = limpar(c)
            if not c:
                continue
            dono = vistos.get(_chave(c))
            if dono and dono != _chave(g):
                problemas.append(f"A categoria '{c}' está em «{dono}» e em «{g}». "
                                 f"Cada categoria pode estar em um grupo só.")
            else:
                vistos[_chave(c)] = _chave(g)
    nomes = [_chave(g) for g in dados]
    if len(set(nomes)) != len(nomes):
        problemas.append("Há grupos com o mesmo nome (letras maiúsculas/acento não distinguem).")
    return problemas


def gravar(loja, dados):
    """Valida e grava o arquivo (escrita atômica). Levanta GruposInvalidos se houver problema."""
    limpo = {}
    for grupo, categorias in dados.items():
        g = limpar(grupo)
        lista = []
        for c in categorias if isinstance(categorias, list) else []:
            c = limpar(c)
            if c and c not in lista:
                lista.append(c)
        if g:
            limpo[g] = lista
    problemas = validar(limpo)
    if problemas:
        raise GruposInvalidos("Corrija antes de gravar:\n- " + "\n- ".join(problemas))
    caminho = arquivo(loja)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="grupos_", suffix=".tmp", dir=str(caminho.parent))
    os.close(fd)
    try:
        Path(tmp).write_text(json.dumps(limpo, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def grupo_da_categoria(dados, categoria):
    """Nome do grupo da categoria, ou None se ela está solta."""
    alvo = _chave(categoria)
    for grupo, categorias in dados.items():
        if any(_chave(c) == alvo for c in categorias):
            return grupo
    return None


def categorias_do_grupo(dados, grupo):
    """Categorias do grupo (como estão escritas no arquivo)."""
    alvo = _chave(grupo)
    for g, categorias in dados.items():
        if _chave(g) == alvo:
            return list(categorias)
    return []


def sem_grupo(categorias, dados):
    """Categorias (já existentes na loja) que não estão em grupo nenhum, na ordem dada."""
    return [c for c in categorias if grupo_da_categoria(dados, c) is None]


def adicionar_grupo(dados, grupo, categorias=()):
    """Devolve um dicionário novo com o grupo (e as categorias que ele ainda não tem)."""
    novo = {g: list(cs) for g, cs in dados.items()}
    nome = limpar(grupo)
    if not nome:
        raise GruposInvalidos("Digite o nome do grupo.")
    for g in novo:
        if _chave(g) == _chave(nome):
            nome = g   # reaproveita a grafia que já existe
            break
    lista = novo.setdefault(nome, [])
    for c in categorias:
        c = limpar(c)
        if c and not any(_chave(x) == _chave(c) for x in lista):
            lista.append(c)
    return novo


def renomear_grupo(dados, antigo, novo):
    """Devolve um dicionário novo com o grupo renomeado (categorias ficam)."""
    saida = {}
    alvo = _chave(antigo)
    nome_novo = limpar(novo)
    if not nome_novo:
        raise GruposInvalidos("Digite o novo nome do grupo.")
    for g, categorias in dados.items():
        if _chave(g) == alvo:
            saida[nome_novo] = list(categorias)
        else:
            saida[g] = list(categorias)
    return saida


def remover_grupo(dados, grupo):
    """Devolve um dicionário novo sem o grupo (as categorias dele ficam soltas)."""
    alvo = _chave(grupo)
    return {g: list(cs) for g, cs in dados.items() if _chave(g) != alvo}


def mover_categoria(dados, categoria, grupo):
    """Devolve um dicionário novo com a categoria no grupo (tirando de onde estava)."""
    saida = {g: [c for c in cs if _chave(c) != _chave(categoria)] for g, cs in dados.items()}
    if limpar(grupo):
        return adicionar_grupo(saida, grupo, [categoria])
    return saida
