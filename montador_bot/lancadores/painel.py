"""Lançador do painel do dono dentro do .exe: abre o Streamlit apontando para a tela embutida."""
import os
import sys

if __name__ == "__main__":
    from streamlit.web import cli
    tela = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "interface_loja.py")
    sys.argv = ["streamlit", "run", tela, "--global.developmentMode=false", "--browser.gatherUsageStats=false"]
    sys.exit(cli.main())
