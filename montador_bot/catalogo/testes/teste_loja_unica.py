"""Loja única: criar, reaproveitar, zerar. Roda numa pasta temporária (não toca em catalogo/loja)."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta catalogo/
from nucleo import gerar_pastas as gp

with tempfile.TemporaryDirectory() as td:
    gp.PASTA_LOJA = Path(td) / "loja"
    assert gp.loja_atual() is None
    loja = gp.criar_loja("  Pizzaria   do Zé ", gp.MODO_ESP)
    assert loja.nome == "Pizzaria do Zé" and loja.modo == gp.MODO_ESP and loja.imagens.is_dir()
    assert gp.loja_atual().nome == "Pizzaria do Zé"
    try:
        gp.criar_loja("Outra")
        raise SystemExit("deveria recusar uma segunda loja")
    except gp.ErroDados:
        pass
    loja.definir_nome("Pizzaria Nova")
    assert gp.loja_atual().nome == "Pizzaria Nova"
    gp.gravar_produto_catalogo(loja, "A000", "Pizza", 40.0, "Boa", "Pizzas")
    destino = gp.zerar_loja(loja)
    assert (destino / "catalogo.db").is_file() and not loja.db.exists()
    assert gp.loja_atual().nome == "Pizzaria Nova" and gp.loja_atual().modo == gp.MODO_ESP   # nome e modo ficam
print("TUDO OK")
