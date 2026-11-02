"""Peça de estoque (controlador/orquestrador).

Uso:
    est = Estoque.da_pasta("pasta_de_saida")   # lê config.json + atributos.json e escolhe o banco do modo
    # (ou, direto:  est = Estoque("pasta_de_saida/produtos_especializados.db"))
    r = est.processar("quero 2 kamisetas pretas e 1 calça jeans", cliente="5585999990000")
    # r.status    -> "ok" | "reperguntar" | "sem_estoque" | "nao_encontrado" | "cancelado" | "erro"
    # r.mensagem  -> texto pronto para mandar ao cliente
    # SÓ COM status "ok" (o que foi realmente separado e descontado) vêm preenchidos:
    # r.itens     -> [(Produto, quantidade), ...]   (Produto = o SKU vendido, ex.: "A001_PR_G")
    # r.produtos  -> LISTA de Produto-SKU (um por item do pedido, sem repetir), com .imagens
    # Listas paralelas (mesmo índice = mesmo item): r.ids, r.nomes, r.precos,
    #   r.quantidades (pedidas), r.subtotais, r.imagens (lista de listas), r.estoques
    # Nos outros status essas listas vêm VAZIAS.
    # r.a_confirmar -> [(Produto, quantidade), ...] aguardando o "sim" (status "reperguntar");
    #                  nada foi descontado ainda
    # r.produto   -> só o primeiro Produto (mantido por compatibilidade)
    # Se r.status == "reperguntar", mande r.mensagem ao cliente e, quando ele
    # responder, chame est.processar(resposta, cliente=<mesmo cliente>).

Se faltar estoque de algum item, nada é descontado: o bot avisa o que acabou e
pergunta se o cliente quer só o que tem ("reperguntar", com r.itens = o que seria
separado). Se ele disser sim, separa; se disser não, devolve "cancelado".

Antes de descontar o estoque, o bot confirma o pedido ("Posso separar ...? Total:
R$ ... (sim/não)", status "reperguntar"; nada é descontado até o "sim"). Se o cliente
já respondeu "sim" a outra pergunta do bot, ele não pergunta de novo. Para desligar a
confirmação: Estoque("produtos.db", confirmar=False).

A frase é separada em itens por " e ", vírgula, ";", "+" e " mais ". Se algum
item não for entendido, nada é descontado: o bot confirma o que entendeu e
pergunta pelo resto ("pode repetir, ou vai comprar só esse mesmo?").

Variações (cor, tamanho...): o cliente procura pelo produto-base ("blusa") e COMPRA um SKU
("A001_PR_G" = Blusa preto G). O bot reconhece as opções citadas na frase ("blusa preta G") e, se
faltar alguma, pergunta ("Qual cor você prefere: verde ou preto?") antes de confirmar o pedido.

Código do carrinho (landing page): se o texto for uma lista, separada por vírgula, de
"quantidade em HEXADECIMAL + CÓDIGO DO SKU" (ex.: "2A001_PR_G,1A000_VE_M,AA001_VE_M" = 2x A001_PR_G,
1x A000_VE_M, 10x A001_VE_M), o pedido é separado direto, sem perguntar "Posso separar?": o código já
é a confirmação. Volta r.status "ok" com r.codigo = True. Se faltar estoque, cai no fluxo normal
("quer levar só o que tem?"). Se um item do código não existe mais, nada é vendido (status
"nao_encontrado"). O formato está todo em ProcessadorTexto._decodificar_codigo.

Banco de dados (SQLite, produtos_especializados.db, gerado pelo painel; modo "especializado"):
    produtos(id, nome, ativo, atualizado_em)                       produto-base
    skus(sku, produto_id, atributos JSON, preco, quantidade, ilimitado, ativo, atualizado_em)
    imagens(produto_id, ordem, url)  /  imagens_sku(sku, ordem, url)   (caminhos relativos à pasta do banco)
- O banco é a fonte da verdade do estoque. Preço e estoque são do SKU (o preço já inclui o acréscimo).
- Só produtos E SKUs com ativo = 1 entram na busca.
- ilimitado = 1 é estoque infinito (nunca é descontado).
- O catálogo fica em memória e é relido do banco SOMENTE quando o arquivo muda (data de
  modificação): se o painel alterar o estoque com o bot ligado, as mudanças valem na
  próxima mensagem, sem reiniciar.
- catalogo.db (opcional, mesma pasta) só fornece a categoria para distinguir produtos com o mesmo nome.
- O desconto é feito direto no banco, de forma atômica ("quantidade = quantidade - N" só se
  ainda houver N). Se o estoque mudou entre o "sim" do cliente e o desconto, nada é vendido.

Organização (uma responsabilidade por arquivo):
    modelos.py            Produto, Resposta, BancoInvalido
    constantes.py         status, vocabulário, limites e regex pré-compiladas
    utilidades.py         normalizar, juntar, reais
    repositorio.py        EstoqueRepository: todo o SQLite + cache do catálogo (produtos-base e SKUs)
    processador_texto.py  ProcessadorTexto: NLP e fuzzy matching
    comunicacao_com_estoque.py   Estoque: estado da conversa e regras do atendimento

Concorrência: cada cliente tem a sua própria trava; clientes diferentes não se bloqueiam.
O que é compartilhado (catálogo em memória e banco) é protegido pelo repositório e pelo SQL atômico.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict
from typing import Optional

from .constantes import (
    ARQ_ATRIBUTOS, ARQ_CONFIG, CANCELADO, DB_POR_MODO, ERRO, NAO_ENCONTRADO, OK, REPERGUNTAR,
    SEM_ESTOQUE, _CANCELAR, _NAO, _SIM, _SO_ESSE,
)
from .modelos import BancoInvalido, Produto, Resposta
from .processador_texto import ProcessadorTexto
from .repositorio import EstoqueRepository
from .utilidades import juntar, normalizar, preco_exibido, reais


class Estoque:
    def __init__(self, caminho: str, limite_direto: int = 85, margem: int = 5,
                 minimo: int = 60, max_tentativas: int = 2, confirmar: bool = True,
                 atributos: Optional[dict] = None, caminho_catalogo: Optional[str] = None,
                 base_imagens: Optional[str] = None, max_opcoes: int = 8):
        self.caminho = caminho
        self.nome_loja = ""   # preenchido por da_pasta()
        self._arq_config = ""   # config.json da loja (preenchido por da_pasta); é de onde sai o "orcamento"
        self._orc_mtime = None
        self._orc = False
        self.max_tentativas = max_tentativas  # quantas vezes pode reperguntar antes de desistir
        self.confirmar = confirmar          # True = pede "sim" do cliente antes de descontar o estoque
        self.repo = EstoqueRepository(caminho, caminho_catalogo, base_imagens)
        # limite_direto: nota a partir da qual o bot não precisa confirmar
        # margem: diferença mínima para o 1º colocado "ganhar" do 2º; minimo: abaixo disso nem é candidato
        self.texto = ProcessadorTexto(lambda: self.repo.catalogo, limite_direto, margem, minimo, atributos,
                                   max_opcoes=max_opcoes)
        self._pendentes: dict[str, dict] = {}  # conversa em andamento, por cliente
        # Uma trava por cliente (webhooks de clientes diferentes rodam em paralelo; as mensagens
        # do MESMO cliente continuam em fila). O defaultdict cria a trava na primeira vez, e a
        # trava-guarda evita que duas threads criem duas travas diferentes para o mesmo cliente.
        self._travas: defaultdict = defaultdict(threading.RLock)
        self._guarda_travas = threading.Lock()

    @classmethod
    def da_pasta(cls, pasta: str, **kw) -> "Estoque":
        """Monta o bot a partir da pasta de saída do painel: config.json (modo -> qual banco),
        atributos.json (rótulos e sinônimos das opções) e o banco do modo."""
        def ler(nome, obrigatorio):
            caminho = os.path.join(pasta, nome)
            if not os.path.exists(caminho):
                if obrigatorio:
                    raise BancoInvalido(f"não achei '{caminho}'.")
                return {}
            try:
                with open(caminho, encoding="utf-8") as f:
                    return json.load(f)
            except ValueError as e:
                raise BancoInvalido(f"'{caminho}' não é um JSON válido ({e}).") from e

        cfg = ler(ARQ_CONFIG, True)
        banco = DB_POR_MODO.get(cfg.get("modo"))
        if banco is None:
            raise BancoInvalido(f"modo '{cfg.get('modo')}' do {ARQ_CONFIG} não é suportado "
                                f"(suportados: {', '.join(DB_POR_MODO)}).")
        est = cls(os.path.join(pasta, banco), atributos=ler(ARQ_ATRIBUTOS, False), **kw)
        est.nome_loja = cfg.get("nome", "")
        est._arq_config = os.path.join(pasta, ARQ_CONFIG)
        return est

    @property
    def orcamento(self) -> bool:
        """Loja POR ORÇAMENTO (config.json da loja: "orcamento": true; vale para a loja inteira, não por item).
        O bot não mostra preços ("a combinar"), pede o endereço e a comanda fecha com a visita no lugar do PIX.
        Relê o arquivo só quando ele muda (mtime), então ligar/desligar no catálogo vale sem reiniciar o bot."""
        if not self._arq_config:
            return self._orc
        try:
            mtime = os.stat(self._arq_config).st_mtime_ns
            if mtime != self._orc_mtime:
                with open(self._arq_config, encoding="utf-8") as f:
                    dados = json.load(f)
                self._orc = bool(isinstance(dados, dict) and dados.get("orcamento"))
                self._orc_mtime = mtime
        except (OSError, ValueError):
            pass   # arquivo sumiu ou está sendo gravado: mantém o último valor conhecido
        return self._orc

    def _preco_entre_parenteses(self, p) -> str:
        """' (R$ 10,00)' para o cliente; vazio na loja por orçamento (preço nunca aparece)."""
        return "" if self.orcamento else f" ({preco_exibido(p)})"

    def _preco_apos_traco(self, p) -> str:
        """' — R$ 10,00' para o cliente; vazio na loja por orçamento."""
        return "" if self.orcamento else f" — {preco_exibido(p)}"

    def _trava_do(self, cliente: str):
        with self._guarda_travas:
            return self._travas[cliente]

    # ----- atalhos de compatibilidade (API antiga) -----
    @property
    def produtos(self) -> list:
        return self.repo.produtos

    @property
    def por_id(self) -> dict:
        return self.repo.por_id

    def buscar(self, texto: str, n: int = 3):
        return self.texto.buscar(texto, n)

    # ================= entrada principal =================
    def parece_codigo(self, texto: str) -> bool:
        """True se o texto é um código do carrinho válido (ao menos um item reconhecido)."""
        try:
            self.repo.atualizar()
        except BancoInvalido:
            return False
        return self.texto.parece_codigo(texto)

    def tem_pendencia(self, cliente: str) -> bool:
        """True se o bot está esperando uma resposta desse cliente (confirmação, escolha de opção...)."""
        with self._trava_do(cliente):
            return cliente in self._pendentes

    def processar(self, texto: str, cliente: str = "default", qtd: Optional[int] = None) -> Resposta:
        """Thread-safe: conversas simultâneas de clientes diferentes não se bloqueiam nem se misturam."""
        with self._trava_do(cliente):
            return self._processar(texto, cliente, qtd)

    def _processar(self, texto: str, cliente: str = "default", qtd: Optional[int] = None) -> Resposta:
        """Recebe o texto do cliente e devolve uma Resposta.

        Se houver uma pergunta pendente para esse cliente, o texto é tratado
        como a resposta a ela; se não resolver, vira uma nova busca.
        """
        texto = (texto or "").strip()
        try:
            self.repo.atualizar()   # catálogo e estoque atuais; só relê o banco se o arquivo mudou
        except BancoInvalido:
            logging.exception("não consegui ler o catálogo no banco '%s'", self.caminho)
            return Resposta(ERRO, "Estou com um problema no sistema agora. Tente de novo em instantes.")
        codigo = self.texto._decodificar_codigo(texto)   # código da landing page tem prioridade sobre qualquer pergunta pendente
        if codigo is not None:
            return self._processar_codigo(cliente, *codigo)
        pend = self._pendentes.get(cliente)
        if pend and pend.get("confirmar"):
            return self._continuar_confirmacao(texto, cliente, pend)
        if pend and pend.get("parcial"):
            return self._continuar_parcial(texto, cliente, pend)
        if pend and pend.get("variacao"):
            return self._continuar_variacao(texto, cliente, pend)
        if pend and pend.get("multi"):
            return self._continuar_multi(texto, cliente, pend)
        if pend:
            resp = self._responder_pergunta(texto, cliente, pend)
            if resp:
                return resp
            self._pendentes.pop(cliente, None)  # não era resposta: nova busca
            return self._entrada_nova(texto, cliente, qtd, pend["qtd"], pend["tentativas"])
        return self._entrada_nova(texto, cliente, qtd, 1, 0)

    def _processar_codigo(self, cliente, itens, invalidos) -> Resposta:
        """O código É a confirmação do cliente (ele montou o carrinho na página): não pergunta
        'Posso separar?'. Se faltar estoque, o fluxo normal assume e pergunta se leva só o que tem."""
        self._pendentes.pop(cliente, None)
        if invalidos:   # nada é vendido com código quebrado
            citados = ", ".join(f'"{t}"' for t in invalidos)
            return Resposta(NAO_ENCONTRADO, f"Não consegui validar o seu código: {citados} não existe mais no "
                            "catálogo. Gere um novo código na página ou me diga o que você quer.")
        r = self._vender_varios(itens, cliente, confirmado=True)
        if r.status == OK:
            r.codigo = True
        return r

    def _entrada_nova(self, texto, cliente, qtd_arg, qtd_padrao, tentativas) -> Resposta:
        partes = self.texto._dividir(texto)
        if len(partes) > 1 and qtd_arg is None:
            return self._processar_itens(partes, cliente, [], tentativas)
        return self._nova_busca(texto, cliente, qtd_arg, qtd_padrao, tentativas)

    def _nova_busca(self, texto, cliente, qtd_arg, qtd_padrao, tentativas) -> Resposta:
        tipo, alvo, qtd, consulta = self.texto._classificar(texto, qtd_arg, qtd_padrao)
        if tipo == "ok":
            return self._vender_base(alvo, qtd, consulta, cliente)
        if tipo == "nada":
            return self._reperguntar(cliente, [], qtd, tentativas, "Não encontrei esse produto.", consulta)
        return self._reperguntar(cliente, alvo, qtd, tentativas, "", consulta)

    # ================= variação (qual SKU do produto-base) =================
    def _vender_base(self, base, qtd, consulta, cliente, confirmado: bool = False) -> Resposta:
        """O cliente escolheu um produto-base: descobre o SKU pelo que ele escreveu ('blusa preta g')
        e, se faltar cor/tamanho, pergunta. Só SKUs chegam em _vender_varios."""
        sku, restantes, aviso = self.texto.resolver_variacao(base, consulta)
        if sku is not None:
            return self._vender_varios([(sku, qtd)], cliente, confirmado)
        return self._perguntar_variacao(cliente, restantes, qtd, 0, aviso)

    def _perguntar_variacao(self, cliente, opcoes, qtd, tentativas, prefixo="") -> Resposta:
        if tentativas >= self.max_tentativas:
            self._pendentes.pop(cliente, None)
            return Resposta(NAO_ENCONTRADO, "Não consegui identificar a variação do produto.")
        self._pendentes[cliente] = {"variacao": True, "opcoes": opcoes, "qtd": qtd,
                                    "tentativas": tentativas + 1}
        msg = f"{prefixo} {self.texto.pergunta_variacao(opcoes)}".strip()
        return Resposta(REPERGUNTAR, msg, opcoes=list(opcoes), quantidade=qtd)

    def _continuar_variacao(self, texto, cliente, pend) -> Resposta:
        """Resposta do cliente a 'Qual cor você prefere: verde ou preto?'."""
        n = normalizar(texto)
        tokens = n.split()
        opcoes, qtd = pend["opcoes"], pend["qtd"]
        restantes = self.texto.filtrar_variacoes(opcoes, n)
        if not restantes:   # citou uma combinação que não existe
            return self._perguntar_variacao(cliente, opcoes, qtd, pend["tentativas"],
                                            "Não temos essa combinação.")
        if len(restantes) == 1:
            return self._vender_varios([(restantes[0], qtd)], cliente)
        if len(restantes) < len(opcoes):   # avançou: pergunta o que ainda falta
            return self._perguntar_variacao(cliente, restantes, qtd, 0)
        if tokens and (tokens[0] in _NAO or tokens[0] in _CANCELAR):
            self._pendentes.pop(cliente, None)
            return Resposta(CANCELADO, "Tudo bem, não separei nada. Se quiser outra coisa, é só pedir.")
        if not self.texto.buscar(n, n=1):   # nem parece outro produto: foi uma opção que não existe
            return self._perguntar_variacao(cliente, opcoes, qtd, pend["tentativas"], "Não temos essa opção.")
        self._pendentes.pop(cliente, None)  # parece outro pedido: tratar como pedido novo
        return self._entrada_nova(texto, cliente, None, qtd, pend["tentativas"])

    # ================= repergunta (item único) =================
    def _reperguntar(self, cliente, opcoes, qtd, tentativas, prefixo, consulta="") -> Resposta:
        if tentativas >= self.max_tentativas:
            self._pendentes.pop(cliente, None)
            return Resposta(NAO_ENCONTRADO, "Não consegui identificar o produto.")
        self._pendentes[cliente] = {"opcoes": opcoes, "qtd": qtd, "tentativas": tentativas + 1,
                                    "consulta": consulta}
        if not opcoes:
            msg = f"{prefixo} Pode escrever o nome do produto de outro jeito?".strip()
        elif len(opcoes) == 1:
            p = opcoes[0]
            msg = f"Você quis dizer {p.nome}{self._preco_entre_parenteses(p)}? (sim/não)"
        else:
            linhas = [f"{i}) {p.nome}{self._preco_apos_traco(p)}" for i, p in enumerate(opcoes, 1)]
            dica = (" Se não for nenhum, escreva o nome do modelo." if len(opcoes) >= self.texto.max_opcoes
                    else "")
            msg = ("Encontrei mais de um produto parecido:\n" + "\n".join(linhas)
                   + "\nQual deles? (responda com o número, o nome ou uma palavra que o diferencie)" + dica)
        return Resposta(REPERGUNTAR, msg, opcoes=list(opcoes), quantidade=qtd)

    def _responder_pergunta(self, texto, cliente, pend) -> Optional[Resposta]:
        """Resolve a resposta do cliente; None se não for resposta à pergunta."""
        opcoes, qtd = pend["opcoes"], pend["qtd"]
        if not opcoes:
            return None  # pergunta aberta ("escreva de outro jeito"): é nova busca
        esc = self.texto._escolher(normalizar(texto), opcoes)
        if isinstance(esc, Produto):
            # "sim" a "você quis dizer X?" já é a confirmação; escolher numa lista não é
            return self._vender_base(esc, qtd, pend.get("consulta", ""), cliente,
                                     confirmado=len(opcoes) == 1)
        if esc is False:
            self._pendentes.pop(cliente, None)
            return self._reperguntar(cliente, [], qtd, pend["tentativas"], "Tudo bem.")
        # "nike", "de lã": não escolheu um só, mas pode ter reduzido a lista
        resto = self.texto.estreitar(texto and normalizar(texto), opcoes)
        if 0 < len(resto) < len(opcoes):
            if len(resto) == 1:
                return self._vender_base(resto[0], qtd, pend.get("consulta", ""), cliente)
            return self._reperguntar(cliente, resto, qtd, 0, "", pend.get("consulta", ""))
        return None

    # ================= vários itens na mesma frase =================
    def _processar_itens(self, partes, cliente, entendidos, tentativas) -> Resposta:
        problemas = []
        for seg in partes:
            tipo, alvo, qtd, consulta = self.texto._classificar(seg)
            if tipo == "ok":
                sku, restantes, _ = self.texto.resolver_variacao(alvo, consulta)
                if sku is not None:
                    entendidos.append((sku, qtd))
                else:   # produto certo, falta cor/tamanho: vira uma pergunta
                    problemas.append({"texto": consulta, "qtd": qtd, "opcoes": restantes, "variacao": True})
            else:
                problemas.append({"texto": consulta, "qtd": qtd, "opcoes": alvo})
        return self._decidir_multi(cliente, entendidos, problemas, tentativas)

    def _decidir_multi(self, cliente, entendidos, problemas, tentativas, confirmado=False) -> Resposta:
        if not problemas:
            return self._vender_varios(entendidos, cliente, confirmado)
        problemas = sorted(problemas, key=lambda pr: not pr["opcoes"])  # dúvidas primeiro (estável)
        if tentativas >= self.max_tentativas:
            return self._desistir(cliente, entendidos, problemas)
        self._pendentes[cliente] = {"multi": True, "entendidos": list(entendidos),
                                    "problemas": problemas, "tentativas": tentativas + 1}
        return Resposta(REPERGUNTAR, self._msg_multi(entendidos, problemas),
                        produto=entendidos[0][0] if entendidos else None,
                        a_confirmar=list(entendidos))

    def _desistir(self, cliente, entendidos, problemas) -> Resposta:
        """Estourou as tentativas. Se já havia itens entendidos, não joga fora o pedido:
        oferece ficar só com eles (e pede o "sim" antes de descontar)."""
        self._pendentes.pop(cliente, None)
        if not entendidos:
            return Resposta(NAO_ENCONTRADO, "Não consegui entender todos os itens do pedido.")
        citados = ", ".join(f'"{pr["texto"]}"' for pr in problemas)
        aviso = f"Não consegui entender {citados}, então ficamos só com o que entendi."
        return self._vender_varios(entendidos, cliente, exigir=True, aviso=aviso)

    def _msg_multi(self, entendidos, problemas) -> str:
        citados = ", ".join(f'"{pr["texto"]}"' for pr in problemas)
        duvidas = [pr for pr in problemas if pr["opcoes"]]
        linhas = []
        if entendidos:
            resumo = juntar([f"{q}x {p.nome}" for p, q in entendidos])
            ref = "o outro item" if len(problemas) == 1 else "os outros itens"
            verbo = "não entendi" if len(duvidas) < len(problemas) else "não tenho certeza sobre"
            linhas.append(f"Entendi, você quer {resumo}, mas {verbo} {ref} ({citados}).")
        else:
            linhas.append(f"Não entendi o pedido ({citados}).")
        for pr in duvidas[:1]:  # uma dúvida por vez; as outras vêm depois de resolver esta
            if pr.get("variacao"):
                linhas.append(f'Sobre "{pr["texto"]}": {self.texto.pergunta_variacao(pr["opcoes"])}')
            elif len(pr["opcoes"]) == 1:
                p = pr["opcoes"][0]
                linhas.append(f'Sobre "{pr["texto"]}": você quis dizer {p.nome}{self._preco_entre_parenteses(p)}? (sim/não)')
            else:
                ops = "; ".join(f"{i}) {p.nome}{self._preco_entre_parenteses(p)}" for i, p in enumerate(pr["opcoes"], 1))
                linhas.append(f'Sobre "{pr["texto"]}": {ops}. Qual deles?')
        if entendidos:
            esse = "esse" if len(entendidos) == 1 and entendidos[0][1] == 1 else "esses"
            pedido = "Responda a pergunta ou repita o item" if duvidas else "Pode repetir"
            linhas.append(f"{pedido}, ou vai comprar só {esse} mesmo?")
        else:
            linhas.append("Responda a pergunta ou repita o pedido." if duvidas else "Pode repetir?")
        return "\n".join(linhas)

    def _continuar_multi(self, texto, cliente, pend) -> Resposta:
        entendidos, problemas = pend["entendidos"], pend["problemas"]
        n = normalizar(texto)
        tokens = n.split()
        # 1) "só esse mesmo": fecha com o que foi entendido
        if entendidos and tokens and tokens[0] in _SO_ESSE:
            return self._vender_varios(entendidos, cliente, confirmado=True)
        # 2) a resposta é sobre as opções da primeira dúvida (as dúvidas vêm primeiro)
        pr = problemas[0]
        if pr["opcoes"]:
            resto = problemas[1:]
            if pr.get("variacao"):   # as opções são SKUs do mesmo produto: a resposta é "preta", "g"...
                restantes = self.texto.filtrar_variacoes(pr["opcoes"], n)
                if len(restantes) == 1:
                    return self._decidir_multi(cliente, entendidos + [(restantes[0], pr["qtd"])], resto, 0)
                if 1 < len(restantes) < len(pr["opcoes"]):   # avançou: pergunta o que ainda falta
                    return self._decidir_multi(cliente, entendidos, [{**pr, "opcoes": restantes}] + resto, 0)
                esc = None
            else:
                esc = self.texto._escolher(n, pr["opcoes"])
                if esc is None:   # "nike": não escolheu um só, mas pode ter reduzido a lista
                    reduz = self.texto.estreitar(n, pr["opcoes"])
                    if len(reduz) == 1:
                        esc = reduz[0]
                    elif 1 < len(reduz) < len(pr["opcoes"]):
                        return self._decidir_multi(cliente, entendidos, [{**pr, "opcoes": reduz}] + resto, 0)
            if isinstance(esc, Produto):  # resolveu o produto-base: ainda falta achar o SKU
                sku, restantes, _ = self.texto.resolver_variacao(esc, pr["texto"])
                if sku is None:
                    novo = {"texto": pr["texto"], "qtd": pr["qtd"], "opcoes": restantes, "variacao": True}
                    return self._decidir_multi(cliente, entendidos, [novo] + resto, 0)
                # "sim" a "você quis dizer X?" só dispensa a confirmação final se X é o único item
                return self._decidir_multi(cliente, entendidos + [(sku, pr["qtd"])], resto, 0,
                                           confirmado=len(pr["opcoes"]) == 1 and not entendidos)
            if esc is False:  # "não": esse item passa a ser "não entendido"
                return self._decidir_multi(cliente, entendidos, resto + [{**pr, "opcoes": []}],
                                           pend["tentativas"])
        # 3) "sim"/"isso" sem nenhuma sugestão pendente = "só esse mesmo"
        if entendidos and tokens and tokens[0] in _SIM and not any(pr["opcoes"] for pr in problemas):
            return self._vender_varios(entendidos, cliente, confirmado=True)
        # 4) a resposta repete os itens não entendidos
        partes = self.texto._dividir(texto)
        if len(partes) < len(problemas):
            if pend["tentativas"] >= self.max_tentativas:
                return self._desistir(cliente, entendidos, problemas)
            pend["tentativas"] += 1
            aviso = ("Não entendi sua resposta." if problemas[0]["opcoes"]
                     else "Faltou repetir todos os itens que não entendi.")
            return Resposta(REPERGUNTAR, aviso + "\n" + self._msg_multi(entendidos, problemas),
                            produto=entendidos[0][0] if entendidos else None, a_confirmar=list(entendidos))
        self._pendentes.pop(cliente, None)
        return self._processar_itens(partes, cliente, list(entendidos), pend["tentativas"])

    # ================= estoque =================
    def _vender_varios(self, itens, cliente: str, confirmado: bool = False,
                       exigir: bool = False, aviso: str = "") -> Resposta:
        """Só desconta o que o cliente confirmou. Se faltar estoque de algum item,
        não desconta nada: avisa e pergunta se ele quer só o que tem."""
        self._pendentes.pop(cliente, None)
        agregado: dict[str, list] = {}
        for p, q in itens:  # mesmo produto repetido na frase soma as quantidades
            agregado.setdefault(p.id, [p, 0])[1] += q
        pedidos = list(agregado.values())
        prefixo = aviso + " " if aviso else ""

        disponiveis, esgotados, parciais = [], [], []
        for p, q in pedidos:
            if p.ilimitado or q <= p.quantidade:
                disponiveis.append((p, q))
            elif p.quantidade <= 0:
                esgotados.append(p)
            else:  # tem, mas menos do que o pedido
                parciais.append((p, p.quantidade))
                disponiveis.append((p, p.quantidade))

        if esgotados or parciais:
            avisos = []
            if esgotados:
                nomes = juntar([p.nome for p in esgotados])
                avisos.append(f"Infelizmente {nomes} " + ("acabou." if len(esgotados) == 1 else "acabaram."))
            for p, n in parciais:
                avisos.append(f"De {p.nome} temos apenas {n} unidade(s).")
            if not disponiveis:
                return Resposta(SEM_ESTOQUE, prefixo + " ".join(avisos) + " Nada foi reservado.", esgotados[0])
            resumo = juntar([f"{q}x {p.nome}" for p, q in disponiveis])
            total = sum(p.preco * q for p, q in disponiveis)
            quer = "só esse" if len(disponiveis) == 1 else "só esses"
            valor = "" if self.orcamento else f" ({reais(total)})"
            msg = prefixo + " ".join(avisos) + f" Quer levar {quer} mesmo: {resumo}{valor}? (sim/não)"
            self._pendentes[cliente] = {"parcial": True, "itens": list(disponiveis)}
            return Resposta(REPERGUNTAR, msg, disponiveis[0][0], a_confirmar=list(disponiveis))

        if (self.confirmar or exigir) and not confirmado:
            resumo = juntar([f"{q}x {p.nome}" for p, q in pedidos])
            total = sum(p.preco * q for p, q in pedidos)
            lista = [(p, q) for p, q in pedidos]
            self._pendentes[cliente] = {"confirmar": True, "itens": lista}
            valor = "" if self.orcamento else f" Total: {reais(total)}."
            msg = f"{prefixo}Posso separar {resumo}?{valor} (sim/não)"
            return Resposta(REPERGUNTAR, msg, lista[0][0], a_confirmar=list(lista))

        return self._baixar(pedidos)

    def _continuar_confirmacao(self, texto, cliente, pend) -> Resposta:
        """Resposta do cliente a 'Posso separar ...? (sim/não)'."""
        tokens = normalizar(texto).split()
        if tokens and tokens[0] in _SIM:
            return self._vender_varios(pend["itens"], cliente, confirmado=True)
        if tokens and (tokens[0] in _NAO or tokens[0] in _CANCELAR):
            self._pendentes.pop(cliente, None)
            return Resposta(CANCELADO, "Tudo bem, não separei nada. Se quiser alterar o pedido, é só me dizer.")
        self._pendentes.pop(cliente, None)  # não era resposta: tratar como pedido novo
        return self._entrada_nova(texto, cliente, None, 1, 0)

    def _continuar_parcial(self, texto, cliente, pend) -> Resposta:
        """Resposta do cliente a 'quer levar só os que temos?'."""
        tokens = normalizar(texto).split()
        if tokens and (tokens[0] in _SIM or tokens[0] in _SO_ESSE):
            return self._vender_varios(pend["itens"], cliente, confirmado=True)
        if tokens and (tokens[0] in _NAO or tokens[0] in _CANCELAR):
            self._pendentes.pop(cliente, None)
            return Resposta(CANCELADO, "Tudo bem, não separei nada. Se quiser outra coisa, é só pedir.")
        self._pendentes.pop(cliente, None)  # não era resposta: tratar como pedido novo
        return self._entrada_nova(texto, cliente, None, 1, 0)

    def _baixar(self, pedidos) -> Resposta:
        """Pede ao repositório o desconto (tudo ou nada) e monta a resposta ao cliente."""
        try:
            falhou = self.repo.baixar(pedidos)
        except BancoInvalido:
            logging.exception("NÃO consegui descontar o estoque no banco '%s' (pedido: %s)", self.caminho,
                              [(p.id, q) for p, q in pedidos])
            return Resposta(ERRO, "Não consegui registrar o pedido agora. Tente de novo em instantes.",
                            pedidos[0][0])
        if falhou is not None:   # acabou/mudou nesse meio tempo: nada foi descontado
            return Resposta(SEM_ESTOQUE, f"O estoque de {falhou.nome} mudou agora há pouco e não "
                            "consegui separar o pedido. Nada foi reservado; pode pedir de novo.", falhou)
        total = sum(p.preco * q for p, q in pedidos)
        if self.orcamento:   # loja por orçamento: sem preços para o cliente
            msg = "Separei " + juntar([f"{q}x {p.nome}" for p, q in pedidos]) + "."
        elif len(pedidos) == 1:
            p, q = pedidos[0]
            msg = f"Separei {q}x {p.nome}: {reais(p.preco * q)}."
        else:
            lista = juntar([f"{q}x {p.nome} ({reais(p.preco * q)})" for p, q in pedidos])
            msg = f"Separei {lista}. Total: {reais(total)}."
        return Resposta(OK, msg, pedidos[0][0], sum(q for _, q in pedidos), itens=[(p, q) for p, q in pedidos])

    def estornar(self, id_: str, qtd: int = 1) -> bool:
        """Devolve unidades de um SKU ao estoque (ex.: pagamento não confirmado; id_ = r.ids[i]).
        Para um pedido com vários itens, chame uma vez para cada (Produto, qtd) de r.itens."""
        return self.repo.estornar(id_, qtd)


if __name__ == "__main__":
    # Teste no terminal (na pasta raiz do bot):  python -m estoque.comunicacao_com_estoque [pasta_de_saida]
    # Digite como se fosse o cliente.
    # A conversa termina quando o bot dá uma resposta final (qualquer status que
    # não seja "reperguntar"). Linha vazia ou "sair" também encerra.
    import sys
    est = Estoque.da_pasta(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    while True:
        texto = input("cliente> ").strip()
        if not texto or normalizar(texto) == "sair":
            break
        r = est.processar(texto, cliente="5585999990000")
        print("bot>", r.mensagem)
        print("     status:", r.status)
        if r.status == "ok":  # só aqui os itens foram separados de verdade
            for i, nome in enumerate(r.nomes):
                print("     separado:", nome, r.quantidades[i], r.precos[i], r.imagens[i])
        elif r.a_confirmar:
            print("     aguardando confirmação:", [(p.nome, q) for p, q in r.a_confirmar])
        if r.status != "reperguntar":
            print("     (conversa encerrada)")
            break
