# catalogo (parte do montador)

Cadastro da loja do bot: produtos, fotos, variações e estoque inicial. Grava direto em SQLite, sem planilhas.
O montador tem **uma loja só**, em `catalogo/loja/` (criada na primeira vez que você abre a aba 1 do montador).
Para montar o bot de outro cliente, use **Zerar loja** na aba: nada é apagado, vai para `loja/_arquivo/<data>/`
(o nome, o modo e os atributos ficam). O site gerado (`loja/site/`) e as configurações dele (que vivem no `catalogo.db`) vão junto.
O site da loja é feito na aba **2 · Site** do montador (pasta `criador_site/`), lendo esta mesma loja.

## Como usar
- Normal: `abrir_montador.bat` (na pasta de cima) → aba **1 · Catálogo**. O montador copia `loja/` para dentro do bot.
- Sozinho, para testes: `streamlit run interface_catalogo.py` (dentro desta pasta).
- Teste automático: `python testes/teste_sem_planilha.py`.

## Estrutura
```
catalogo/
├── interface_catalogo.py     tela do cadastro; desenhar() é chamada pelo montador_ui.py
├── atributos_padrao.json     vocabulário padrão (tamanho, numeração, cor, borda)
├── categorias_presets.json   listas prontas (grupos + categorias + atributos por nicho)
├── nucleo/                   dados da loja
│   ├── gerar_pastas.py         a loja única, fotos, catalogo.db, acréscimos de preço
│   ├── banco_loja.py           grava produto/SKU direto no banco do bot
│   ├── formato_ids.py          IDs, SKUs e itens de carrinho
│   ├── grupos.py               grupos (subcategorias): <loja>/grupos_categorias.json
│   └── presets.py              lê as listas prontas (categorias_presets.json)
├── variacoes/                regras de variação (tamanho, cor...)
│   ├── atributos_loja.py       vocabulário da loja (atributos.json)
│   ├── constantes_especializado.py
│   ├── uso_atributos.py        o que já está em uso (não pode excluir)
│   ├── planilha_especializada.py   combinações, validação e grade da tela (o nome é de quando havia planilhas)
│   └── criar_banco_especializado.py  schema e validação do banco do bot
├── testes/teste_sem_planilha.py
└── loja/                     a loja (criada sozinha)
```

## Grupos (subcategorias)
As categorias atuais viram subcategorias. Um nível acima fica em `loja/grupos_categorias.json`
(`{"Roupas Masculinas": ["Camisetas", "Calças"]}`). Cada categoria pertence a um grupo só; categoria
sem grupo aparece solta. O site (moldes 1/3/4) mostra o título do grupo e o bot lista o grupo antes
das categorias. Na aba 1: seção «Grupos» para criar/renomear/mover e «Lista pronta» para aplicar um
modelo de loja de uma vez (só soma, nunca apaga).

## Depois que o bot está montado
O bot **não** leva este programa. Para mudar preço, nome, descrição ou categoria, o bot tem `alterar_loja.bat`
(script simples, só biblioteca padrão). Quantidade/ativo continuam no painel (`abrir_painel.bat`).
Para cadastrar produto novo ou mexer em variações e fotos, volte aqui, ajuste a loja e monte o bot de novo.

## Observação
O bot atual só atende lojas no modo **especializado** (o formulário já vem com ele marcado).
