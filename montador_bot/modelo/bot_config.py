"""Lê o bot_config.json (gerado pelo montador) que fica ao lado deste arquivo. Só biblioteca padrão.

Tudo que muda de loja para loja (pasta da loja, token, PIX, textos, anti-spam) vem daqui.
Variáveis de ambiente continuam valendo e têm prioridade sobre o arquivo.
"""
import json
import os
import sys
from pathlib import Path

RAIZ = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent   # .exe: ao lado do executável
CAMINHO = Path(os.environ.get("BOT_CONFIG") or RAIZ / "bot_config.json")


def carregar() -> dict:
    if not CAMINHO.exists():
        return {}
    try:
        dados = json.loads(CAMINHO.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise RuntimeError(f"'{CAMINHO}' não é um JSON válido: {e}") from e
    return dados if isinstance(dados, dict) else {}


CONFIG = carregar()


def pasta_loja() -> str:
    """Pasta da loja (config.json, atributos.json, produtos_especializados.db). Relativa à raiz do bot."""
    bruto = (CONFIG.get("loja") or {}).get("pasta", "")
    if not bruto:
        return ""
    p = Path(bruto)
    return str(p if p.is_absolute() else (RAIZ / p).resolve())
