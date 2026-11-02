# loja_catalogo

Cadastro de catálogo + gerenciador de estoque por loja. Tudo grava direto em bancos SQLite (sem planilhas).

## Estrutura
```
loja_catalogo/
├── interface_catalogo.py     streamlit run interface_catalogo.py   (cadastrar produtos, fotos, atributos)
├── interface_estoque.py      streamlit run interface_estoque.py    (monitorar/editar/zerar estoque)
├── atributos_padrao.json     (NÃO veio nos uploads: coloque aqui, na raiz)
├── requirements.txt
├── nucleo/                   dados da loja
│   ├── gerar_pastas.py         lojas, fotos, catalogo.db, acréscimos de preço
│   ├── banco_loja.py           grava produto/SKU direto no banco do bot
│   ├── estoque_loja.py         estoque real: editar, zerar, desfazer, registro
│   └── formato_ids.py          IDs, SKUs e itens de carrinho
├── variacoes/                regras de variação (tamanho, cor...)
│   ├── atributos_loja.py       vocabulário de cada loja (atributos.json)
│   ├── constantes_especializado.py
│   ├── uso_atributos.py        o que já está em uso (não pode excluir)
│   ├── planilha_especializada.py   combinações, validação e grade da tela
│   └── criar_banco_especializado.py  schema e validação do banco do bot
├── testes/
│   ├── teste_sem_planilha.py   python testes/teste_sem_planilha.py
│   └── legado_a_reescrever/    testes antigos (ainda apontam para planilhas/importadores)
└── lojas/                    criada sozinha ao criar a primeira loja
```

## Fora deste pacote (precisa existir)
- `estoque/utilidades.py` (pacote do bot, função `normalizar`): usado por `criar_banco_especializado.py`.
  O pacote `estoque/` precisa estar nesta pasta ou em alguma pasta acima dela.
- `atributos_padrao.json`: usado pelo botão de atributos padrão; sem ele o vocabulário padrão fica vazio.
- Se o bot importa `formato_ids` ou `constantes_especializado`, o caminho mudou:
  `from loja_catalogo.nucleo import formato_ids` (ou ajuste o import dele).
