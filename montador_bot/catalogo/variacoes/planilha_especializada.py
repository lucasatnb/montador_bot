"""Regras das variações do modo especializado: combinações, validação das linhas, estado da grade da tela."""
from itertools import product
import hashlib, json, re
from variacoes import constantes_especializado as ce
from nucleo.formato_ids import validar_id, montar_sku, RE_SKU
import unicodedata


class PlanilhaInvalida(Exception):
    """Dados inválidos, com mensagem em linguagem simples."""


def _normalizar(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", texto.lower()).split())


def _numero(valor, linha, coluna) -> float:
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace("R$", "").replace(".", "").replace(",", "."))
    except ValueError:
        raise PlanilhaInvalida(f"linha {linha}: {coluna} '{valor}' não é um número")


COLUNAS_FIXAS = ["sku", "id", "nome", "preco", "quantidade", "imagem"]


def gerar_combinacoes(tipos_e_opcoes):
    """Produto cartesiano seguindo a ordem oficial de VARIANTES, não a ordem de entrada."""
    tipos = [t for t in ce.VARIANTES if t in tipos_e_opcoes]
    for t in tipos_e_opcoes:
        if t not in ce.VARIANTES:
            raise PlanilhaInvalida(f"tipo de variação desconhecido: {t}")
    opcoes = []
    for tipo in tipos:
        selecionadas = list(tipos_e_opcoes[tipo])
        invalidas = [o for o in selecionadas if o not in ce.VARIANTES[tipo]]
        if invalidas:
            raise PlanilhaInvalida(f"opção inválida para {tipo}: {', '.join(map(str, invalidas))}")
        if not selecionadas or len(set(selecionadas)) != len(selecionadas):
            raise PlanilhaInvalida(f"selecione opções únicas para {tipo}")
        opcoes.append(selecionadas)
    if not tipos:
        return [{}]
    return [dict(zip(tipos, valores)) for valores in product(*opcoes)]


def validar(linhas):
    erros, skus, combinacoes, ids_nomes, tipos_produto = [], set(), set(), {}, {}
    colunas_base = set(COLUNAS_FIXAS)
    for i, linha in enumerate(linhas, 2):
        num = linha.get("_linha", i)
        pid = str(linha.get("id") or "").strip().upper()
        sku = str(linha.get("sku") or "").strip().upper()
        nome = str(linha.get("nome") or "").strip()
        try:
            validar_id(pid)
        except ValueError as e: erros.append(f"linha {num}: {e}")
        if not nome: erros.append(f"linha {num}: nome vazio")
        if not sku or not RE_SKU.fullmatch(sku): erros.append(f"linha {num}: SKU inválida '{sku}'")
        if sku in skus: erros.append(f"linha {num}: SKU repetida '{sku}'")
        skus.add(sku)
        try:
            preco = _numero(linha.get("preco"), num, "preço")
            if preco < 0: erros.append(f"linha {num}: preço não pode ser negativo")
        except PlanilhaInvalida as e: erros.append(str(e))
        q = linha.get("quantidade")
        if _normalizar(q) not in {"true", "verdadeiro", "infinito"}:
            try:
                qtd = _numero(q, num, "quantidade")
                if qtd < 0 or qtd != int(qtd): erros.append(f"linha {num}: quantidade deve ser inteiro >= 0 ou TRUE")
            except PlanilhaInvalida as e: erros.append(str(e))
        if nome and pid:
            if pid in ids_nomes and ids_nomes[pid] != nome:
                erros.append(f"linha {num}: ID {pid} aparece com nomes diferentes ('{ids_nomes[pid]}' e '{nome}')")
            ids_nomes[pid] = nome
        atributos = {}
        for tipo in ce.VARIANTES:
            valor = linha.get(tipo)
            if valor is not None and str(valor).strip():
                opcao = str(valor).strip()
                if opcao not in ce.VARIANTES[tipo]: erros.append(f"linha {num}: opção '{opcao}' não existe em VARIANTES['{tipo}']")
                else: atributos[tipo] = opcao
        for coluna, valor in linha.items():
            if coluna.startswith("_") or coluna in colunas_base or valor is None or str(valor).strip() == "": continue
            if coluna not in ce.VARIANTES:
                erros.append(f"linha {num}: coluna desconhecida '{coluna}'")
        if pid:
            tipos_produto.setdefault(pid, set()).add(tuple(sorted(atributos)))
            chave = (pid, tuple(sorted(atributos.items())))
            if chave in combinacoes: erros.append(f"linha {num}: combinação repetida para produto {pid}: {atributos}")
            combinacoes.add(chave)
    for pid, tipos in tipos_produto.items():
        if len(tipos) > 1:
            erros.append(f"produto {pid}: as linhas usam conjuntos diferentes de tipos de variação")
    if erros:
        raise PlanilhaInvalida("Planilha especializada inválida:\n- " + "\n- ".join(erros))
    return True


def chave_atributos(atributos):
    """Chave estável de uma combinação (a ordem das chaves não importa)."""
    return tuple(sorted(atributos.items()))


def preco_numerico(valor, padrao=0.0):
    """'49,90' -> 49.9. Valor ausente ou em texto inválido devolve `padrao` (não quebra a interface)."""
    try:
        return float(_numero(valor, "?", "preço"))
    except (PlanilhaInvalida, TypeError):
        return padrao


def estado_inicial_vazio(preco_catalogo):
    return {"tem_variacoes": False, "tipos": {}, "valores": {},
            "simples": {"preco": preco_catalogo, "quantidade": 0, "ilimitado": False}}


def estado_a_partir_do_salvo(salvo, preco_catalogo):
    """`salvo` é {"tipos", "valores"} (da planilha ou do banco) ou None. O que já está gravado vale; só o que
    ainda não existe cai no preço do catálogo e quantidade 0. Reaprovar nunca apaga o que já estava salvo."""
    estado = estado_inicial_vazio(preco_catalogo)
    if salvo is None:
        return estado
    estado["tipos"] = salvo["tipos"]
    estado["valores"] = salvo["valores"]
    estado["tem_variacoes"] = bool(salvo["tipos"])
    sem_variacao = salvo["valores"].get(())
    if sem_variacao:
        estado["simples"] = {
            "preco": preco_catalogo if sem_variacao["preco"] is None else sem_variacao["preco"],
            "quantidade": sem_variacao["quantidade"] or 0, "ilimitado": sem_variacao["ilimitado"]}
    return estado


def mesclar_valores(base, edicoes):
    """base (do que está salvo) + edicoes (o que a pessoa digitou), combinação por combinação."""
    saida = {k: dict(v) for k, v in base.items()}
    for k, v in edicoes.items():
        saida.setdefault(k, {}).update(v)
    return saida


def montar_dados_grade(id_produto, combinacoes, valores, preco_padrao):
    """Linhas da grade de estoque: valor já salvo/digitado de cada combinação, ou (preço do catálogo, 0)."""
    dados = []
    for atributos in combinacoes:
        salvo = valores.get(chave_atributos(atributos), {})
        sku = salvo.get("sku") or montar_sku(id_produto, atributos, ce.VARIANTES, ce.CODIGOS)
        preco, qtd = salvo.get("preco"), salvo.get("quantidade")
        dados.append({"SKU": sku,
                      "Variação": " / ".join(f"{ce.ROTULOS.get(t, t)}: {o}" for t, o in atributos.items()),
                      "preco": preco_padrao if preco is None else preco,
                      "quantidade": 0 if qtd is None else qtd,
                      "ilimitado": bool(salvo.get("ilimitado", False))})
    return dados


def chave_grade(id_produto, versao, tipos_escolhidos):
    """Chave do data_editor. Inclui as opções marcadas NA ORDEM escolhida (a ordem muda a ordem das
    linhas): se as opções mudam, o editor recomeça em vez de aplicar edições na linha errada."""
    ordenado = [[t, list(tipos_escolhidos[t])] for t in ce.VARIANTES if t in tipos_escolhidos]
    h = hashlib.md5(json.dumps(ordenado, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]
    return f"grade_estoque_{id_produto}_{versao}_{h}"
