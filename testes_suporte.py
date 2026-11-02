"""Ajuda comum dos testes.

O ambiente do DSH bloqueia o diretório temporário do sistema e o `os.chmod` que o
`tempfile.TemporaryDirectory` usa na limpeza; por isso os testes criam o scratch DENTRO do
repositório (sempre gravável) com `mkdir` e o apagam com `shutil.rmtree`, que funcionam em
qualquer lugar. Fora desse contexto o comportamento é o mesmo de um TemporaryDirectory.
"""
import contextlib
import shutil
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


@contextlib.contextmanager
def tmpdir():
    """Diretório temporário auto-limpante criado dentro do repositório."""
    d = RAIZ / (".teste_tmp_" + uuid.uuid4().hex[:8])
    d.mkdir(parents=True, exist_ok=False)
    try:
        yield str(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
