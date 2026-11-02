"""Painel do vendedor (DONOS): confirmar pagamento (ou a visita, na loja por orçamento), cancelar comanda,
ligar o bot de novo para um cliente (loja por orçamento) e listar pendentes.

Não conhece conversas de clientes. Trabalha só com o registro de comandas (registro_comandas),
o estoque (recebido por parâmetro, para não haver import circular com atendimento.py) e o
aviso ao cliente (notificacoes.py).
"""
import logging
import re

from . import configuracao as cfg
import registro_comandas
import registro_mensagens
from .notificacoes import avisar_cliente
from estoque.utilidades import normalizar, reais

# compiladas uma vez, na importação
_RE_CONFIRMAR = re.compile(r"(?:confirmar|confirma|pago|paga)\s+(\d+)")
_RE_CANCELAR = re.compile(r"(?:cancelar|cancela)\s+(\d+)")
_RE_LIGAR = re.compile(r"(?:ligar|liga|liberar|libera)\s+(\d+)")


def confirmar_comanda(numero: int) -> str:
    """O vendedor confirmou o pagamento (ou, na comanda de orçamento, a VISITA). Devolve o texto de resposta para o vendedor."""
    with cfg.TRAVA_REGISTRO:
        c = registro_comandas.buscar_comanda(numero)
        if c is None:
            return f"Não achei a comanda nº {numero}."
        if c["status"] == "confirmada":
            return f"A comanda nº {numero} já estava confirmada."
        if c["status"] == "cancelada":
            return (f"A comanda nº {numero} foi cancelada e os itens voltaram ao estoque, então não dá para "
                    "confirmar. O cliente precisa fazer um novo pedido.")
        if not registro_comandas.mudar_status(numero, "aguardando", "confirmada"):
            return f"A comanda nº {numero} acabou de mudar. Mande 'pendentes' para ver como ela está."
    if c["tipo"] == "orcamento":   # a confirmação é sobre a visita, não sobre pagamento
        avisado = avisar_cliente(c["chave"], cfg.TEXTO_VISITA_CONFIRMADA.format(nome=c["nome"], numero=numero))
        return (f"Visita da comanda nº {numero} confirmada ({c['nome']}, {c['endereco']})."
                + ("" if avisado else " Não avisei o cliente: nenhum canal de envio registrado.")
                + (f" O bot continua calado com ele; para ligar: ligar {numero}."
                   if registro_mensagens.esta_pausado(c["chave"]) else ""))
    avisado = avisar_cliente(c["chave"], cfg.TEXTO_CONFIRMADA.format(nome=c["nome"], numero=numero))
    return (f"Comanda nº {numero} confirmada ({c['nome']}, {reais(c['total'])})."
            + ("" if avisado else " Não avisei o cliente: nenhum canal de envio registrado."))


def cancelar_comanda(numero: int, estoque) -> str:
    """O vendedor cancelou: os itens VOLTAM ao estoque. Devolve o texto de resposta para o vendedor.
    `estoque` = a instância de Estoque, usada para devolver os itens."""
    with cfg.TRAVA_REGISTRO:
        c = registro_comandas.buscar_comanda(numero)
        if c is None:
            return f"Não achei a comanda nº {numero}."
        if c["status"] == "cancelada":
            return f"A comanda nº {numero} já estava cancelada."
        if c["status"] == "confirmada":
            return (f"A comanda nº {numero} já foi confirmada (paga), então não cancelei. "
                    "Se for uma devolução, ajuste o estoque à mão.")
        # troca o status ANTES de devolver o estoque: se duas pessoas cancelarem ao mesmo tempo,
        # só uma passa, e o estoque nunca é devolvido duas vezes
        if not registro_comandas.mudar_status(numero, "aguardando", "cancelada"):
            return f"A comanda nº {numero} acabou de mudar. Mande 'pendentes' para ver como ela está."
        falhas = []
        for produto_id, produto_nome, qtd in c["itens"]:
            try:
                devolveu = estoque.estornar(produto_id, qtd)
            except KeyError:
                devolveu = False
            if not devolveu:
                falhas.append(f"{qtd}x {produto_nome}")
                logging.error("comanda %s cancelada, mas não consegui devolver %sx %s (%s) ao estoque",
                              numero, qtd, produto_nome, produto_id)
    avisado = avisar_cliente(c["chave"], cfg.TEXTO_CANCELADA.format(numero=numero))
    if falhas:
        return (f"Comanda nº {numero} cancelada, MAS não consegui devolver ao estoque: {', '.join(falhas)}. "
                "Ajuste à mão.")
    return (f"Comanda nº {numero} cancelada ({c['nome']}); itens devolvidos ao estoque."
            + ("" if avisado else " Não avisei o cliente: nenhum canal de envio registrado."))


def ligar_bot(numero: int) -> str:
    """Liga o bot de novo para o cliente da comanda `numero` (tira a pausa que o fechamento do orçamento colocou)."""
    c = registro_comandas.buscar_comanda(numero)
    if c is None:
        return f"Não achei a comanda nº {numero}."
    if registro_mensagens.liberar(c["chave"]):
        return f"Bot ligado de novo para {c['nome']} (comanda nº {numero})."
    return f"O bot já estava ligado para {c['nome']} (comanda nº {numero})."


def _listar_pendentes() -> str:
    linhas = registro_comandas.comandas_com_status("aguardando")
    if not linhas:
        return "Nenhuma comanda aguardando confirmação."
    return "Aguardando confirmação:\n" + "\n".join(
        f"nº {c['id']} · {c['nome']} · "
        + (f"visita: {c['endereco']}" if c["tipo"] == "orcamento" else reais(c["total"]))
        + f" · {c['quando'][8:10]}/{c['quando'][5:7]} {c['quando'][11:16]}"
        for c in linhas)


def comando_dono(texto: str, estoque):
    """Interpreta 'confirmar 7', 'cancelar 7', 'ligar 7', 'pendentes', 'ajuda' (com ou sem '/').
    Devolve o texto de resposta, ou None se a mensagem não é um comando. Só chame para DONOS."""
    n = normalizar(texto)
    try:
        m = _RE_CONFIRMAR.fullmatch(n)
        if m:
            return confirmar_comanda(int(m.group(1)))
        m = _RE_CANCELAR.fullmatch(n)
        if m:
            return cancelar_comanda(int(m.group(1)), estoque)
        m = _RE_LIGAR.fullmatch(n)
        if m:
            return ligar_bot(int(m.group(1)))
        if n in ("pendentes", "pendente", "comandas"):
            with cfg.TRAVA_REGISTRO:
                return _listar_pendentes()
        if n in ("ajuda", "help", "comandos"):
            return cfg.TEXTO_AJUDA_DONO
    except Exception:
        logging.exception("erro ao executar o comando do vendedor: %r", texto)
        return "Deu erro ao acessar o banco de comandas. Tente de novo em instantes."
    return None
