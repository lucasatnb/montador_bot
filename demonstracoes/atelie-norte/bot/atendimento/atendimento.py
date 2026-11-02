"""Núcleo do bot (controlador/orquestrador), independente do canal (Telegram agora, WhatsApp depois).

Entrada:  chave do cliente + texto que ele mandou.
Saída:    uma Resposta; o que você manda de volta ao cliente é r.mensagem.

Fluxo completo:
  1. saudação (SAUDACAO) + "como posso te chamar?"  -> r.status "pedir_nome"
  2. o cliente diz o nome (vale só para esta conversa) -> r.status "boas_vindas"
  3. o cliente pede e confirma (estoque)            -> r.status "ok": os itens entram na comanda dele
     e o bot pergunta "É só isso mesmo?"
  4. "sim"                                          -> r.status "fechado": a comanda é SALVA em
     comandas.db (com nome e id do cliente), mostra o total e o PIX, e a conversa
     ENCERRA: a próxima mensagem dele começa do zero (saudação e nome de novo).
     Ela nasce "aguardando": os itens ficam RESERVADOS (já saíram do estoque) até o vendedor decidir.
  5. "não" / pede mais coisa                        -> a comanda continua aberta e ele segue pedindo
  *. CÓDIGO DO CARRINHO (landing page), ex.: "2P001,1P004,AP002" (quantidade em hexadecimal + ID):
     vale a QUALQUER momento (não precisa de saudação nem de nome antes): separa o estoque e FECHA a
     comanda direto (passos 3 e 4 de uma vez), sem "posso separar?" nem "é só isso?".
     Se o cliente ainda não disse o nome, o bot separa os itens e pede o nome só no FINAL
     (r.status "pedir_nome"); ao receber o nome, a comanda fecha.
     Se faltar estoque, cai no fluxo normal ("quer levar só o que temos?").
  6. o VENDEDOR (quem estiver em DONOS) responde pelo próprio canal:
       "confirmar 7"  -> pagamento ok: comanda confirmada e o cliente é avisado
       "cancelar 7"   -> os itens VOLTAM ao estoque e o cliente é avisado
       "pendentes"    -> lista as comandas aguardando

  LOJA POR ORÇAMENTO (config.json da loja: "orcamento": true, a loja inteira): sem preços para o cliente ("a combinar").
     No passo 4, depois do "sim" (e do nome), o bot pede o ENDEREÇO da visita (r.status "pedir_endereco"); com o endereço
     a comanda fecha (tipo 'orcamento'), SEM PIX: o vendedor recebe o endereço e "confirmar 7" confirma a VISITA.
     Ao fechar, o bot fica CALADO com esse cliente (pausa) até o atendente ligar ("ligar 7" ou o painel) ou até passar
     cfg.PAUSA_ORCAMENTO_S (1 h); isso vale só neste modo e segura quem tenta fechar comanda atrás de comanda.

Status novos: "pedir_nome", "boas_vindas", "fechado", "continuar", "vitrine" e "comando_dono" (em configuracao.py).
  *. DEPOIS DO NOME o bot manda "Estas são as nossas categorias:" + a lista (r.status "boas_vindas"). Quando o cliente
     escolhe uma ("roupa"), o bot responde "Estes são os itens desta categoria:" + os itens (vitrine.py), r.status "vitrine".
     Loja por orçamento: nenhuma dessas listas (nem o carrinho) mostra preço.
Os demais status ("ok", "reperguntar", "sem_estoque"...) vêm do estoque.
Para o /start do canal, chame iniciar(chave) (recomeça a conversa). Canais sem /start (WhatsApp)
não precisam dele: a primeira mensagem de quem não tem conversa aberta já recebe a saudação.

Independente de canal: o núcleo só conhece a "chave" do cliente (texto qualquer: "tg:123", wa_id...).
  - atender() e iniciar() são thread-safe. Cada cliente (chave) tem a SUA trava: webhooks de
    clientes diferentes rodam em paralelo; mensagens do mesmo cliente seguem em fila.
  - aviso ao dono/cliente: registrar_notificador / registrar_enviador (reexportados de notificacoes).

Organização (uma responsabilidade por arquivo):
    configuracao.py          textos, status, DONOS, PIX, vocabulário  (EDITE AQUI)
    pagamento_pix.py         código PIX "copia e cola"
    identificacao_cliente.py nome e saudação do cliente
    notificacoes.py          avisos ao dono/cliente (rede e threads) + despachante da fila do painel
    antispam.py              timeout de 10 min: 3 mensagens iguais ou 5 sem sentido seguidas
    registro_mensagens.py    histórico das conversas e fila de envio (mensagens.db), compartilhado com o painel
    painel_vendedor.py       confirmar/cancelar/listar comandas
    vitrine.py               "uma roupa" -> mostra até 4 itens da categoria (descrição, preço, cores/tamanhos)
    atendimento.py           este arquivo: estado da conversa e máquina de estados
    (reaproveita do estoque: utilidades.py, constantes.py, modelos.py, comunicacao_com_estoque.py)
"""
import logging
import re
import threading
import time
from contextlib import contextmanager

from . import antispam
from . import configuracao as cfg
import registro_comandas
import registro_mensagens
from estoque.comunicacao_com_estoque import Estoque
from .configuracao import (   # status (reexportados)
    BLOQUEADO, BOAS_VINDAS, COMANDO_DONO, CONTINUAR, ENDERECO_INVALIDO, FECHADO, PEDIR_ENDERECO, PEDIR_NOME, VITRINE)
from estoque.constantes import _NAO, _NEGACAO, _SIM
from .identificacao_cliente import _eh_saudacao, _extrair_nome, _parece_produto
from estoque.modelos import Resposta
from .notificacoes import (   # noqa: F401 (API pública)
    avisar_cliente, avisar_dono, iniciar_despachante, parar_despachante, registrar_enviador, registrar_notificador)
from .painel_vendedor import comando_dono
from .pagamento_pix import pix_copia_e_cola
from . import vitrine
from estoque.utilidades import normalizar, reais

DONOS = cfg.DONOS   # o MESMO conjunto de configuracao.py: atendimento.DONOS.add("tg:123") continua valendo

# UMA instância só, criada uma vez: ela guarda as perguntas pendentes de cada cliente.
# da_pasta lê config.json (modo -> banco) e atributos.json (rótulos e sinônimos de cor/tamanho).
estoque = Estoque.da_pasta(cfg.PASTA_ESTOQUE)

# comanda aberta de cada cliente: chave -> {"itens": {id: [Produto, qtd]}, "perguntou_fim": bool}
_comandas: dict = {}

# nome de cada cliente NESTA conversa (só memória; some quando a comanda fecha) e quem acabou de
# receber a saudação e ainda não disse o nome
_nomes: dict = {}
_aguardando_nome: set = set()
# (legado) código do carrinho que chegava ANTES do nome. Agora o código vale a qualquer momento e o nome é
# pedido no final; o dicionário fica só para a limpeza e o _iniciar não quebrarem.
_codigo_pendente: dict = {}

# Uma trava POR CLIENTE (chave): o estado acima é sempre de um cliente só, então mensagens de
# clientes diferentes não precisam esperar umas pelas outras. Cada entrada é [trava, quantas threads a usam]:
# a trava nasce na primeira vez e é APAGADA quando a última thread larga (o dicionário não cresce com
# o tempo). Tudo isso sob a trava-guarda, então duas threads nunca ficam com travas diferentes da mesma chave.
_travas: dict = {}
_guarda_travas = threading.Lock()


@contextmanager
def _trava_do(chave: str):
    """Uso: `with _trava_do(chave): ...` (igual a antes)."""
    with _guarda_travas:
        entrada = _travas.get(chave)
        if entrada is None:
            entrada = _travas[chave] = [threading.RLock(), 0]
        entrada[1] += 1
    try:
        with entrada[0]:
            yield
    finally:
        with _guarda_travas:
            entrada[1] -= 1
            if entrada[1] == 0:
                _travas.pop(chave, None)


# ------------------------------------------------------------------ ganchos da comanda
def adicionar_na_comanda(chave: str, r) -> None:
    """Chamada a cada pedido confirmado (estoque já descontado). Só registra no log;
    a comanda só é gravada de verdade quando fecha (fechar_comanda)."""
    for i, nome in enumerate(r.nomes):
        logging.info("[comanda] %s: +%sx %s (R$ %.2f)", chave, r.quantidades[i], nome, r.subtotais[i])


def fechar_comanda(chave: str, nome: str, itens: list, total: float, endereco: str = "", tipo: str = "pedido") -> int:
    """Grava a comanda fechada (comandas.db) e devolve o nº dela.
    itens = [(Produto, qtd), ...]. Se não conseguir gravar no banco, levanta exceção.
    A gravação passa pela trava estreita do registro (arquivo compartilhado entre clientes)."""
    with cfg.TRAVA_REGISTRO:
        return registro_comandas.salvar_comanda(chave, nome, itens, total, endereco, tipo)


# ------------------------------------------------------------------ nome do cliente
def _nome_do_cliente(chave: str):
    """Nome do cliente NESTA conversa (só em memória: cada conversa começa pedindo o nome)."""
    return _nomes.get(chave)


def _registrar_conversa(chave: str, nome: str, texto, resposta: str) -> None:
    """Guarda no mensagens.db o que o cliente escreveu e o que o bot respondeu (o dono acompanha pelo painel),
    numa conexão e numa transação só. Nunca atrapalha o atendimento: se o banco falhar, só vai para o log."""
    try:
        itens = []
        if texto is not None:
            itens.append(("cliente", texto))
        if resposta:
            itens.append(("bot", resposta))
        registro_mensagens.registrar_varias(chave, nome, itens)
    except Exception:
        logging.exception("não consegui registrar a conversa de %s", chave)


def iniciar(chave: str) -> Resposta:
    """Começo da conversa (use no /start do canal): saudação e pergunta do nome."""
    with _trava_do(chave):
        if chave not in cfg.DONOS:
            if antispam.bloqueado(chave):
                return Resposta(BLOQUEADO, "")
            if antispam.registrar_mensagem(chave, "/start"):
                return Resposta(BLOQUEADO, _aviso_bloqueio(cfg.TEXTO_BLOQUEIO_REPETIDO))
        r = _iniciar(chave)
        _registrar_conversa(chave, "", None, r.mensagem)
        return r


def _iniciar(chave: str) -> Resposta:
    _nomes.pop(chave, None)
    _codigo_pendente.pop(chave, None)
    _aguardando_nome.add(chave)
    return Resposta(PEDIR_NOME, f"{cfg.SAUDACAO}\n{cfg.PERGUNTA_NOME}")


def _receber_nome(chave: str, texto: str) -> Resposta:
    if estoque.parece_codigo(texto):   # mandou (outro) código em vez do nome: guarda o mais recente
        _codigo_pendente[chave] = texto
        return Resposta(PEDIR_NOME, cfg.PERGUNTA_NOME)
    if _eh_saudacao(texto):   # respondeu "oi" à pergunta do nome: só repete a pergunta
        return Resposta(PEDIR_NOME, cfg.PERGUNTA_NOME)
    nome, tirou_prefixo = _extrair_nome(texto)
    if nome and not tirou_prefixo and _parece_produto(texto, estoque.produtos):
        nome = None   # "camiseta preta" é um pedido, não um nome
    if not nome:
        return Resposta(PEDIR_NOME, cfg.NOME_NAO_ENTENDIDO)
    _nomes[chave] = nome
    _aguardando_nome.discard(chave)
    codigo = _codigo_pendente.pop(chave, None)
    if codigo is not None:   # ele já tinha mandado o código da página: agora que tem nome, fecha o pedido
        r = _pedido(chave, codigo)
        r.mensagem = f"Prazer, {nome}!\n" + r.mensagem
        return r
    try:   # depois do nome: "Estas são as nossas categorias:" + a lista (loja sem categorias: mensagem antiga)
        categorias = vitrine.texto_categorias(estoque)
    except Exception:
        logging.exception("erro ao listar as categorias; sigo sem elas")
        categorias = None
    if categorias:
        return Resposta(BOAS_VINDAS, cfg.APOS_NOME_CATEGORIAS.format(nome=nome) + "\n" + categorias)
    return Resposta(BOAS_VINDAS, cfg.APOS_NOME.format(nome=nome, exemplo=vitrine.exemplo_de_pedido(estoque, itens=2)))


def _receber_nome_final(chave: str, texto: str) -> Resposta:
    """Resposta à pergunta de nome feita no FIM (cliente que mandou o código sem se apresentar)."""
    nome, tirou_prefixo = _extrair_nome(texto)
    if _eh_saudacao(texto) or not nome or (not tirou_prefixo and _parece_produto(texto, estoque.produtos)):
        return Resposta(PEDIR_NOME, cfg.NOME_NAO_ENTENDIDO)
    _nomes[chave] = nome
    return _fechar(chave)


# ------------------------------------------------------------------ "é só isso mesmo?"
# Respostas exatas de "sim": o _SIM do estoque + as extras de configuracao.py (não repete o que o estoque já tem)
_EXATAS_FIM = _SIM | cfg._EXTRAS_FIM_SIM
# "não" do estoque, menos "outro": aqui "outro tênis" é um PEDIDO NOVO, não uma negação
_NAO_FECHAR = _NAO - {"outro"}


def _regex_frases(frases) -> "re.Pattern":
    """Frase inteira, por PALAVRA ('fechar' não casa com 'fechado' nem com pedaço de outra palavra)."""
    return re.compile(r"\b(?:" + "|".join(re.escape(f) for f in frases) + r")\b")


_RE_FIM_SO = _regex_frases(cfg._FRASES_FIM)          # "só isso", "mais nada"...
_RE_FIM_ACAO = _regex_frases(cfg._FRASES_FIM_ACAO)   # "pode fechar", "finalizar"...
# o que pode vir depois de "sim" sem ser um pedido novo ("sim, obrigado", "sim pode fechar")
_ENFEITE_SIM = {"obrigado", "obrigada", "pode", "isso", "mesmo", "e", "so", "por", "favor", "pfv",
                "claro", "certo", "ok", "fechar", "finalizar"}


def _quer_fechar(texto: str):
    """True = é só isso (fechar) | False = quer mais | texto = pedido novo para o Estoque."""
    n = normalizar(texto)
    t = n.split()
    if not t:
        return texto
    if n in _EXATAS_FIM:
        return True
    if _RE_FIM_ACAO.search(n):
        if any(p in _NEGACAO for p in t):   # "não quero fechar ainda": NÃO fecha
            return False
        if "mais" not in t or _RE_FIM_SO.search(n):   # "fechar e mais uma calabresa" é pedido novo
            return True
        return texto
    if _RE_FIM_SO.search(n):
        return True
    if t[0] == "sim":
        resto = t[1:]
        if all(p in _ENFEITE_SIM for p in resto):
            return True
        return " ".join(resto)   # "sim uma calabresa" -> o pedido é "uma calabresa" (antes fechava e perdia o pedido)
    if t[0] in _NAO_FECHAR:
        resto = " ".join(t[1:])
        return False if not resto else resto   # "não, quero uma preta" -> pedido "quero uma preta"
    return texto   # qualquer outra coisa ("pode colocar uma preta tbm") é pedido novo


def _total(comanda: dict) -> float:
    return sum(p.preco * q for p, q in comanda["itens"].values())


def _endereco_valido(texto: str) -> bool:
    """Aceita qualquer coisa que se pareça com um endereço: letras suficientes e ao menos duas palavras
    (\"Rua das Flores 12, Centro\"). Recusa \"kkk\", \"aqui\", só números ou emoji."""
    t = " ".join(str(texto).split())
    letras = sum(1 for c in t if c.isalpha())
    return len(t) >= cfg.MIN_LETRAS_ENDERECO and letras >= 4 and len(t.split()) >= 2


def _receber_endereco(chave: str, texto: str) -> Resposta:
    """Resposta à pergunta do endereço (loja por orçamento): com endereço válido a comanda fecha."""
    comanda = _comandas[chave]
    if not _endereco_valido(texto):
        return Resposta(ENDERECO_INVALIDO, cfg.TEXTO_ENDERECO_INVALIDO)
    comanda["aguardando_endereco"] = False
    comanda["endereco"] = " ".join(str(texto).split())
    return _fechar(chave)


def _fechar(chave: str) -> Resposta:
    comanda = _comandas[chave]
    if not _nome_do_cliente(chave):   # pulou o atendimento (mandou o código direto): pede o nome só agora, no final
        comanda["aguardando_nome"] = True
        total = "a combinar" if estoque.orcamento else reais(_total(comanda))
        return Resposta(PEDIR_NOME, cfg.TEXTO_PEDIR_NOME_NO_FIM.format(total=total))
    orcamento = estoque.orcamento
    if orcamento and not comanda.get("endereco"):   # loja por orçamento: falta o endereço da visita
        comanda["aguardando_nome"] = False
        comanda["aguardando_endereco"] = True
        return Resposta(PEDIR_ENDERECO, cfg.TEXTO_PEDIR_ENDERECO)
    nome = _nome_do_cliente(chave)
    itens = [(p, q) for p, q in comanda["itens"].values()]
    total = _total(comanda)
    endereco = comanda.get("endereco", "") if orcamento else ""
    try:   # grava ANTES de zerar a comanda: se falhar, ele pode confirmar de novo
        numero = fechar_comanda(chave, nome, itens, total, endereco, "orcamento" if orcamento else "pedido")
    except Exception:
        logging.exception("não consegui gravar a comanda de %s", chave)
        if orcamento:
            comanda["aguardando_endereco"] = False
            comanda.pop("endereco", None)
            comanda["perguntou_fim"] = True
        else:
            comanda["perguntou_fim"] = True
        return Resposta("erro", "Não consegui fechar sua comanda agora. Responda \"sim\" de novo em instantes.")
    _comandas.pop(chave)
    _nomes.pop(chave, None)   # a conversa encerrou: a próxima mensagem dele começa do zero
    _aguardando_nome.discard(chave)
    if orcamento:
        return _fechado_orcamento(chave, nome, numero, itens, endereco)
    avisar_dono(cfg.TEXTO_AVISO_DONO.format(
        numero=numero, nome=nome or "(sem nome)", chave=chave, total=reais(total),
        itens="\n".join(f"{q}x {p.nome}" for p, q in itens)))
    linhas = [f"{q}x {p.nome} - {reais(p.preco * q)}" for p, q in itens]
    msg = (f"Fechado{', ' + nome if nome else ''}! Sua comanda nº {numero}:\n" + "\n".join(linhas)
           + f"\nTotal: {reais(total)}")
    if cfg.PIX_CHAVE and cfg.PIX_NOME and cfg.PIX_CIDADE:
        msg += "\n\nPague por PIX (copia e cola):\n" + pix_copia_e_cola(cfg.PIX_CHAVE, cfg.PIX_NOME, cfg.PIX_CIDADE, total)
    else:
        msg += "\n\n" + cfg.TEXTO_PIX_NAO_CONFIGURADO
    msg += "\n\n" + cfg.TEXTO_AGUARDANDO
    return Resposta(FECHADO, msg, itens[0][0], sum(q for _, q in itens), itens=itens)


def _fechado_orcamento(chave: str, nome: str, numero: int, itens: list, endereco: str) -> Resposta:
    """Comanda de ORÇAMENTO gravada: avisa o vendedor (com o endereço), responde ao cliente sem PIX e deixa o bot
    CALADO com ele até o atendente ligar ou até cfg.PAUSA_ORCAMENTO_S (1 h). Só roda na loja por orçamento."""
    minutos = cfg.PAUSA_ORCAMENTO_S // 60
    lista = "\n".join(f"{q}x {p.nome}" for p, q in itens)
    avisar_dono(cfg.TEXTO_AVISO_DONO_ORCAMENTO.format(
        numero=numero, nome=nome or "(sem nome)", chave=chave, endereco=endereco, itens=lista, minutos=minutos))
    if chave not in cfg.DONOS:   # vendedor testando o bot não se silencia
        try:
            registro_mensagens.pausar(chave, minutos)
        except Exception:   # sem a pausa o atendimento segue; só perde a trava anti-troll deste cliente
            logging.exception("não consegui pausar o bot para %s depois da comanda de orçamento", chave)
    msg = cfg.TEXTO_FECHADO_ORCAMENTO.format(nome=nome or "", numero=numero, itens=lista, endereco=endereco)
    return Resposta(FECHADO, msg, itens[0][0], sum(q for _, q in itens), itens=itens)


# ------------------------------------------------------------------ entrada única do bot
def esta_bloqueado(chave: str) -> bool:
    """True se o cliente está em timeout (anti-spam). Vendedores nunca ficam bloqueados."""
    return chave not in cfg.DONOS and antispam.bloqueado(chave)


def _aviso_bloqueio(modelo: str) -> str:
    return modelo.format(minutos=cfg.TIMEOUT_BLOQUEIO_S // 60)


def _sem_sentido(r) -> bool:
    """O bot não entendeu a mensagem? (produto não encontrado ou nome não entendido)"""
    if r.status in cfg.STATUS_SEM_SENTIDO or r.mensagem == cfg.NOME_NAO_ENTENDIDO:
        return True
    # "Não encontrei esse produto..." volta como "reperguntar" SEM opções e SEM nada a confirmar
    return r.status == "reperguntar" and not r.opcoes and not r.a_confirmar


def atender(chave: str, texto: str):
    """Ponto de entrada do bot. Thread-safe: clientes diferentes são atendidos em paralelo;
    as mensagens do mesmo cliente são processadas uma de cada vez.
    Anti-spam: 3 mensagens iguais seguidas ou 5 que o bot não entendeu -> timeout (r.status "bloqueado";
    r.mensagem vazia = bot calado, não mande nada ao cliente)."""
    with _trava_do(chave):
        cliente = chave not in cfg.DONOS
        if cliente:
            if antispam.bloqueado(chave):
                return Resposta(BLOQUEADO, "")
            if antispam.registrar_mensagem(chave, texto):
                return Resposta(BLOQUEADO, _aviso_bloqueio(cfg.TEXTO_BLOQUEIO_REPETIDO))
        nome_antes = _nome_do_cliente(chave)   # a comanda fechada apaga o nome: guarda antes
        r = _atender(chave, texto)
        if cliente and r.status != COMANDO_DONO and antispam.registrar_resultado(chave, _sem_sentido(r)):
            r = Resposta(BLOQUEADO, _aviso_bloqueio(cfg.TEXTO_BLOQUEIO_SEM_SENTIDO))
        if r.status != COMANDO_DONO:           # comandos do vendedor ("confirmar 7") não entram no histórico
            _registrar_conversa(chave, nome_antes or _nome_do_cliente(chave) or "", texto, r.mensagem)
        return r


def _atender(chave: str, texto: str):
    # 0) vendedor: "confirmar 7", "cancelar 7", "pendentes". Só vale para quem está em DONOS;
    #    qualquer outra mensagem dele segue o fluxo normal (ele também pode fazer pedidos).
    if chave in cfg.DONOS:
        resposta = comando_dono(texto, estoque)
        if resposta is not None:
            return Resposta(COMANDO_DONO, resposta)

    # 1) saudação e nome
    if _nome_do_cliente(chave) is None:
        c = _comandas.get(chave)
        if c and c.get("aguardando_nome"):   # já mandou o código; falta só o nome para fechar
            if estoque.parece_codigo(texto):   # mandou outro código em vez do nome: soma ao pedido e pede o nome de novo
                return _pedido(chave, texto)
            return _receber_nome_final(chave, texto)
        # código do carrinho (ou conversa já em andamento por causa dele) NÃO precisa de saudação nem de nome
        if estoque.parece_codigo(texto) or estoque.tem_pendencia(chave) or c:
            _aguardando_nome.discard(chave)
            _codigo_pendente.pop(chave, None)
            return _pedido(chave, texto)
        if chave not in _aguardando_nome:   # primeira mensagem dele: cumprimenta e pergunta o nome
            return _iniciar(chave)
        return _receber_nome(chave, texto)

    # 2) pedido, comanda e fechamento
    return _pedido(chave, texto)


def _pedido(chave: str, texto: str):
    """Pedido por texto ou por código do carrinho."""
    comanda = _comandas.get(chave)
    if comanda:
        comanda["atualizada"] = time.monotonic()   # cliente ativo: o relógio do carrinho parado recomeça
        if comanda.get("aguardando_endereco"):     # loja por orçamento: a resposta é o endereço da visita
            if not estoque.parece_codigo(texto):
                return _receber_endereco(chave, texto)
            comanda["aguardando_endereco"] = False   # mandou outro código do carrinho: soma ao pedido e pergunta de novo
    perguntando_fim = bool(comanda and comanda["perguntou_fim"])
    if comanda and comanda["perguntou_fim"]:       # o cliente está respondendo "é só isso mesmo?"
        comanda["perguntou_fim"] = False
        decisao = _quer_fechar(texto)
        if decisao is True:
            return _fechar(chave)
        if decisao is False:
            return Resposta(CONTINUAR, "Tudo bem! O que mais você quer?")
        texto = decisao                             # pedido novo: segue pro Estoque

    # pedido de CATEGORIA ("eu queria uma roupa"): mostra até 4 itens. Não entra no meio de uma pergunta do estoque
    # (ex.: "qual cor?") nem com código do carrinho.
    if not estoque.tem_pendencia(chave) and not estoque.parece_codigo(texto):
        try:
            vitrine_texto = vitrine.tentar(estoque, texto)
        except Exception:
            logging.exception("erro na vitrine; sigo com o atendimento normal")
            vitrine_texto = None
        if vitrine_texto is not None:
            if perguntando_fim and chave in _comandas:   # ainda dá para responder "é só isso" depois de ver a vitrine
                _comandas[chave]["perguntou_fim"] = True
            return Resposta(VITRINE, vitrine_texto)

    r = estoque.processar(texto, cliente=chave)
    if r.status == "ok":
        adicionar_na_comanda(chave, r)
        comanda = _comandas.setdefault(chave, {"itens": {}, "perguntou_fim": False})
        comanda["atualizada"] = time.monotonic()
        for p, q in r.itens:
            comanda["itens"].setdefault(p.id, [p, 0])[1] += q
        _guardar_carrinho(chave, comanda)   # estoque já saiu: anota no banco para poder devolver se o bot cair
        if r.codigo:   # veio pelo código da página: o cliente já montou e confirmou o carrinho, então fecha direto
            return _fechar(chave)
        comanda["perguntou_fim"] = True
        if estoque.orcamento:   # loja por orçamento: sem preço para o cliente
            r.mensagem += "\nÉ só isso mesmo? (sim/não)"
        else:
            r.mensagem += f"\nTotal da comanda: {reais(_total(comanda))}. É só isso mesmo? (sim/não)"
    return r


# ------------------------------------------------------------------ carrinho parado: devolve o estoque
def _guardar_carrinho(chave: str, comanda: dict) -> None:
    """Anota o carrinho aberto no comandas.db (some sozinho quando a comanda fecha). Falha só vai para o log."""
    try:
        with cfg.TRAVA_REGISTRO:
            registro_comandas.salvar_carrinho(chave, [(p.id, q) for p, q in comanda["itens"].values()])
    except Exception:
        logging.exception("não consegui anotar o carrinho de %s", chave)


def _devolver_ao_estoque(chave: str, itens: list) -> list:
    """itens = [(produto_id, qtd)]. Devolve ao estoque e responde a lista dos que NÃO conseguiu devolver."""
    falhas = []
    with cfg.TRAVA_REGISTRO:
        for produto_id, qtd in itens:
            try:
                devolveu = estoque.estornar(produto_id, qtd)
            except KeyError:
                devolveu = False
            if not devolveu:
                falhas.append(f"{qtd}x {produto_id}")
                logging.error("carrinho de %s: não consegui devolver %sx %s ao estoque (ajuste à mão)",
                              chave, qtd, produto_id)
        try:
            registro_comandas.apagar_carrinho(chave)
        except Exception:
            logging.exception("não consegui apagar o carrinho de %s do banco", chave)
    return falhas


def _expirar_carrinhos() -> None:
    """Carrinho sem atividade por cfg.TEMPO_CARRINHO_S: devolve os itens ao estoque e encerra a conversa."""
    for chave in list(_comandas):
        c = _comandas.get(chave)
        if c is None or time.monotonic() - c["atualizada"] < cfg.TEMPO_CARRINHO_S:
            continue
        with _trava_do(chave):   # mesma trava do atendimento: não corre junto com uma mensagem do cliente
            c = _comandas.get(chave)
            if c is None or time.monotonic() - c["atualizada"] < cfg.TEMPO_CARRINHO_S:
                continue   # o cliente voltou bem na hora
            _comandas.pop(chave)
            falhas = _devolver_ao_estoque(chave, [(p.id, q) for p, q in c["itens"].values()])
            _nomes.pop(chave, None)
            _aguardando_nome.discard(chave)
            _codigo_pendente.pop(chave, None)
        logging.info("carrinho de %s expirou por inatividade%s", chave,
                     f" (falhou ao devolver: {', '.join(falhas)})" if falhas else "; itens devolvidos ao estoque")
        avisar_cliente(chave, cfg.TEXTO_CARRINHO_EXPIRADO)


def recuperar_carrinhos_abandonados() -> int:
    """Ao ligar o bot: carrinhos que ficaram no banco são de conversas que se perderam (o estado vive em memória),
    mas os itens já tinham saído do estoque. Devolve tudo. Responde quantos carrinhos foram devolvidos."""
    carrinhos = registro_comandas.carrinhos_abertos()
    for chave, itens in carrinhos.items():
        _devolver_ao_estoque(chave, itens)
        logging.info("carrinho de %s sobrou de antes de reiniciar: itens devolvidos ao estoque", chave)
    return len(carrinhos)


_limpeza = None
_parar_limpeza = threading.Event()


def _laco_limpeza(intervalo: float) -> None:
    while not _parar_limpeza.is_set():
        try:
            _expirar_carrinhos()
            antispam.limpar()
            registro_mensagens.expirar_pausas()   # pausas com prazo vencidas (loja por orçamento)
        except Exception:
            logging.exception("erro na limpeza de carrinhos parados")
        _parar_limpeza.wait(intervalo)


def iniciar_limpeza_carrinhos(intervalo: float = 60.0) -> None:
    """Chame UMA vez ao ligar o bot (depois de registrar_enviador): devolve o que sobrou de antes de reiniciar
    e liga a thread que devolve ao estoque os carrinhos parados."""
    global _limpeza
    if _limpeza is not None and _limpeza.is_alive():
        return
    try:
        recuperar_carrinhos_abandonados()
    except Exception:
        logging.exception("não consegui conferir os carrinhos que sobraram de antes")
    _parar_limpeza.clear()
    _limpeza = threading.Thread(target=_laco_limpeza, args=(intervalo,), daemon=True, name="limpeza-carrinhos")
    _limpeza.start()


def parar_limpeza_carrinhos() -> None:
    _parar_limpeza.set()
