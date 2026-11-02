"""Vocabulário de variações de UMA loja: categorias (tipos), opções, códigos e sinônimos.

Arquivo:  lojas/<loja>/atributos.json
    {"tipos": {"cor": {"rotulo": "Cor", "opcoes": {"Preto": "PT", "Verde": "VD"}}},
     "sinonimos": {"preta": "Preto"}}

ABERTO para extensão, FECHADO para modificação: dá para ADICIONAR categorias, opções e sinônimos, e nada do que já foi
atribuído à loja pode ser renomeado, mudar de código ou trocar de ordem. Só dá para EXCLUIR o que nenhum produto usa
ainda (SKUs, planilhas e pastas de fotos dependem do que já está em uso). Quem sabe o que está em uso é o
uso_atributos.levantar(), que devolve {categoria: {opção: [IDs dos produtos]}}; esse levantamento é passado a salvar().

A regra está em salvar(): toda gravação que tire ou altere algo em uso é recusada. Sem o levantamento (uso=None) nada
que já está gravado pode ser removido: na dúvida, vale como "em uso".

As funções com_*() não mexem no que recebem: devolvem um vocabulário novo, que então vai para salvar().
Sinônimos também podem vir de um .txt (palavras separadas por vírgula): com_sinonimos_do_texto().
"""
import copy
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

RESERVADAS = {"sku", "id", "nome", "preco", "quantidade", "imagem"}   # colunas fixas da planilha especializada
PROIBIDOS = set('\\/:*?"<>|;')          # nomes viram pasta de foto e a lista de fotos usa ';'
PADRAO = Path(__file__).resolve().parents[1] / "atributos_padrao.json"   # na raiz do projeto


class VocabularioInvalido(ValueError):
    """Violação de regra do vocabulário, com mensagem em linguagem simples."""


# ---------------------------------------------------------------- textos
def _sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c))


def normalizar(texto):
    """minúsculas, sem acento, sem pontuação, espaços únicos (igual ao normalizar do bot)."""
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", _sem_acento(texto).lower()).split())


def chave_do_tipo(rotulo):
    """'Numeração' -> 'numeracao' (minúsculo, sem acento nem espaço: é o nome da coluna na planilha)."""
    return re.sub(r"[^a-z0-9]", "", _sem_acento(rotulo).lower())


def sugerir_codigo(nome, usados):
    """Código curto (A-Z, 0-9) para uma opção, sem repetir os já usados no tipo."""
    base = re.sub(r"[^A-Z0-9]", "", _sem_acento(nome).upper())
    if not base:
        raise VocabularioInvalido(f"Não consegui gerar um código para '{nome}'. Informe um (letras e números).")
    for n in range(min(2, len(base)), len(base) + 1):
        if base[:n] not in usados:
            return base[:n]
    i = 2
    while f"{base}{i}" in usados:
        i += 1
    return f"{base}{i}"


# ---------------------------------------------------------------- arquivo
def vazio():
    return {"tipos": {}, "sinonimos": {}}


def ler(caminho):
    """Vocabulário gravado (vazio se o arquivo ainda não existe)."""
    caminho = Path(caminho)
    if not caminho.exists():
        return vazio()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise VocabularioInvalido(f"Não consegui ler {caminho.name}: {e}") from None
    if not isinstance(dados, dict):
        raise VocabularioInvalido(f"{caminho.name} não tem o formato esperado.")
    dados.setdefault("tipos", {})
    dados.setdefault("sinonimos", {})
    return dados


def salvar(caminho, dados, uso=None):
    """Valida e grava. Recusa se `dados` tirar ou alterar algo que já está em uso. `uso` vem de
    uso_atributos.levantar(); com uso=None (não sei o que está em uso) nada já gravado pode ser removido."""
    caminho = Path(caminho)
    _validar(dados)
    _so_cresce(ler(caminho), dados, uso)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="atributos_", suffix=".tmp", dir=str(caminho.parent))
    os.close(fd)
    try:
        Path(tmp).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _opcao_usada(dados, uso, nome):
    """True se a opção `nome` está em uso em alguma categoria (ou, com uso=None, se ela existe: na dúvida, em uso)."""
    donos = [c for c, t in dados["tipos"].items() if nome in t["opcoes"]]
    return bool(donos) and (uso is None or any(nome in (uso.get(c) or {}) for c in donos))


def _so_cresce(antigo, novo, uso):
    """A regra do 'fechado para modificação': acrescentar pode; excluir só o que nenhum produto usa; mudar, nunca."""
    def usado(tipo, opcao=None):
        if uso is None:          # não sei o que está em uso: nada pode sair
            return True
        em_uso = uso.get(tipo) or {}
        return bool(em_uso) if opcao is None else opcao in em_uso

    mantidas = [c for c in antigo["tipos"] if c in novo["tipos"]]
    if list(novo["tipos"])[:len(mantidas)] != mantidas:
        raise VocabularioInvalido("As categorias já atribuídas à loja não podem ser trocadas de ordem.")
    for chave, t in antigo["tipos"].items():
        if chave not in novo["tipos"]:
            if usado(chave):
                raise VocabularioInvalido(
                    f"A categoria '{t['rotulo']}' já é usada por algum produto e não pode ser removida.")
            continue
        n = novo["tipos"][chave]
        if n["rotulo"] != t["rotulo"]:
            raise VocabularioInvalido(f"A categoria '{t['rotulo']}' não pode ser renomeada.")
        for nome, codigo in t["opcoes"].items():
            if nome not in n["opcoes"]:
                if usado(chave, nome):
                    raise VocabularioInvalido(
                        f"A opção '{nome}' de '{t['rotulo']}' já é usada por algum produto e não pode ser "
                        "removida nem renomeada.")
            elif n["opcoes"][nome] != codigo:
                raise VocabularioInvalido(f"A opção '{nome}' de '{t['rotulo']}' não pode mudar de código.")
        restantes = [o for o in t["opcoes"] if o in n["opcoes"]]
        if list(n["opcoes"])[:len(restantes)] != restantes:
            raise VocabularioInvalido(f"As opções já cadastradas em '{t['rotulo']}' não podem ser trocadas de ordem.")
    for texto, oficial in antigo["sinonimos"].items():
        atual = novo["sinonimos"].get(texto)
        if atual == oficial:
            continue
        if atual is not None:
            raise VocabularioInvalido(f"O sinônimo '{texto}' já foi atribuído e não pode ser alterado.")
        if _opcao_usada(antigo, uso, oficial):
            raise VocabularioInvalido(
                f"O sinônimo '{texto}' aponta para '{oficial}', que já é usada por algum produto, "
                "e não pode ser removido.")


def _validar(dados):
    todas = set()
    for chave, t in dados["tipos"].items():
        if not re.fullmatch(r"[a-z0-9]+", chave) or chave in RESERVADAS:
            raise VocabularioInvalido(f"Nome de categoria inválido ou reservado: '{chave}'.")
        if not str(t.get("rotulo", "")).strip():
            raise VocabularioInvalido(f"A categoria '{chave}' precisa de um nome.")
        vistos, codigos = set(), {}
        for nome, codigo in t["opcoes"].items():
            if not nome or nome != nome.strip() or PROIBIDOS & set(nome):
                raise VocabularioInvalido(
                    f"Opção inválida em '{t['rotulo']}': {nome!r} (sem espaços nas pontas e sem \\ / : * ? \" < > | ;).")
            if nome.casefold() in vistos:
                raise VocabularioInvalido(f"A opção '{nome}' está repetida em '{t['rotulo']}'.")
            vistos.add(nome.casefold())
            if not re.fullmatch(r"[A-Z0-9]+", str(codigo)):
                raise VocabularioInvalido(f"Código inválido para {t['rotulo']}/{nome}: {codigo!r} (use só A-Z e 0-9).")
            if codigo in codigos:
                raise VocabularioInvalido(f"O código {codigo} já é usado por '{codigos[codigo]}' em '{t['rotulo']}'.")
            codigos[codigo] = nome
            todas.add(nome)
    for texto, oficial in dados["sinonimos"].items():
        if not texto or texto != normalizar(texto):
            raise VocabularioInvalido(f"Sinônimo inválido: {texto!r} (minúsculas, sem acento nem pontuação).")
        if oficial not in todas:
            raise VocabularioInvalido(f"O sinônimo '{texto}' aponta para '{oficial}', que não existe nas opções da loja.")


# ---------------------------------------------------------------- só se pode ACRESCENTAR
def com_tipo(dados, rotulo):
    rotulo = " ".join(str(rotulo or "").split())
    chave = chave_do_tipo(rotulo)
    if not chave:
        raise VocabularioInvalido("Digite o nome da categoria (letras ou números).")
    if chave in dados["tipos"]:
        raise VocabularioInvalido(f"A categoria '{dados['tipos'][chave]['rotulo']}' já existe nesta loja.")
    novo = copy.deepcopy(dados)
    novo["tipos"][chave] = {"rotulo": rotulo, "opcoes": {}}
    _validar(novo)
    return novo


def com_opcao(dados, chave_tipo, nome, codigo=None):
    if chave_tipo not in dados["tipos"]:
        raise VocabularioInvalido("Escolha uma categoria existente.")
    nome = str(nome or "").strip()
    if not nome:
        raise VocabularioInvalido("Digite o nome da opção.")
    t = dados["tipos"][chave_tipo]
    if nome.casefold() in {o.casefold() for o in t["opcoes"]}:
        raise VocabularioInvalido(f"A opção '{nome}' já existe em '{t['rotulo']}'.")
    codigo = str(codigo or "").strip().upper() or sugerir_codigo(nome, set(t["opcoes"].values()))
    novo = copy.deepcopy(dados)
    novo["tipos"][chave_tipo]["opcoes"][nome] = codigo
    _validar(novo)
    return novo


def com_sinonimo(dados, texto, opcao):
    chave = normalizar(texto)
    if not chave:
        raise VocabularioInvalido("Digite o sinônimo.")
    if chave in dados["sinonimos"]:
        raise VocabularioInvalido(f"O sinônimo '{chave}' já existe.")
    novo = copy.deepcopy(dados)
    novo["sinonimos"][chave] = opcao
    _validar(novo)
    return novo


def com_padrao(dados, caminho_padrao=PADRAO):
    """Soma ao vocabulário os atributos padrão que ainda não existem (nunca remove nem altera o que já há)."""
    padrao = ler(caminho_padrao)
    novo = copy.deepcopy(dados)
    for chave, t in padrao["tipos"].items():
        alvo = novo["tipos"].setdefault(chave, {"rotulo": t["rotulo"], "opcoes": {}})
        usados = set(alvo["opcoes"].values())
        for nome, codigo in t["opcoes"].items():
            if nome not in alvo["opcoes"] and codigo not in usados:
                alvo["opcoes"][nome] = codigo
                usados.add(codigo)
    todas = {o for t in novo["tipos"].values() for o in t["opcoes"]}
    for texto, oficial in padrao["sinonimos"].items():
        if texto not in novo["sinonimos"] and oficial in todas:
            novo["sinonimos"][texto] = oficial
    _validar(novo)
    return novo


# ---------------------------------------------------------------- sinônimos de um .txt
def decodificar_texto(conteudo):
    """Bytes de um .txt -> texto. UTF-8 (com ou sem BOM); se não for, Windows-1252 (o Bloco de Notas antigo)."""
    if isinstance(conteudo, str):
        return conteudo
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            pass
    return conteudo.decode("latin-1")


def com_sinonimos_do_texto(dados, texto, opcao_padrao=None):
    """Lê o texto de um .txt de sinônimos. NÃO grava: devolve (vocabulário novo, relatório) para a tela mostrar
    o que vai entrar antes de a pessoa confirmar.

    Formato (vírgula separa as palavras; ';' e quebra de linha também):
        preta, negra, escura        -> todas viram sinônimo de `opcao_padrao`
        Preto: preta, negra         -> o que vem antes de ':' é a opção (uma linha por opção)
        Branco: branca, clara
    Maiúsculas, acento e pontuação não importam (preta = Preta = PRÉTA).

    Relatório: {"novos": [(sinônimo, opção)], "repetidos": [sinônimo], "problemas": [mensagem]}.
    Sinônimo que já existe e aponta para a mesma opção é só "repetido"; o que já aponta para OUTRA opção não é
    trocado (vira problema); linha com opção desconhecida é ignorada (vira problema). Reimportar o mesmo arquivo é seguro.
    """
    todas = {}                      # texto normalizado da opção -> nome oficial
    for t in dados["tipos"].values():
        for nome in t["opcoes"]:
            chave = normalizar(nome)
            if chave:
                todas.setdefault(chave, nome)
    padrao = todas.get(normalizar(opcao_padrao)) if opcao_padrao else None
    existentes = dict(dados["sinonimos"])
    novos, repetidos, problemas = [], [], []

    for n, linha in enumerate(str(texto).splitlines(), 1):
        linha = linha.strip()
        if not linha:
            continue
        if ":" in linha:
            esquerda, _, resto = linha.partition(":")
            opcao = todas.get(normalizar(esquerda))
            if opcao is None:
                problemas.append(f"Linha {n}: a opção '{esquerda.strip()}' não existe nesta loja; linha ignorada.")
                continue
        else:
            opcao, resto = padrao, linha
            if opcao is None:
                problemas.append(f"Linha {n}: não diz a opção (escreva «Opção: palavras») e nenhuma opção foi "
                                 "escolhida na tela; linha ignorada.")
                continue
        for palavra in re.split(r"[,;]", resto):
            chave = normalizar(palavra)
            if not chave:
                continue
            atual = existentes.get(chave)
            if chave == normalizar(opcao) or atual == opcao:
                repetidos.append(chave)
            elif atual is not None:
                problemas.append(f"Linha {n}: '{chave}' já significa '{atual}'; não foi trocado para '{opcao}'.")
            else:
                existentes[chave] = opcao
                novos.append((chave, opcao))

    novo = copy.deepcopy(dados)
    novo["sinonimos"].update(novos)
    _validar(novo)
    return novo, {"novos": novos, "repetidos": list(dict.fromkeys(repetidos)), "problemas": problemas}


# ---------------------------------------------------------------- EXCLUIR o que ninguém usa
# `uso` = {categoria: {opção: [IDs dos produtos]}}, de uso_atributos.levantar(). Com uso=None (não sei o que está em
# uso) nada é removível. salvar() confere de novo: estas funções só dão mensagens melhores, a regra é uma só.
def _exigir_uso(uso):
    if uso is None:
        raise VocabularioInvalido("Não consegui conferir o que a loja já usa, então nada pode ser excluído agora.")


def _ids(produtos):
    produtos = sorted(produtos)
    return ", ".join(produtos[:5]) + (f" e mais {len(produtos) - 5}" if len(produtos) > 5 else "")


def _sem_sinonimos_orfaos(dados):
    """Tira os sinônimos que apontam para uma opção que deixou de existir (em qualquer categoria)."""
    todas = {o for t in dados["tipos"].values() for o in t["opcoes"]}
    dados["sinonimos"] = {s: o for s, o in dados["sinonimos"].items() if o in todas}
    return dados


def opcoes_removiveis(dados, uso):
    """[(categoria, opção)] que nenhum produto usa."""
    if uso is None:
        return []
    return [(c, n) for c, t in dados["tipos"].items() for n in t["opcoes"] if n not in (uso.get(c) or {})]


def tipos_removiveis(dados, uso):
    """[categoria] em que nenhuma opção é usada por produto algum."""
    if uso is None:
        return []
    return [c for c in dados["tipos"] if not uso.get(c)]


def sinonimos_removiveis(dados, uso):
    """[sinônimo] cuja opção nenhum produto usa."""
    if uso is None:
        return []
    return [s for s, o in dados["sinonimos"].items() if not _opcao_usada(dados, uso, o)]


def com_sinonimos_removidos(dados, textos, uso):
    _exigir_uso(uso)
    novo = copy.deepcopy(dados)
    for texto in textos:
        if texto not in novo["sinonimos"]:
            raise VocabularioInvalido(f"O sinônimo '{texto}' não existe.")
        oficial = novo["sinonimos"][texto]
        if _opcao_usada(dados, uso, oficial):
            raise VocabularioInvalido(
                f"O sinônimo '{texto}' aponta para '{oficial}', que já é usada por algum produto, "
                "e não pode ser excluído.")
        del novo["sinonimos"][texto]
    _validar(novo)
    return novo


def com_opcao_removida(dados, chave_tipo, nome, uso):
    """Tira a opção (e os sinônimos que só existiam por causa dela). Recusa se algum produto a usa."""
    _exigir_uso(uso)
    if chave_tipo not in dados["tipos"]:
        raise VocabularioInvalido("Escolha uma categoria existente.")
    t = dados["tipos"][chave_tipo]
    if nome not in t["opcoes"]:
        raise VocabularioInvalido(f"A opção '{nome}' não existe em '{t['rotulo']}'.")
    produtos = (uso.get(chave_tipo) or {}).get(nome)
    if produtos:
        raise VocabularioInvalido(
            f"A opção '{nome}' de '{t['rotulo']}' já é usada ({_ids(produtos)}) e não pode ser excluída.")
    novo = copy.deepcopy(dados)
    del novo["tipos"][chave_tipo]["opcoes"][nome]
    _sem_sinonimos_orfaos(novo)
    _validar(novo)
    return novo


def com_tipo_removido(dados, chave_tipo, uso):
    """Tira a categoria inteira, com as opções e os sinônimos dela. Recusa se algum produto usa alguma opção."""
    _exigir_uso(uso)
    if chave_tipo not in dados["tipos"]:
        raise VocabularioInvalido("Escolha uma categoria existente.")
    t = dados["tipos"][chave_tipo]
    em_uso = uso.get(chave_tipo) or {}
    if em_uso:
        detalhe = "; ".join(f"{o}: {_ids(p)}" for o, p in em_uso.items())
        raise VocabularioInvalido(f"A categoria '{t['rotulo']}' já é usada ({detalhe}) e não pode ser excluída.")
    novo = copy.deepcopy(dados)
    del novo["tipos"][chave_tipo]
    _sem_sinonimos_orfaos(novo)
    _validar(novo)
    return novo
