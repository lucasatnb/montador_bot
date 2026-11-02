# Montador de bots

Cadastra a loja (catálogo), gera o site dela e entrega a pasta do bot pronta, tudo na mesma tela.

## Demonstrações prontas
A pasta `demonstracoes/` tem 3 lojas fictícias completas (catálogo, site e bot) para apresentar
a donos de loja: Visioné Ótica, Ateliê Norte e Bicho & Cia. Abra `demonstracoes/index.html`
para ver a vitrine das demos e leia `demonstracoes/LEIA-ME.md` para os roteiros de teste.
Para regerar: `python demonstracoes/_gerar_demos.py`.

## Usar
- **Com telas:** dê dois cliques em `abrir_montador.bat` (ou `streamlit run montador_ui.py`).
  A aba **1 · Catálogo** cadastra a loja (produtos, fotos, variações); a **2 · Site** gera o site da mesma loja;
  as abas 3 a 5 configuram o bot; a **6 · Montar** entrega.
- **Por linha de comando** (usa a loja já cadastrada em `catalogo/loja/`):
  `python montador.py --destino C:\bots --perfil meu_perfil.json`
  `python montador.py --destino C:\bots --loja C:\lojas\pizza-pepi.zip` (opcional: montar com outra loja, pasta ou .zip)
  `python montador.py --perfil-modelo meu_perfil.json` cria um perfil com todos os padrões para você editar.

## Site da loja (aba 2)
O site sai da **mesma loja** do bot (`catalogo/loja/`: mesmo `catalogo.db`, `produtos_especializados.db` e `imagens/`), então preço,
variação, foto e estoque nunca ficam diferentes entre site e bot. Na aba: logo (as 3 cores mais frequentes dela são sugeridas),
3 cores (60/30/10), molde (o programa recomenda um pelo número de categorias; dá para trocar), nome da loja, WhatsApp, preview
(celular ou computador) e **Gerar / regerar site**. Sai em `catalogo/loja/site/` e a aba tem **Baixar o site (.zip)**.
- O aviso amarelo lembra de regerar sempre que entrar/sair um item, mudar preço, foto, cor ou molde.
- O que a aba grava (nome do site, WhatsApp, cores, molde, logo) fica **dentro do `catalogo.db`** (tabelas `site_config` e `site_logo`).
- O `site/` **não vai para dentro do bot** (a montagem o ignora) e **«Zerar loja» o leva para `_arquivo/`** junto com o resto.
- Só entram no site produtos **aprovados** (com descrição e categoria) e com ao menos uma variação ativa à venda.
- Por linha de comando, sem telas: `python criador_site/gerador_site.py [pasta-da-loja] [molde 1-4]` (sem pasta, usa `catalogo/loja/`).

## Site → Telegram
Preencha o **@usuario do bot** na aba 3 (ou `--usuario-telegram`) e deixe o canal em Telegram: o site passa a pedir pelo Telegram
(sem isso, pede pelo WhatsApp) e a aba 2 avisa que o site está desatualizado até você regerá-lo. O botão do site abre
`https://t.me/<usuario>?start=<carrinho>`; o bot lê o carrinho e fecha o pedido direto, igual ao WhatsApp.
`<carrinho>` é o código de sempre com `-` no lugar de `,` (o Telegram não aceita vírgula e limita a 64 caracteres).
Carrinho maior que isso: o site copia o código e abre `https://t.me/<usuario>`; o cliente cola na conversa.
O passo a passo com o seu usuário sai no `LEIA-ME.txt` do bot montado.

## Esconder o código (só executáveis)
Marque **Entregar só executáveis** na aba 6 (ou `--exe` na linha de comando). Precisa de `pip install pyinstaller`.
O bot sai com `iniciar_bot`, `painel` e `alterar_loja` (.exe no Windows), `bot_config.json` e `loja/`; nenhum `.py`.
O `.exe` só é gerado **no Windows** (aqui foi testado em Linux, com o mesmo resultado). Demora alguns minutos; o painel pesa ~170 MB.
Obs.: PyInstaller dificulta ler o código, mas não é à prova de engenharia reversa.

## Canais (por onde o bot atende)
Escolha na aba **3 · Canal e PIX** (ou `--canal`); fica no campo `canal` do `bot_config.json`.

| canal | arquivo | para quê |
|---|---|---|
| `telegram` | `telegram_bot.py` | só para testar; não precisa de servidor |
| `whatsapp_oficial` | `whatsapp_oficial.py` | Cloud API da Meta (produção) |
| `whatsapp_nao_oficial` | `whatsapp_nao_oficial.py` | via Evolution API (QR code); risco de banimento, só teste com chip reserva |

`iniciar_bot.bat` liga o canal escolhido; cada arquivo também roda sozinho (`python whatsapp_oficial.py`).
`canal_comum.py` é a base dos dois de WhatsApp (fila por cliente, mini servidor de webhook, `canais.db`).
O passo a passo de cada canal está no começo do próprio arquivo `.py`.

Pontos de atenção:
- **Oficial:** o webhook precisa de URL pública em HTTPS (hospedagem ou túnel). Cliente identificado pelo BSUID (`user_id`);
  vendedor pode ser telefone ou BSUID. Fora da janela de 24h só sai template: cadastre um (1 variável) em `template_aviso_nome`
  para avisar o vendedor. Erro 130497 e conta em modo de teste são limites da Meta, não do código.
- **Não oficial:** o bot responde sempre no mesmo endereço em que recebeu (contas `@lid`), liga lid e telefone quando a Evolution
  informa os dois, e confere a instância ao ligar. Confira a licença da versão da Evolution que usar.
- **Os dois:** webhook repetido é descartado pelo id da mensagem; resposta longa é dividida; segredos somem dos logs.

## O que sai (`<destino>/<nome-do-bot>/`)
```
bot_config.json        <- TUDO que muda de loja para loja (pasta da loja, token, vendedores, PIX, textos, anti-spam)
iniciar_bot.bat        liga o bot no canal escolhido (iniciar.py)
abrir_painel.bat       painel do dono
alterar_loja.bat       mudança simples: preço, nome, descrição e categoria (alterar_loja.py, só biblioteca padrão)
telegram_bot.py, whatsapp_oficial.py, whatsapp_nao_oficial.py, canal_comum.py, iniciar.py,
atendimento/, estoque/, registro_*.py, interface_loja.py, bot_config.py
loja/                  a loja (cópia de catalogo/loja/)
```
O bot montado **não** leva o programa de catálogo nem o criador de site; eles ficam só aqui no montador (pastas `catalogo/` e `criador_site/`).

## Para a próxima loja
Na aba 1, use **Zerar loja** (nada é apagado: vai para `catalogo/loja/_arquivo/`) e cadastre a próxima.
O `bot_config.json` de um bot serve de perfil: envie ele na tela (ou `--perfil`), troque token, PIX e saudação.

## Loja por orçamento
Na aba **1 · Catálogo** (barra lateral) ligue **Esta loja trabalha por orçamento**. Vale para a loja inteira, não item a item
(fica em `loja/config.json` como `"orcamento": true`; o site e o bot leem dali).
- **Site:** mostra «A combinar» no lugar dos preços e o carrinho não mostra valores nem total (os preços continuam cadastrados,
  só o cliente não os vê). O botão vira «Pedir orçamento». Regere o site depois de ligar/desligar.
- **Bot:** não mostra preços; depois do «é só isso?» pede o **endereço**; a comanda fecha como pedido de **visita** (sem PIX).
  O vendedor recebe o endereço, e `confirmar 7` confirma a **visita** (não pagamento). `cancelar 7` devolve o estoque, como sempre.
- **Bot calado:** ao fechar a comanda o bot não responde mais a esse cliente até o atendente **ligar** (`ligar 7` no chat do
  vendedor, ou o botão no painel) ou até passar 1 hora (`orcamento_pausa_minutos` no `bot_config.json`, ou `BOT_PAUSA_ORCAMENTO_MIN`).
  Só neste modo; vendedor testando o bot não é silenciado.
- Ligar/desligar no catálogo vale na hora para um bot que já roda com a mesma pasta `loja/`; o **site** só muda ao ser regerado.

## Fluxo do atendimento
Saudação → nome → **«Estas são as nossas categorias:»** + lista → o cliente diz a categoria → **«Estes são os itens desta categoria:»** + itens
(até 20 por categoria). Loja sem categorias pula a lista. Os textos são editáveis (`TEXTO_CATEGORIAS_TOPO`, `TEXTO_VITRINE_TOPO`...).
Com **grupos** (subcategorias): a lista mostra os grupos (e as categorias soltas); o cliente diz o grupo → o bot lista as categorias dele →
o cliente diz a categoria → itens. Na loja por orçamento nenhuma lista, pergunta de confirmação nem carrinho mostra preço.

## Painel: aba «Catálogo»
No painel do dono (`painel.exe` / `abrir_painel.bat`): adicionar produto (nome, descrição, categoria, preço), editar e remover.
Vale na hora para o bot; o site precisa ser regerado no montador. Remover tira da venda mas guarda o histórico (o ID não é reaproveitado).
Código em `modelo/catalogo_loja.py`.

## Regras
- Nunca escreve em pasta que já existe (pode ter comandas e conversas). A loja de `catalogo/loja/` não é alterada pela montagem.
- Variáveis de ambiente (TELEGRAM_TOKEN, PIX_CHAVE, BOT_PASTA_ESTOQUE...) continuam tendo prioridade sobre o arquivo.
- O `bot_config.json` guarda o token: não compartilhe a pasta sem apagá-lo.

## Se mudar o código do bot
Edite a pasta `modelo/` (é a cópia que o montador distribui; o catálogo fica fora dela, em `catalogo/`). Ela já lê o `bot_config.json`; os arquivos
`atendimento/configuracao.py`, `interface_loja.py` e `telegram_bot.py` foram ajustados para isso, e há o `bot_config.py` novo.
Os textos configuráveis estão na lista `TEXTOS` do `montador.py`; os padrões vêm do próprio `configuracao.py`.
