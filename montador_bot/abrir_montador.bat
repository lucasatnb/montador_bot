@echo off
cd /d "%~dp0"
python -m pip install --quiet streamlit pandas pillow
python -m streamlit run montador_ui.py
echo.
echo O montador parou. Leia a mensagem acima.
pause
