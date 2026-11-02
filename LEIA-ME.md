# Montador de bots

Entrega a pasta de um bot pronta a partir da pasta (ou .zip) de uma loja.

## Usar
- **Com telas:** dê dois cliques em `abrir_montador.bat` (ou `streamlit run montador_ui.py`).
- **Por linha de comando:**
  `python montador.py --loja C:\lojas\pizza-pepi.zip --destino C:\bots --perfil meu_perfil.json`
  `python montador.py --perfil-modelo meu_perfil.json` cria um perfil com todos os padrões para você editar.

## O que sai (`<destino>/<nome-do-bot>/`)
```
bot_config.json        <- TUDO que muda de loja para loja (pasta da loja, token, vendedores, PIX, textos, anti-spam)
iniciar_bot.bat        liga o bot do Telegram
abrir_painel.bat       painel do dono
abrir_catalogo.bat     cadastro de produtos (se incluído)
telegram_bot.py, atendimento/, estoque/, registro_*.py, interface_loja.py, bot_config.py
catalogo/loja_catalogo/lojas/<loja>/   a loja (o bot e o catálogo usam a MESMA pasta)
```
Sem catálogo, a loja fica em `loja/`.

## Para a próxima loja
O `bot_config.json` de um bot serve de perfil: envie ele na tela (ou `--perfil`), troque token, PIX e saudação.

## Regras
- Nunca escreve em pasta que já existe (pode ter comandas e conversas). A pasta original da loja não é alterada.
- Variáveis de ambiente (TELEGRAM_TOKEN, PIX_CHAVE, BOT_PASTA_ESTOQUE...) continuam tendo prioridade sobre o arquivo.
- O `bot_config.json` guarda o token: não compartilhe a pasta sem apagá-lo.

## Se mudar o código do bot
Edite a pasta `modelo/` (é a cópia que o montador distribui). Ela já lê o `bot_config.json`; os arquivos
`atendimento/configuracao.py`, `interface_loja.py` e `telegram_bot.py` foram ajustados para isso, e há o `bot_config.py` novo.
Os textos configuráveis estão na lista `TEXTOS` do `montador.py`; os padrões vêm do próprio `configuracao.py`.
