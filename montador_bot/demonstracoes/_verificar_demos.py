import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parent

problemas = []
for d in sorted(p for p in root.iterdir() if (p / "site" / "index.html").is_file()):
    site = d / "site"
    texto = (site / "dados.js").read_text(encoding="utf-8")
    dados = json.loads(texto.split("=", 1)[1].strip().rstrip(";"))
    cfg = json.loads((d / "bot" / "bot_config.json").read_text(encoding="utf-8"))
    grupos = json.loads((d / "loja" / "grupos_categorias.json").read_text(encoding="utf-8"))
    grupos_site = {g["nome"]: g["categorias"] for g in dados.get("grupos") or []}
    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    imgs = list((d / "loja" / "imagens").glob("*/01.jpg"))
    categorias = {p["categoria"] for p in dados["produtos"]}
    nos_grupos = {c for cats in grupos.values() for c in cats}
    orfas = notas = []
    if not nos_grupos <= categorias:
        orfas = sorted(nos_grupos - categorias)
    com_grupo = {c for cats in grupos.values() for c in cats}
    sem_grupo = sorted(categorias - com_grupo)
    if grupos_site != grupos:
        problemas.append(f"{d.name}: grupos do site diferentes do catálogo")
    if orfas:
        problemas.append(f"{d.name}: grupos com categoria sem produto: {orfas}")
    if not (site / "index.html").is_file():
        problemas.append(f"{d.name}: site/index.html ausente")
    if not (d / "bot" / "iniciar.py").is_file():
        problemas.append(f"{d.name}: bot/iniciar.py ausente")
    if cfg.get("telegram", {}).get("token"):
        problemas.append(f"{d.name}: token de Telegram preenchido numa demo")
    if not (d / "site.zip").is_file():
        problemas.append(f"{d.name}: site.zip ausente")
    print(
        f"{d.name}: produtos={len(dados['produtos'])} grupos={len(grupos)} "
        f"fotos={len(imgs)} sem_grupo={sem_grupo or '-'} bot=ok "
        f"zip=ok total={total / 1e6:.1f}MB"
    )

if problemas:
    print("\nPROBLEMAS:")
    for p in problemas:
        print(" -", p)
    raise SystemExit(1)
print("\nTudo certo.")
