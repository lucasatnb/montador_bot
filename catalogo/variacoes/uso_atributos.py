"""Quais categorias/opções de variação a loja JÁ USA (e que, por isso, não podem mais ser excluídas).

Uma opção está em uso quando algum item da loja depende dela:
  - o banco produtos_especializados.db tem uma SKU com ela (inclusive SKU inativa: o código dela continua valendo);
  - existem fotos em imagens/<ID>/<categoria>/<opção>/ (pasta vazia não conta);
  - o acrescimos.json de algum produto cita a opção.
Uma categoria está em uso quando alguma opção dela está.

    levantar(loja, dados)  ->  {categoria: {opção: [IDs dos produtos]}}   (só o que está em uso)

`dados` é o vocabulário da loja (atributos_loja.ler). Se alguma fonte não puder ser conferida (banco ilegível,
banco travado...), levanta UsoIndeterminado: quem chama deve tratar tudo como "em uso" e não deixar excluir nada.

Este módulo só LÊ: não grava nada, nem na planilha, nem no banco, nem nas pastas.
"""
import json
import sqlite3

from nucleo.gerar_pastas import MODO_ESP, ler_acrescimos, listar_imagens, nome_pasta


class UsoIndeterminado(Exception):
    """Não deu para conferir alguma fonte (planilha aberta ou ilegível, banco travado...), com mensagem simples."""


def levantar(loja, dados):
    tipos = dados["tipos"]
    # como cada opção aparece nas fontes: pelo nome (planilha, banco, acréscimos) ou pelo nome da pasta (fotos)
    por_nome = {t: {o.casefold(): o for o in v["opcoes"]} for t, v in tipos.items()}
    por_pasta = {t: {nome_pasta(o).casefold(): o for o in v["opcoes"]} for t, v in tipos.items()}
    tipo_da_pasta = {nome_pasta(t).casefold(): t for t in tipos}
    achados = {}

    def marcar(tipo, opcao, produto):
        if opcao is not None:
            achados.setdefault(tipo, {}).setdefault(opcao, set()).add(str(produto or "?").strip().upper())

    # 1) banco que o bot usa (só leitura; o bot pode estar gravando nele agora)
    banco = loja.banco_estoque(MODO_ESP)
    if banco.exists():
        try:
            con = sqlite3.connect(f"{banco.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
            try:
                skus = con.execute("SELECT produto_id, atributos FROM skus").fetchall()
            finally:
                con.close()
        except sqlite3.Error as e:
            if "no such table" not in str(e):
                raise UsoIndeterminado(f"Não consegui ler {banco.name} ({e}).") from None
            skus = []
        for produto, texto in skus:
            try:
                atributos = json.loads(texto or "{}")
            except ValueError:
                continue
            if isinstance(atributos, dict):
                for tipo, opcao in atributos.items():
                    if tipo in tipos:
                        marcar(tipo, por_nome[tipo].get(str(opcao).strip().casefold()), produto)

    # 2) fotos por variação: imagens/<ID>/<categoria>/<opção>/
    try:
        if loja.imagens.is_dir():
            for pasta_id in (d for d in loja.imagens.iterdir() if d.is_dir()):
                for pasta_tipo in (d for d in pasta_id.iterdir() if d.is_dir()):
                    tipo = tipo_da_pasta.get(pasta_tipo.name.casefold())
                    if tipo is None:
                        continue
                    for pasta_opcao in (d for d in pasta_tipo.iterdir() if d.is_dir()):
                        if listar_imagens(pasta_opcao):
                            marcar(tipo, por_pasta[tipo].get(pasta_opcao.name.casefold()), pasta_id.name)
    except OSError as e:
        raise UsoIndeterminado(f"Não consegui ler a pasta de fotos ({e}).") from None

    # 3) acréscimos de preço por opção (acrescimos.json)
    for produto, por_tipo in ler_acrescimos(loja).items():
        if not isinstance(por_tipo, dict):
            continue
        for tipo, regra in por_tipo.items():
            if tipo in tipos and isinstance(regra, dict) and isinstance(regra.get("opcoes"), dict):
                for opcao in regra["opcoes"]:
                    marcar(tipo, por_nome[tipo].get(str(opcao).strip().casefold()), produto)

    return {t: {o: sorted(ids) for o, ids in ops.items()} for t, ops in achados.items()}
