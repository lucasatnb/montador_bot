"""Atendimento ao cliente. Reexporta a API pública, então `import atendimento; atendimento.atender(...)`
continua funcionando como quando era um arquivo só."""
from .atendimento import (  # noqa: F401
    BLOQUEADO, BOAS_VINDAS, COMANDO_DONO, CONTINUAR, DONOS, FECHADO, PEDIR_NOME,
    atender, esta_bloqueado, estoque, iniciar, iniciar_limpeza_carrinhos, parar_limpeza_carrinhos,
    registrar_enviador, registrar_notificador,
)
