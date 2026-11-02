"""Avisos por canal externo (Telegram, WhatsApp, e-mail...): todo o I/O de rede e threads fica aqui.

O núcleo não sabe COMO avisar. Quem liga o bot escolhe o canal:
    notificacoes.registrar_notificador(minha_funcao)   # minha_funcao(texto: str) -> None        (avisa o DONO)
    notificacoes.registrar_enviador(minha_funcao)      # minha_funcao(chave: str, texto: str) -> None  (avisa um CLIENTE)
Sem função registrada, nada é enviado. Falha no aviso nunca atrapalha o cliente.

Mensagens escritas pelo dono no PAINEL (interface_loja.py) ficam numa fila no mensagens.db. Para elas saírem:
    notificacoes.registrar_enviador(minha_funcao)   # a MESMA função de cima (adaptada ao Telegram/WhatsApp)
    notificacoes.iniciar_despachante()              # liga a thread que lê a fila a cada ~2 s e chama minha_funcao
O despachante só marca "bot online" no painel (e só envia) enquanto houver um enviador registrado.
(atendimento.py reexporta os dois registradores, então atendimento.registrar_notificador continua valendo.)
"""
import logging
import threading
from typing import Callable, Optional

import registro_mensagens

_notificador: Optional[Callable[[str], None]] = None
_enviador: Optional[Callable[[str, str], None]] = None


def registrar_notificador(funcao: Optional[Callable[[str], None]]) -> None:
    global _notificador
    _notificador = funcao


def registrar_enviador(funcao: Optional[Callable[[str, str], None]]) -> None:
    global _enviador
    _enviador = funcao


def avisar_cliente(chave: str, texto: str) -> bool:
    """Manda mensagem ao cliente pelo canal registrado. False se nenhum canal foi registrado."""
    funcao = _enviador
    if funcao is None:
        return False

    def enviar():
        try:
            funcao(chave, texto)
            _guardar_aviso(chave, texto, "enviada")
        except Exception:
            logging.exception("não consegui avisar o cliente %s", chave)
            _guardar_aviso(chave, texto, "erro")

    threading.Thread(target=enviar, daemon=True).start()
    return True


def _guardar_aviso(chave: str, texto: str, status: str) -> None:
    """Aviso automático ao cliente (comanda confirmada/cancelada pelo chat do vendedor) entra no histórico."""
    try:
        registro_mensagens.registrar(chave, "", "bot", texto, status)
    except Exception:
        logging.exception("não consegui registrar o aviso enviado a %s", chave)


def avisar_dono(texto: str) -> None:
    funcao = _notificador
    if funcao is None:
        return

    def enviar():   # em outra thread: o envio pode demorar e não deve travar o atendimento
        try:
            funcao(texto)
        except Exception:
            logging.exception("não consegui avisar o dono")

    threading.Thread(target=enviar, daemon=True).start()


# ------------------------------------------------------------------ despachante da fila do painel
_despachante: Optional[threading.Thread] = None
_parar = threading.Event()


def _laco(intervalo: float) -> None:
    while not _parar.is_set():
        try:
            funcao = _enviador
            if funcao is not None:   # sem canal registrado não envia nada e não se diz "online"
                registro_mensagens.batimento()
                for id_, chave, texto in registro_mensagens.reservar_pendentes():
                    try:
                        funcao(chave, texto)
                        registro_mensagens.concluir(id_, True)
                    except Exception as e:
                        logging.exception("não consegui enviar a mensagem do painel a %s", chave)
                        registro_mensagens.concluir(id_, False, str(e)[:300])
        except Exception:
            logging.exception("erro no despachante de mensagens")
        _parar.wait(intervalo)


def iniciar_despachante(intervalo: float = 2.0) -> None:
    """Liga a thread que envia as mensagens escritas no painel. Chame UMA vez, depois de registrar_enviador."""
    global _despachante
    if _despachante is not None and _despachante.is_alive():
        return
    try:
        registro_mensagens.marcar_interrompidos()
    except Exception:
        logging.exception("não consegui conferir a fila de envio")
    _parar.clear()
    _despachante = threading.Thread(target=_laco, args=(intervalo,), daemon=True, name="despachante-mensagens")
    _despachante.start()


def parar_despachante() -> None:
    _parar.set()


# Nomes originais (com underscore), mantidos para compatibilidade.
_avisar_cliente = avisar_cliente
_avisar_dono = avisar_dono
