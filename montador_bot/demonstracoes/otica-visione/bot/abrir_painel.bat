@echo off
cd /d "%~dp0"
python -m pip install --quiet streamlit pandas
python -m streamlit run interface_loja.py
echo.
echo O painel parou. Leia a mensagem acima.
pause
