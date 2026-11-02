# criador_site (parte do montador)

Gera o **site estático** (HTML/CSS/JS, abre direto no navegador) da loja cadastrada no catálogo. Lê a mesma pasta que o bot recebe:
`catalogo/loja/` (`catalogo.db`, `produtos_especializados.db`, `imagens/`). Escreve em `catalogo/loja/site/`.

## Como usar
- Normal: `abrir_montador.bat` → aba **2 · Site**.
- Sozinho, para testes: `streamlit run interface_site.py` (dentro desta pasta).
- Sem telas: `python gerador_site.py [pasta-da-loja] [molde 1-4]`. Sem pasta, usa `catalogo/loja/`
  (a variável de ambiente `SITE_PASTA_DADOS` aponta outra).

## Arquivos
```
interface_site.py   a tela; desenhar() é chamada pelo montador_ui.py (não tem set_page_config nem st.stop)
gerador_site.py     lê os bancos, escolhe o molde, monta o preview e escreve o site/ (não usa Streamlit)
moldes_site/        _comum/ (cabeçalho, gaveta, base.css, core.js) + molde1..4 (index.html, layout.css, script.js)
```

## O que vem da loja e o que o site grava
- **Da loja (só leitura):** produtos, fotos, variações, preço por SKU, estoque; do `config.json`: `nome` (nome padrão do site) e
  `orcamento` (loja por orçamento: «A combinar» no lugar dos preços, sem total no carrinho).
- **Do montador:** o `@usuario` do bot, quando o canal é Telegram: o botão do carrinho abre `t.me/<bot>?start=<carrinho>`
  (carrinho com `-` no lugar de `,`; acima de 64 caracteres o site copia o código e abre o bot). Não é gravado em lugar nenhum.
- **Gravado no `catalogo.db`** (tabelas `site_config` e `site_logo`): nome do site, WhatsApp, mensagem inicial, «usar estoque»,
  «pedido só com nomes», cores, molde e logo. O «Regerar catalogo.db» do catálogo não apaga essas tabelas.

## Moldes (a recomendação vem do número de categorias)
1 sem categorias (lista) · 2 exatamente 2 categorias (tela dividida) · 3 três ou mais (carrosséis) ·
4 muitas categorias e itens (busca + abas). Os cortes estão em `MOLDES_CFG` no `gerador_site.py`.

## Grupos (subcategorias)
Se a loja tiver `grupos_categorias.json` (feito na aba 1 do montador), o site mostra o título do grupo
acima das categorias dele (moldes 1/3/4; no molde 4 as abas viram os grupos). Sem o arquivo, nada muda.

## Depois de gerar
Hospede a pasta `site/` (ou entregue o .zip da aba). Regere sempre que mudar produto, preço, foto, cor, molde, orçamento
ou o @usuario do Telegram: a aba avisa quando o site está desatualizado.
