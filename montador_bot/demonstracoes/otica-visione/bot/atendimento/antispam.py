"""Trava anti-spam por cliente (independente de canal; só guarda estado em memória).

Duas regras, ambas dão TIMEOUT de configuracao.TIMEOUT_BLOQUEIO_S (10 min):
  1. MAX_MENSAGENS_IGUAIS (3) mensagens IGUAIS seguidas (comparação sem acento/pontuação/maiúsculas),
     dentro da janela JANELA_REPETICAO_S. Qualquer mensagem diferente zera a contagem.
  2. MAX_SEM_SENTIDO (5) respostas SEM SENTIDO seguidas: o bot não entendeu (produto não encontrado,
     nome não entendido...). Qualquer mensagem entendida zera a contagem.

Durante o timeout o bot fica calado (o aviso é mandado uma vez, na mensagem que disparou o bloqueio).
Quando o tempo acaba, os contadores começam do zero. Vendedores (DONOS) nunca passam por aqui.
"""
import threading
import time
from dataclasses import dataclass

from . import configuracao as cfg
from estoque.utilidades import normalizar


@dataclass
class _Estado:
    ultima: str = ""          # última mensagem (normalizada)
    repeticoes: int = 0       # quantas vezes seguidas ela apareceu
    ultima_em: float = 0.0    # quando chegou (time.monotonic)
    sem_sentido: int = 0      # respostas sem sentido seguidas
    bloqueado_ate: float = 0.0


_estados: dict = {}
_trava = threading.Lock()


def _bloquear(e: _Estado, agora: float) -> None:
    e.bloqueado_ate = agora + cfg.TIMEOUT_BLOQUEIO_S
    e.ultima, e.repeticoes, e.sem_sentido = "", 0, 0


def bloqueado(chave: str) -> bool:
    """True enquanto o cliente está em timeout."""
    with _trava:
        e = _estados.get(chave)
        return e is not None and e.bloqueado_ate > time.monotonic()


def registrar_mensagem(chave: str, texto: str) -> bool:
    """Conta a mensagem que chegou. Devolve True se ESTA mensagem completou as repetições e disparou o timeout."""
    agora = time.monotonic()
    with _trava:
        e = _estados.setdefault(chave, _Estado())
        if e.bloqueado_ate > agora:
            return False
        n = normalizar(texto) or str(texto).strip().lower()   # só emoji: normalizar() dá vazio
        if n and n == e.ultima and agora - e.ultima_em <= cfg.JANELA_REPETICAO_S:
            e.repeticoes += 1
        else:
            e.ultima, e.repeticoes = n, 1
        e.ultima_em = agora
        if e.repeticoes >= cfg.MAX_MENSAGENS_IGUAIS:
            _bloquear(e, agora)
            return True
        return False


def registrar_resultado(chave: str, sem_sentido: bool) -> bool:
    """Depois que o bot respondeu: diz se a mensagem não fez sentido. Devolve True se isso disparou o timeout."""
    agora = time.monotonic()
    with _trava:
        e = _estados.setdefault(chave, _Estado())
        if e.bloqueado_ate > agora:
            return False
        if not sem_sentido:
            e.sem_sentido = 0
            return False
        e.sem_sentido += 1
        if e.sem_sentido >= cfg.MAX_SEM_SENTIDO:
            _bloquear(e, agora)
            return True
        return False


def limpar() -> None:
    """Esquece clientes parados há mais de 1 hora (e sem timeout ativo), para o dicionário não crescer sem fim."""
    agora = time.monotonic()
    with _trava:
        for chave in [c for c, e in _estados.items()
                      if e.bloqueado_ate <= agora and agora - max(e.ultima_em, e.bloqueado_ate) > 3600]:
            del _estados[chave]
