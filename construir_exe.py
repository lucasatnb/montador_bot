"""construir_exe.py -- troca o código-fonte de um bot montado por executáveis (PyInstaller).

Deixa na pasta só: iniciar_bot, painel, alterar_loja (.exe no Windows), bot_config.json, loja/ e LEIA-ME.txt.
Só dá para gerar .exe NO WINDOWS (o PyInstaller não faz build cruzado). Em outro sistema sai um executável
daquele sistema, útil só para testar.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
LANCADORES = AQUI / "lancadores"

# (nome do executável, script de entrada, o que mais embutir)
ALVOS = [
    ("iniciar_bot", "iniciar.py", ["--hidden-import=telegram_bot", "--hidden-import=whatsapp_oficial",
                                   "--hidden-import=whatsapp_nao_oficial", "--hidden-import=atendimento",
                                   "--collect-submodules=atendimento", "--collect-submodules=estoque",
                                   "--hidden-import=rapidfuzz", "--hidden-import=requests"]),
    ("painel", None, ["--collect-all=streamlit", "--copy-metadata=streamlit", "--copy-metadata=pandas",
                      "--hidden-import=pandas", "--hidden-import=bot_config", "--hidden-import=registro_mensagens",
                      "--hidden-import=registro_comandas", "--hidden-import=catalogo_loja", "--hidden-import=alterar_loja",
                      "--collect-submodules=estoque",
                      "--collect-submodules=atendimento", "--hidden-import=rapidfuzz"]),
    ("alterar_loja", "alterar_loja.py", []),
]


def disponivel() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def converter(pasta_bot: Path, passos: list, avisos: list) -> None:
    """Gera os executáveis a partir dos .py de `pasta_bot` e apaga o código-fonte dela."""
    if not disponivel():
        raise RuntimeError("Falta o PyInstaller neste Python (pip install pyinstaller).")
    if sys.platform != "win32":
        avisos.append("Isto NÃO é Windows: os executáveis gerados só rodam neste sistema. Para entregar a clientes "
                      "com Windows, monte o bot num Windows.")
    ext = ".exe" if sys.platform == "win32" else ""
    with tempfile.TemporaryDirectory(prefix="montador_exe_") as tmp:
        tmp = Path(tmp)
        for nome, script, extra in ALVOS:
            entrada = str(pasta_bot / script) if script else str(LANCADORES / "painel.py")
            cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--clean",
                   "--name", nome, "--distpath", str(tmp / "dist"), "--workpath", str(tmp / "build"),
                   "--specpath", str(tmp / "spec"), "--paths", str(pasta_bot)]
            if nome == "painel":
                cmd += ["--add-data", f"{pasta_bot / 'interface_loja.py'}{';' if sys.platform == 'win32' else ':'}."]
            else:
                cmd += ["--console"]
            r = subprocess.run(cmd + extra + [entrada], capture_output=True, text=True, cwd=tmp)
            if r.returncode or not (tmp / "dist" / (nome + ext)).is_file():
                raise RuntimeError(f"Não consegui gerar '{nome}': " + (r.stderr.strip().splitlines() or ["erro desconhecido"])[-1])
            passos.append(f"Gerei {nome}{ext}.")
        for item in list(pasta_bot.iterdir()):   # some o código-fonte e os atalhos que dependiam dele
            if item.name in ("bot_config.json", "loja", "LEIA-ME.txt", ".gitignore"):
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        for nome, _, _ in ALVOS:
            shutil.move(str(tmp / "dist" / (nome + ext)), str(pasta_bot / (nome + ext)))
    antigo = (pasta_bot / "LEIA-ME.txt").read_text(encoding="utf-8")   # guarda o bloco do link do site
    ini = antigo.find("LIGAR O SITE")
    bloco = ("\n" + antigo[ini:antigo.find("CONFIGURAÇÃO", ini)]) if ini >= 0 else ""
    (pasta_bot / "LEIA-ME.txt").write_text(
        "COMO USAR\n  iniciar_bot  liga o bot no canal escolhido em bot_config.json\n"
        "  painel       painel do dono (comandas, mensagens, catálogo e estoque)\n"
        "  alterar_loja mudança simples: preço, nome, descrição e categoria\n\n"
        "" + bloco + "\nbot_config.json (token, vendedores, PIX, textos) e a pasta loja/ ficam ao lado dos executáveis e podem ser editados.\n"
        "CUIDADO: bot_config.json tem o token do bot; não envie a pasta sem apagá-lo.\n", encoding="utf-8")
    passos.append("Removi o código-fonte: ficaram só os executáveis, bot_config.json e loja/.")
