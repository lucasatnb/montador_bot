"""Configuração estática do bot de atendimento: textos, status, vendedores, PIX e vocabulário.

É AQUI que você edita textos, DONOS e as credenciais do PIX. Os outros módulos leem estes
valores pelo módulo (`configuracao.PIX_CHAVE`), então mudar aqui vale para o bot inteiro.
Só importa a biblioteca padrão: é a base do grafo de imports.
"""
import os
import sys
import threading

_PASTA_RAIZ = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
               else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:   # bot_config.json (gerado pelo montador); sem ele valem os padrões deste arquivo
    import bot_config
    _CFG = bot_config.CONFIG
    _PASTA_DA_CONFIG = bot_config.pasta_loja()
except ImportError:
    _CFG, _PASTA_DA_CONFIG = {}, ""

# ---- status novos do atendimento (os demais, "ok", "reperguntar"..., vêm do estoque)
PEDIR_NOME = "pedir_nome"
BOAS_VINDAS = "boas_vindas"
FECHADO = "fechado"
CONTINUAR = "continuar"
COMANDO_DONO = "comando_dono"
VITRINE = "vitrine"   # o cliente pediu um tipo de produto ("uma roupa") e o bot mostrou opções
PEDIR_ENDERECO = "pedir_endereco"   # loja por orçamento: itens fechados, falta o endereço da visita
ENDERECO_INVALIDO = "endereco_invalido"   # ... e o que o cliente mandou não parece um endereço (conta como "sem sentido")
BLOQUEADO = "bloqueado"   # cliente em timeout (anti-spam): a mensagem vem vazia (bot calado) ou é o aviso do bloqueio
# Fluxo: saudação -> nome -> LISTA DE CATEGORIAS -> o cliente escolhe uma -> LISTA DE ITENS da categoria
TEXTO_CATEGORIAS_TOPO = "Estas são as nossas categorias:"
TEXTO_CATEGORIAS_RODAPE = "Me diga qual grupo ou categoria você quer ver."
APOS_NOME_CATEGORIAS = "Prazer, {nome}!"   # vem antes da lista de categorias (loja sem categorias usa APOS_NOME)
TEXTO_VITRINE_TOPO = "Estes são os itens desta categoria:"   # {categoria} (opcional) = nome da categoria
TEXTO_VITRINE_VARIAS = "Quer ver só uma categoria? Diga, por exemplo: {exemplo}."
TEXTO_VITRINE_RODAPE = "Me diga qual você quer (nome e opções). Ex.: {exemplo}"   # {exemplo} sai do catálogo (vitrine.exemplo_de_pedido)
TEXTO_VITRINE_VAZIA = "No momento estamos sem itens de {categoria}. Posso te ajudar com outra coisa?"
TEXTO_CATEGORIAS_GRUPOS = "Grupos:"
TEXTO_CATEGORIAS_OUTRAS = "Outras categorias:"
TEXTO_SUBCATEGORIAS_TOPO = "No grupo {grupo}, temos estas categorias:"
TEXTO_SUBCATEGORIAS_RODAPE = "Me diga qual categoria você quer ver."
# ---- TEXTOS DO BOT: edite à vontade ({nome} é trocado pelo nome do cliente)
SAUDACAO = "Olá! 🍕 Bem-vindo(a) à [Nome da Pizzaria]. Para agilizar o seu atendimento, acesse nosso cardápio digital e monte seu pedido direto por aqui: [Link do Site]. É rápido e fácil!"
PERGUNTA_NOME = "Como posso te chamar?"
NOME_NAO_ENTENDIDO = "Não consegui entender seu nome. Pode me dizer só o primeiro nome?"
PEDIR_NOME_COM_CODIGO = "Recebi o seu pedido da página! 🛒 Só preciso do seu nome para fechar. Como posso te chamar?"
# Cliente que mandou o código da página sem passar pela saudação: o nome é pedido só no final
TEXTO_PEDIR_NOME_NO_FIM = "Recebi seu pedido e separei os itens! 🛒 Total: {total}. Para fechar a comanda, como posso te chamar?"
APOS_NOME = "Prazer, {nome}! O que você quer pedir? Por exemplo: {exemplo}."   # {exemplo} sai do catálogo
TEXTO_AGUARDANDO = "Assim que o pagamento for confirmado, aviso por aqui. Até lá seus itens ficam reservados."
TEXTO_CONFIRMADA = "Pagamento confirmado, {nome}! Obrigado pela compra (comanda nº {numero}). 😊"
TEXTO_CANCELADA = "Sua comanda nº {numero} foi cancelada e os itens voltaram ao estoque. Se quiser, é só fazer um novo pedido."
TEXTO_AJUDA_DONO = ("Comandos do vendedor:\nconfirmar 7  (pagamento recebido; na loja por orçamento, visita confirmada)\n"
                    "cancelar 7  (devolve os itens ao estoque)\npendentes  (comandas aguardando)\n"
                    "ligar 7  (loja por orçamento: liga o bot de novo para o cliente da comanda 7)")
TEXTO_PIX_NAO_CONFIGURADO = "(PIX ainda não configurado: preencha PIX_CHAVE, PIX_NOME e PIX_CIDADE em configuracao.py)"
# Aviso que o VENDEDOR recebe quando uma comanda fecha
TEXTO_AVISO_DONO = ("Nova comanda nº {numero}\nCliente: {nome} ({chave})\n{itens}\nTotal: {total}\n\n"
                    "Para confirmar o pagamento: confirmar {numero}\nPara cancelar e devolver ao estoque: cancelar {numero}")

# ---- LOJA POR ORÇAMENTO (config.json da loja: "orcamento": true; vale para a loja inteira, não por item).
# Em vez de pagamento: o bot pede o ENDEREÇO, a comanda fecha como pedido de VISITA e o vendedor confirma a visita.
TEXTO_PEDIR_ENDERECO = ("Para agendarmos a visita do orçamento, me diga o endereço completo: rua, número, bairro "
                        "e, se tiver, um ponto de referência.")
TEXTO_ENDERECO_INVALIDO = "Não consegui entender o endereço. Pode mandar rua, número e bairro?"
# {nome} {numero} {itens} {endereco}
TEXTO_FECHADO_ORCAMENTO = ("Pedido de orçamento registrado, {nome}! Comanda nº {numero}:\n{itens}\n"
                           "Endereço da visita: {endereco}\nValor: a combinar.\n\n"
                           "Nossa equipe vai falar com você por aqui para confirmar o dia e o horário da visita. "
                           "Até lá seus itens ficam reservados.")
TEXTO_VISITA_CONFIRMADA = "Visita confirmada, {nome}! Nossa equipe vai até o endereço combinado (comanda nº {numero}). 😊"
# Aviso que o VENDEDOR recebe quando uma comanda de orçamento fecha. {minutos} = quanto tempo o bot fica calado sozinho
TEXTO_AVISO_DONO_ORCAMENTO = ("Nova comanda de ORÇAMENTO nº {numero}\nCliente: {nome} ({chave})\n"
                              "Endereço da visita: {endereco}\n{itens}\n\n"
                              "Para confirmar a visita: confirmar {numero}\n"
                              "Para cancelar e devolver ao estoque: cancelar {numero}\n\n"
                              "O bot ficou calado com este cliente. Para ligar de novo: ligar {numero} "
                              "(se você não ligar, ele volta sozinho em {minutos} min).")
MIN_LETRAS_ENDERECO = 8   # abaixo disso (ou sem letra) o endereço é recusado e a mensagem conta como "sem sentido"

# ---- ANTI-SPAM (antispam.py) e CARRINHO PARADO (atendimento.py)
def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


MAX_MENSAGENS_IGUAIS = 3          # 3 mensagens iguais seguidas -> timeout
MAX_SEM_SENTIDO = 5               # 5 mensagens seguidas que o bot não entendeu -> timeout
TIMEOUT_BLOQUEIO_S = 10 * 60      # duração do timeout (10 min)
JANELA_REPETICAO_S = 5 * 60       # as repetições só contam se vierem dentro de 5 min uma da outra
STATUS_SEM_SENTIDO = {"nao_encontrado", ENDERECO_INVALIDO}   # status do estoque que contam como "sem sentido" (+ nome não entendido)
# Carrinho com itens já descontados do estoque, sem atividade por este tempo: o estoque é devolvido.
# Mude sem editar o código: variável de ambiente BOT_TEMPO_CARRINHO_MIN (minutos).
TEMPO_CARRINHO_S = _env_int("BOT_TEMPO_CARRINHO_MIN", 30) * 60
# LOJA POR ORÇAMENTO: depois que a comanda fecha, o bot fica calado com o cliente até o atendente LIGAR (comando
# "ligar 7" ou botão do painel) ou até passar este tempo, o que vier primeiro. Variável: BOT_PAUSA_ORCAMENTO_MIN.
PAUSA_ORCAMENTO_S = _env_int("BOT_PAUSA_ORCAMENTO_MIN", 60) * 60
TEXTO_BLOQUEIO_REPETIDO = ("Você mandou a mesma mensagem várias vezes seguidas. Vou pausar o atendimento por "
                           "{minutos} minutos. Depois disso é só me chamar de novo. 🙂")
TEXTO_BLOQUEIO_SEM_SENTIDO = ("Não estou conseguindo entender suas últimas mensagens. Vou pausar o atendimento por "
                              "{minutos} minutos; depois disso é só me chamar de novo. 🙂")
TEXTO_CARRINHO_EXPIRADO = ("Como ficou um tempo sem resposta, cancelei seu pedido em aberto e os itens voltaram "
                           "ao estoque. Se ainda quiser, é só mandar de novo. 😊")

# ---- VENDEDORES: chaves de quem pode confirmar/cancelar comandas, no formato do canal.
# Ex.: {"tg:123456789", "wa:5585999990000"}. Quem NÃO está aqui nunca consegue usar esses comandos.
DONOS: set = set()

# ---- CONFIGURE AQUI SEU PIX (sem isso o bot fecha a comanda mas avisa que o PIX não está configurado)
# Defina como variável de ambiente (não fica no código): PIX_CHAVE, PIX_NOME e PIX_CIDADE.
PIX_CHAVE = (os.environ.get("PIX_CHAVE") or (_CFG.get("pix") or {}).get("chave") or "").strip()     # CPF, telefone (+5585...), e-mail ou chave aleatória
PIX_NOME = (os.environ.get("PIX_NOME") or (_CFG.get("pix") or {}).get("nome") or "").strip()       # nome do recebedor (até 25 letras)
PIX_CIDADE = (os.environ.get("PIX_CIDADE") or (_CFG.get("pix") or {}).get("cidade") or "").strip()   # cidade do recebedor (até 15 letras)

# Pasta de saída do painel, onde ficam config.json, atributos.json e produtos_especializados.db
# (catalogo.db, opcional, também). O Estoque.da_pasta() lê o "modo" do config.json e escolhe o banco sozinho.
# Para usar outra pasta sem editar o código: defina a variável de ambiente BOT_PASTA_ESTOQUE.
PASTA_ESTOQUE = (os.environ.get("BOT_PASTA_ESTOQUE") or _PASTA_DA_CONFIG
                 or os.path.join(_PASTA_RAIZ, "loja"))

# ---- Trava ESTREITA do registro de comandas (comandas.db / comandas.xlsx).
# O bot NÃO tem mais trava global: clientes diferentes são atendidos em paralelo. Mas gravar a
# comanda (e o .xlsx) e confirmar/cancelar mexem em arquivo compartilhado, então essas operações
# curtas passam uma por vez por esta trava. Se registro_comandas já for seguro para threads, pode remover.
TRAVA_REGISTRO = threading.RLock()

# ---- vocabulário do nome do cliente (identificacao_cliente.py)
_PREFIXOS_NOME = [   # o que o cliente costuma dizer ANTES do nome (já sem acento, em minúsculas)
    ("meu", "nome", "e"), ("meu", "nome"), ("me", "chamo"), ("me", "chamam", "de"),
    ("pode", "me", "chamar", "de"), ("pode", "me", "chamar"), ("pode", "chamar", "de"),
    ("eu", "sou", "o"), ("eu", "sou", "a"), ("eu", "sou"), ("sou", "o"), ("sou", "a"), ("sou",),
    ("aqui", "e", "o"), ("aqui", "e", "a"), ("aqui", "e"), ("e", "o"), ("e", "a"),
    ("bom", "dia"), ("boa", "tarde"), ("boa", "noite"), ("oi",), ("ola",), ("opa",), ("eai",),
]
_NAO_E_NOME = {"quero", "queria", "gostaria", "preciso", "sim", "nao", "ok", "oi", "ola", "ver", "vou",
               "pode", "manda", "separa", "tem", "tudo", "bem", "obrigado", "obrigada", "oque"}
_PARTICULAS = {"de", "da", "do", "das", "dos", "e"}
_SAUDACOES = {"oi", "ola", "opa", "eai", "e", "ai", "bom", "boa", "dia", "tarde", "noite", "tudo", "bem",
              "hey", "hello", "hi", "salve", "fala", "olaa", "oii", "oie", "blz", "beleza"}

# ---- vocabulário do "é só isso mesmo?" (atendimento.py)
_FRASES_FIM = ("so isso", "mais nada", "nada mais")   # "é só isso": vale como "sim" mesmo com "não" junto ("não, mais nada")
_FRASES_FIM_ACAO = ("pode fechar", "pode finalizar", "fechar", "finalizar")   # têm verbo: "não quero fechar" NÃO fecha
# Respostas exatas de "sim" que o _SIM do estoque (constantes.py) NÃO cobre; o atendimento
# junta as duas listas em vez de repetir o que o estoque já tem.
_EXTRAS_FIM_SIM = {"ss", "isso mesmo", "so", "e so", "e isso", "certo", "pode ser", "fechou",
                   "sim obrigado", "sim obrigada"}


# ---- SOBRESCRITAS vindas do bot_config.json (o montador gera esse arquivo; pode editar à mão também).
# Só troca o que já existe aqui como texto; chave desconhecida é ignorada. Variável de ambiente ainda ganha.
for _k, _v in (_CFG.get("textos") or {}).items():
    if isinstance(globals().get(_k), str) and isinstance(_v, str) and _v.strip():
        globals()[_k] = _v


def _numero(valor, padrao):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


_a = _CFG.get("antispam") or {}
MAX_MENSAGENS_IGUAIS = _numero(_a.get("max_mensagens_iguais"), MAX_MENSAGENS_IGUAIS)
MAX_SEM_SENTIDO = _numero(_a.get("max_sem_sentido"), MAX_SEM_SENTIDO)
TIMEOUT_BLOQUEIO_S = _numero(_a.get("timeout_min"), TIMEOUT_BLOQUEIO_S // 60) * 60
JANELA_REPETICAO_S = _numero(_a.get("janela_min"), JANELA_REPETICAO_S // 60) * 60
if not os.environ.get("BOT_TEMPO_CARRINHO_MIN"):
    TEMPO_CARRINHO_S = _numero(_CFG.get("carrinho_minutos"), TEMPO_CARRINHO_S // 60) * 60
if not os.environ.get("BOT_PAUSA_ORCAMENTO_MIN"):
    PAUSA_ORCAMENTO_S = _numero(_CFG.get("orcamento_pausa_minutos"), PAUSA_ORCAMENTO_S // 60) * 60
