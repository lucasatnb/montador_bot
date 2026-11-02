"""Funções puras para IDs, SKUs e itens de carrinho do modo especializado."""
import re
from collections.abc import Mapping, Sequence

RE_ID = re.compile(r"^[A-Z][0-9]{3}$")
RE_SKU = re.compile(r"^[A-Z][0-9]{3}(?:_[A-Z0-9]+)*$")

class FormatoInvalido(ValueError):
    pass


def validar_id(id_produto: str) -> str:
    valor = str(id_produto or "").strip().upper()
    if not RE_ID.fullmatch(valor):
        raise FormatoInvalido(f"ID inválido: {valor!r}. Use uma letra e três dígitos, por exemplo P001.")
    return valor


def proximo_id(ids_existentes) -> str:
    usados = set()
    for valor in ids_existentes:
        valor = str(valor or "").strip().upper()
        if RE_ID.fullmatch(valor):
            usados.add(valor)
    for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for numero in range(1000):
            candidato = f"{letra}{numero:03d}"
            if candidato not in usados:
                return candidato
    raise FormatoInvalido("Todos os IDs de A000 a Z999 já foram utilizados; não há IDs disponíveis.")


def validar_codigos(codigos_por_tipo: Mapping[str, Mapping[str, str]]) -> None:
    for tipo, mapa in codigos_por_tipo.items():
        vistos = {}
        for opcao, codigo in mapa.items():
            c = str(codigo)
            if not re.fullmatch(r"[A-Z0-9]+", c):
                raise FormatoInvalido(f"Código de {tipo}/{opcao} inválido: {c!r}; use apenas A-Z e 0-9, sem underline.")
            if c in vistos:
                raise FormatoInvalido(f"Código repetido no tipo '{tipo}': {vistos[c]!r} e {opcao!r} usam {c!r}.")
            vistos[c] = opcao


def montar_sku(id_produto: str, atributos: Mapping[str, str], variantes: Mapping[str, Sequence[str]],
               codigos: Mapping[str, Mapping[str, str]]) -> str:
    pid = validar_id(id_produto)
    validar_codigos(codigos)
    desconhecidos = set(atributos) - set(variantes)
    if desconhecidos:
        raise FormatoInvalido(f"Tipos de variação desconhecidos: {', '.join(sorted(desconhecidos))}.")
    partes = [pid]
    for tipo in variantes:
        if tipo not in atributos:
            continue
        opcao = atributos[tipo]
        if opcao not in variantes[tipo]:
            raise FormatoInvalido(f"Opção {opcao!r} não existe em VARIANTES['{tipo}'].")
        try:
            partes.append(codigos[tipo][opcao])
        except KeyError:
            raise FormatoInvalido(f"Falta código para {tipo}={opcao!r}.") from None
    if set(atributos) != {t for t in variantes if t in atributos}:
        raise FormatoInvalido("Atributos inválidos.")
    return "_".join(partes)


def montar_item_carrinho(sku: str, quantidade: int) -> str:
    sku = str(sku or "").strip().upper()
    if not RE_SKU.fullmatch(sku):
        raise FormatoInvalido(f"SKU inválida: {sku!r}.")
    if isinstance(quantidade, bool) or not isinstance(quantidade, int) or not 1 <= quantidade <= 999:
        raise FormatoInvalido("A quantidade do carrinho deve ser um inteiro entre 1 e 999.")
    return f"{sku.split('_', 1)[0]}_{quantidade}" + ("_" + sku.split("_", 1)[1] if "_" in sku else "")


def decodificar_item(texto: str, skus_do_produto) -> dict:
    """Decodifica ID_QTD_cod... casando o SKU completo com SKUs existentes, sem assumir posições."""
    partes = str(texto or "").strip().upper().split("_")
    if len(partes) < 2 or not RE_ID.fullmatch(partes[0]):
        raise FormatoInvalido(f"Item de carrinho inválido: {texto!r}.")
    try:
        qtd = int(partes[1])
    except ValueError:
        raise FormatoInvalido("A quantidade no carrinho não é um inteiro.") from None
    if not 1 <= qtd <= 999:
        raise FormatoInvalido("A quantidade no carrinho deve estar entre 1 e 999.")
    sku = "_".join([partes[0]] + partes[2:]) if len(partes) > 2 else partes[0]
    if not RE_SKU.fullmatch(sku):
        raise FormatoInvalido(f"SKU inválida no item de carrinho: {sku!r}.")
    if isinstance(skus_do_produto, Mapping):
        candidatos = list(skus_do_produto.keys())
    else:
        candidatos = []
        for item in skus_do_produto:
            candidatos.append(item.get("sku") if isinstance(item, Mapping) else str(item))
    candidatos = [str(x).upper() for x in candidatos if x]
    if sku not in candidatos:
        raise FormatoInvalido(f"SKU '{sku}' não existe entre as SKUs disponíveis do produto {partes[0]}.")
    return {"id": partes[0], "quantidade": qtd, "sku": sku}
