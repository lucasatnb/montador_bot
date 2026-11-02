"""Listas prontas de grupos/categorias/atributos (catalogo/categorias_presets.json).

Cada lista é um ponto de partida para montar a loja: grupos, categorias (subcategorias) e
quais atributos padrão cada categoria oferece. Aplicar NUNCA apaga nem renomeia o que já
existe: só soma o que falta.
"""
import json
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parents[1] / "categorias_presets.json"


class PresetInvalido(ValueError):
    """Problema na lista pronta, com mensagem em linguagem simples."""


def _limpar(texto):
    return " ".join(str(texto or "").split())


def carregar():
    try:
        bruto = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PresetInvalido(f"Não consegui ler {ARQUIVO.name}: {e}") from None
    if not isinstance(bruto, dict):
        raise PresetInvalido(f"{ARQUIVO.name} não é um objeto JSON.")
    return bruto


def listar():
    """[{'chave', 'nome', 'grupos': {grupo: [categorias]}, 'categorias': [{nome, grupo, atributos}]}]."""
    saida = []
    for chave, dados in carregar().items():
        if not isinstance(dados, dict):
            continue
        grupos = {}
        for g, categorias in (dados.get("grupos") or {}).items():
            g = _limpar(g)
            lista = [_limpar(c) for c in categorias] if isinstance(categorias, list) else []
            if g:
                grupos[g] = [c for c in lista if c]
        categorias = []
        for item in dados.get("categorias") or []:
            if not isinstance(item, dict):
                continue
            nome = _limpar(item.get("nome"))
            if not nome:
                continue
            categorias.append({
                "nome": nome,
                "grupo": _limpar(item.get("grupo")),
                "atributos": [str(a) for a in (item.get("atributos") or []) if str(a).strip()],
            })
        nome = _limpar(dados.get("nome")) or chave
        saida.append({"chave": chave, "nome": nome, "grupos": grupos, "categorias": categorias})
    return saida


def obter(chave):
    for p in listar():
        if p["chave"] == chave:
            return p
    return None


def plano(preset, categorias_existentes, grupos_existentes, tipos_existentes):
    """O que a aplicação da lista faria, SEM gravar nada.

    Devolve:
      categorias_novas      nomes que serão criados
      categorias_ignoradas  nomes que já existem (não mexe)
      grupos_novos          grupos que serão criados
      grupos_mesclados      grupos existentes que ganharão categorias
      categorias_em_grupo   erros: categorias da lista que já estão em outro grupo
      atributos_faltantes   chaves de atributo pedidas que a loja não tem
    """
    existentes = {_limpar(c).casefold() for c in categorias_existentes}
    grupos_chave = {g.casefold(): g for g in grupos_existentes}
    tipos = set(tipos_existentes)

    categorias_novas, categorias_ignoradas = [], []
    categorias_em_grupo, atributos_faltantes = [], set()
    for item in preset["categorias"]:
        nome = item["nome"]
        if nome.casefold() in existentes:
            categorias_ignoradas.append(nome)
        else:
            categorias_novas.append(nome)
        for chave in item["atributos"]:
            if chave not in tipos:
                atributos_faltantes.add(chave)

    grupos_novos, grupos_mesclados = [], {}
    for grupo, categorias in preset["grupos"].items():
        # categoria da lista que já está em outro grupo da loja (não será movida)
        for c in categorias:
            for g, cats in grupos_existentes.items():
                if any(_limpar(x).casefold() == c.casefold() for x in cats):
                    categorias_em_grupo.append((c, g))
        chave = grupo.casefold()
        if chave in grupos_chave:
            nome_real = grupos_chave[chave]
            entram = [c for c in categorias
                      if not any(_limpar(x).casefold() == c.casefold() for x in grupos_existentes.get(nome_real, []))]
            if entram:
                grupos_mesclados[nome_real] = entram
        else:
            grupos_novos.append(grupo)

    # uma categoria só pode ir para um grupo: se a loja já a tem em outro, ela NÃO é movida
    categorias_em_grupo = sorted(set(categorias_em_grupo))
    return {
        "categorias_novas": categorias_novas,
        "categorias_ignoradas": categorias_ignoradas,
        "grupos_novos": grupos_novos,
        "grupos_mesclados": grupos_mesclados,
        "categorias_em_grupo": categorias_em_grupo,
        "atributos_faltantes": sorted(atributos_faltantes),
    }
