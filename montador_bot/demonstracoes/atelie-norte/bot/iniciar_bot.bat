@echo off
cd /d "%~dp0"
python -m pip install --quiet requests rapidfuzz
python iniciar.py
echo.
echo O bot parou. Leia a mensagem acima.
pause
