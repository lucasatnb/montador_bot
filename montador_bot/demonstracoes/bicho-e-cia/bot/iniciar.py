"""Liga o bot no canal escolhido em bot_config.json ("canal"):  telegram | whatsapp_oficial | whatsapp_nao_oficial.

    python iniciar.py                      usa o canal do bot_config.json
    python iniciar.py whatsapp_oficial     força um canal (os três arquivos também rodam direto: python whatsapp_oficial.py)
"""
import importlib
import sys

import bot_config

MODULOS = {"telegram": "telegram_bot", "whatsapp_oficial": "whatsapp_oficial",
           "whatsapp_nao_oficial": "whatsapp_nao_oficial"}

canal = (sys.argv[1] if len(sys.argv) > 1 else bot_config.CONFIG.get("canal") or "telegram").strip().lower()
if canal not in MODULOS:
    sys.exit(f"Canal '{canal}' não existe. Use um destes: {', '.join(MODULOS)} (campo \"canal\" do bot_config.json).")
print(f"Ligando o canal: {canal}")
importlib.import_module(MODULOS[canal]).main()
