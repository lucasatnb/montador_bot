# Demonstrações — catálogo + site + atendente

Três lojas fictícias prontas para apresentar a donos de loja. Cada uma tem catálogo,
site de vitrine (com pedido no WhatsApp) e bot de atendimento já montado.

> **Dados fictícios.** Produtos, preços, WhatsApp, PIX e endereço são de demonstração.
> Troque tudo antes de usar com um cliente real.

## Abrir

- **Vitrine das demos:** abra `index.html` nesta pasta.
- **Site de cada loja:** `otica-visione/site/index.html`, `atelie-norte/site/index.html`,
  `bicho-e-cia/site/index.html`.
- **Pacote para hospedar:** o `site.zip` de cada loja (Vercel, Cloudflare Pages, Netlify etc.).

| Demo | Nicho | Molde | O que demonstra |
| --- | --- | --- | --- |
| **Visioné Ótica** | ótica | 3 | catálogo com grupos, orçamento e pedido de visita |
| **Ateliê Norte** | moda masculina | 4 | variações de tamanho/cor e pedido com PIX |
| **Bicho & Cia** | pet shop | 3 | grupos de produtos e pedido direto no WhatsApp |

Todas usam grupos acima das categorias (ex.: **Óculos de sol › Solar Masculino**) no site
e no bot.

## Bot (Telegram)

O bot de cada loja está em `<loja>/bot/` e vem com o canal **Telegram** por padrão.

1. Crie um bot no [@BotFather](https://t.me/BotFather) e copie o token.
2. Abra `<loja>/bot/bot_config.json` e preencha `telegram > token`.
3. Rode `iniciar_bot.bat` (Windows) ou `python iniciar.py` dentro de `bot/`.
4. Siga o roteiro do `COMO-USAR.md` de cada loja.

O WhatsApp do site é o número fictício **5585999990000**. Para uma apresentação real,
troque pelo seu número (ou pelo número do cliente) na aba 2 do montador antes de gerar o site.

## Roteiros rápidos

- **Visioné:** `/start` → nome → `óculos de sol` → `solar riviera` → cor → endereço (modo orçamento).
- **Ateliê Norte:** `/start` → nome → `roupas` → `camisetas` → `camiseta essential preta m` → `sim` → PIX demo.
- **Bicho & Cia:** `/start` → nome → `alimentos` → `ração` → `ração premium 15kg` → `sim` → PIX demo.

## Estrutura de cada loja

```
<demo>/
  loja/      catálogo, imagens, grupos e site gerado (fonte)
  site/      cópia pronta para hospedar
  site.zip   pacote do site
  bot/       bot montado com uma cópia da loja
  COMO-USAR.md
```

## Regerar

Na raiz do projeto:

```bash
python demonstracoes/_gerar_demos.py      # recria catálogo, site e bot (mantém as fotos)
python demonstracoes/_verificar_demos.py  # confere grupos, fotos, site, bot e zip
```

As imagens são ilustrativas, geradas para a demonstração. Se a geração de uma imagem
falhar, o script cria uma capa simples com a inicial do produto, para a demo não ficar
quebrada. Para o cliente real, use as fotos dos produtos dele: isso muda muito a conversão.

## Observações comerciais

- Use as demos para mostrar **antes** de pedir dados do cliente.
- Deixe claro que é uma loja fictícia e que o site dele será feito com os produtos dele.
- O bot pode rodar no Telegram na hora; o WhatsApp oficial exige conta Cloud API da Meta.
  O canal não oficial (Evolution) serve só para teste e pode banir o número.
