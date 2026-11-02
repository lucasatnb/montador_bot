# Bicho & Cia — demonstração

> **Dados fictícios.** Produtos, preços, endereço, PIX e WhatsApp são de demonstração.
> Troque tudo antes de usar com um cliente real.

## Site
- Abra `site/index.html` no navegador (ou hospede a pasta `site/`).
- O `site.zip` é a mesma pasta pronta para subir em Vercel/Cloudflare Pages.
- O botão de pedido usa o WhatsApp fictício `5585999990000`. Troque no montador (aba 2) antes de divulgar.

## Bot (Telegram)
1. Crie um bot no @BotFather e copie o token.
2. Abra `bot/bot_config.json` e preencha `telegram > token`.
3. Rode `bot/iniciar_bot.bat` (Windows) ou `python bot/iniciar.py`.
4. No Telegram: `/start` → seu nome → `alimentos` → `ração` → `ração premium 15kg` → `sim` → o bot gera o PIX de demonstração.

O bot está com o canal **Telegram** por padrão. Para WhatsApp oficial, use a aba 3 do montador
e uma conta Cloud API da Meta; o canal não oficial (Evolution) é só para teste e pode banir o número.

## Estrutura
- `loja/` — catálogo, imagens, grupos e site gerado.
- `site/` — cópia pronta para hospedar.
- `bot/` — bot montado com uma cópia da loja.
- `site.zip` — pacote do site.

## Observação
As imagens são ilustrativas, geradas para a demonstração. Para o cliente real, use as fotos
dos produtos dele; isso muda muito a conversão.
