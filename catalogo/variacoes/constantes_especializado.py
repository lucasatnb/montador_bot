"""Vocabulário do estoque ESPECIALIZADO: tipos, opções, códigos e sinônimos.

Os dados NÃO ficam mais escritos aqui: vêm de um JSON, um por loja (lojas/<loja>/atributos.json, gerenciado pela
interface do catálogo; veja atributos_loja.py). Este módulo só os expõe no mesmo formato de sempre
(VARIANTES, ROTULOS, SINONIMOS, CODIGOS), então quem faz `import constantes_especializado as ce` não muda nada.

    carregar(caminho)    troca o vocabulário para o de um atributos.json (os dicionários são alterados NO LUGAR,
                         então referências já guardadas enxergam o vocabulário novo). Arquivo ausente = vazio.

Sem chamar carregar(), vale o atributos_padrao.json que fica ao lado deste arquivo.
Atenção: o vocabulário é um estado do processo; um processo atende uma loja por vez.
"""
import json
from pathlib import Path

VARIANTES = {}    # tipo -> [opções]            (a ordem importa: é a ordem das partes do SKU)
ROTULOS = {}      # tipo -> texto exibido
SINONIMOS = {}    # texto normalizado -> opção oficial
CODIGOS = {}      # tipo -> {opção: código usado no SKU}

PADRAO = Path(__file__).resolve().parents[1] / "atributos_padrao.json"   # na raiz do projeto


def carregar(caminho):
    """Carrega o vocabulário de `caminho`. Se o arquivo não existe, o vocabulário fica vazio."""
    dados = {}
    caminho = Path(caminho)
    if caminho.exists():
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    VARIANTES.clear(), ROTULOS.clear(), SINONIMOS.clear(), CODIGOS.clear()
    for tipo, t in (dados.get("tipos") or {}).items():
        opcoes = t.get("opcoes") or {}
        VARIANTES[tipo] = list(opcoes)
        ROTULOS[tipo] = t.get("rotulo") or tipo.capitalize()
        CODIGOS[tipo] = dict(opcoes)
    SINONIMOS.update(dados.get("sinonimos") or {})


if PADRAO.exists():
    carregar(PADRAO)
