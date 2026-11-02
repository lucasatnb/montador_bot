"""Processamento de texto (NLP leve + fuzzy matching com rapidfuzz).

Não toca no banco nem guarda estado de conversa: recebe o texto do cliente e interpreta
(quantidade, itens, produto mais parecido, código do carrinho). O catálogo vem de uma função
`obter_catalogo()` (um snapshot consistente, ver repositorio.Catalogo), o que evita depender
do repositório e de imports circulares.
"""
from __future__ import annotations

from typing import Callable, Optional

from rapidfuzz import fuzz, process

from .constantes import (
    MAX_QTD_CODIGO, RE_DIVIDIR_E_MAIS, RE_ESPACO, RE_HEX, RE_HEX_MAIS_ALGO, RE_QTD_FIM,
    RE_QTD_INICIO, RE_SEPARADORES, _ABERTURA, _ENCHIMENTO, _LIGACAO, _NAO, _NEGACAO, _NUM_EXT,
    _ORDINAIS, _SIM, _UNIDADES,
)
from .modelos import Produto
from .utilidades import juntar_ou, normalizar, rotulo_opcao


class ProcessadorTexto:
    def __init__(self, obter_catalogo: Callable, limite_direto: int = 85, margem: int = 5,
                 minimo: int = 60, atributos: Optional[dict] = None, max_opcoes: int = 8,
                 faixa: int = 10):
        self._obter_catalogo = obter_catalogo
        self.limite_direto = limite_direto  # nota a partir da qual o bot não precisa confirmar
        self.margem = margem                # diferença mínima para o 1º colocado "ganhar" do 2º
        self.minimo = minimo                # abaixo disso nem é candidato
        self.max_opcoes = max_opcoes        # quantos produtos parecidos mostrar de uma vez ao cliente
        self.faixa = faixa                  # só entram na lista os que estão a até `faixa` pontos do 1º
        # atributos.json: {"tipos": {"cor": {"rotulo": "cor", "opcoes": {...}}, ...}, "sinonimos": {...}}
        atributos = atributos or {}
        tipos = atributos.get("tipos") or {}
        self._ordem_tipos = list(tipos)                                           # ordem das perguntas
        self._rotulos = {t: (info.get("rotulo") or t) for t, info in tipos.items()}  # "Qual {rótulo}?"
        self._sinonimos = self._ler_sinonimos(atributos.get("sinonimos") or {})

    @staticmethod
    def _ler_sinonimos(bruto: dict) -> dict:
        """{palavra normalizada: opção normalizada}. Aceita {"grande": "g"} ou {"tamanho": {"grande": "g"}}.
        (No output atual 'sinonimos' está vazio: este formato é uma suposição.)"""
        saida = {}
        for k, v in bruto.items():
            if isinstance(v, dict):
                saida.update({normalizar(pal): normalizar(op) for pal, op in v.items()})
            else:
                saida[normalizar(k)] = normalizar(v)
        return saida

    # ================= busca =================
    def buscar(self, texto: str, n: int = 3):
        """Até n (produto, nota 0-100), melhores primeiro."""
        consulta = normalizar(texto)
        if not consulta:
            return []
        cat = self._obter_catalogo()   # uma única referência: nomes e produtos do MESMO snapshot
        achados = process.extract(consulta, cat.nomes, scorer=fuzz.WRatio,
                                  limit=max(3 * n, 15), score_cutoff=self.minimo)
        pontos = self._penalizar(consulta, [(idx, nota) for _, nota, idx in achados], cat.nomes)
        pontos.sort(key=lambda x: -x[1])   # estável: empate mantém a ordem do catálogo
        return [(cat.produtos[idx], round(nota)) for idx, nota in pontos[:n]]

    # ---- palavras que distinguem produtos que começam igual ("tênis NIKE" x "tênis ADIDAS") ----
    @staticmethod
    def _bate(t: str, w: str) -> bool:
        """A palavra do cliente (t) é essa palavra do nome (w)? Aceita plural e erro de digitação
        em palavras longas; palavras curtas ('la', 'air') só valem exatas."""
        if t == w:
            return True
        if len(t) <= 3 or len(w) <= 3:
            return False
        return max(fuzz.ratio(t, w), fuzz.ratio(t.rstrip("s"), w.rstrip("s"))) >= 80

    @staticmethod
    def _significativas(consulta: str) -> list:
        """Palavras da frase que carregam informação (sem enchimento, número, sim/não)."""
        return [t for t in consulta.split()
                if len(t) >= 2 and not t.isdigit() and t not in _ENCHIMENTO and t not in _ABERTURA
                and t not in _NEGACAO and t not in _SIM and t not in _NAO]

    def _penalizar(self, consulta: str, pontos: list, nomes: list) -> list:
        """pontos = [(índice, nota)]. O fuzzy dá nota alta a quem só compartilha a 1ª palavra
        ('tenis nike' ~ 'tenis adidas'). Se o cliente citou uma palavra que OUTRO candidato tem e
        este não tem, este é o produto errado: perde pontos. Não dá bônus (o nome exato continua
        ganhando de 'Blusa Cropped' quando o cliente escreve só 'blusa')."""
        palavras = {idx: nomes[idx].split() for idx, _ in pontos}
        saida = []
        qs = self._significativas(consulta)
        tem = {q: {idx for idx, ws in palavras.items() if any(self._bate(q, w) for w in ws)} for q in qs}
        for idx, nota in pontos:
            pen = sum(15 for q in qs if tem[q] and idx not in tem[q])
            saida.append((idx, max(0, nota - min(pen, 30))))
        return saida

    def _explicadas(self, consulta: str, produto: Produto) -> set:
        """Palavras significativas da frase que aparecem no nome do produto."""
        ws = normalizar(produto.nome).split()
        return {q for q in self._significativas(consulta) if any(self._bate(q, w) for w in ws)}

    def estreitar(self, resposta: str, opcoes: list) -> list:
        """Resposta do cliente a uma lista de opções ('nike', 'de lã'): fica só com as opções
        cujo nome tem TODAS as palavras da resposta. Sem palavra útil na resposta, devolve todas."""
        qs = self._significativas(normalizar(resposta))
        if not qs:
            return list(opcoes)
        return [p for p in opcoes
                if all(any(self._bate(q, w) for w in normalizar(p.nome).split()) for q in qs)]

    @staticmethod
    def _extrair_qtd(texto: str):
        """Devolve (quantidade ou None, resto da frase). Entende:
        '40 blusas', 'me dê 40 blusas', '40x blusa', 'blusa x40', 'blusa 40 unidades',
        'quarenta blusas', 'duas camisetas', 'meia dúzia de camisetas', 'uma dúzia de blusas'.
        Número solto no FIM não conta ('tenis 42' é tamanho, não 42 unidades)."""
        t = normalizar(texto).split()
        while t and t[0] in _ABERTURA:
            t = t[1:]
        qtd = None
        if t and len(t) > 1:
            m = RE_QTD_INICIO.fullmatch(t[0])
            if m and int(m.group(1)) > 0:
                qtd, t = int(m.group(1)), t[1:]
            elif t[0] == "meia" and len(t) > 2 and t[1] in ("duzia", "duzias"):
                qtd, t = 6, t[2:]
            elif t[0] in _NUM_EXT:
                if t[1] in ("duzia", "duzias") and len(t) > 2:
                    qtd, t = _NUM_EXT[t[0]] * 12, t[2:]
                elif t[0] in ("um", "uma"):
                    t = t[1:]                       # artigo: 1 unidade
                else:
                    qtd, t = _NUM_EXT[t[0]], t[1:]
            if qtd is not None:
                while t and t[0] in _LIGACAO:
                    t = t[1:]
        if qtd is None and len(t) > 1:              # quantidade marcada no fim: 'blusa x40', 'blusa 40 un'
            m = RE_QTD_FIM.fullmatch(t[-1])
            if m and int(m.group(1) or m.group(2)) > 0:
                qtd, t = int(m.group(1) or m.group(2)), t[:-1]
            elif len(t) > 2 and t[-1] in _UNIDADES and t[-2].isdigit() and int(t[-2]) > 0:
                qtd, t = int(t[-2]), t[:-2]
        return qtd, " ".join(t)

    def _dividir(self, texto: str) -> list:
        """Separa a frase em itens: ' e ', vírgula, ';', '+', ' mais '.
        Nomes de produto que têm ' e ' (ex.: 'Bolsa e Mochila') são protegidos."""
        cat = self._obter_catalogo()
        bruto = RE_SEPARADORES.sub(" e ", str(texto))
        n = normalizar(bruto)
        protegidos = {}
        for i, nome in cat.nomes_com_conectivo:   # só os nomes que realmente têm " e "/" mais "
            if nome in n:
                marca = f"zzprot{i}zz"
                n = n.replace(nome, marca)
                protegidos[marca] = nome
        partes = RE_DIVIDIR_E_MAIS.split(n)
        saida = []
        for parte in partes:
            for marca, nome in protegidos.items():
                parte = parte.replace(marca, nome)
            parte = parte.strip()
            if parte and parte not in ("e", "mais"):
                saida.append(parte)
        return saida

    def _sobra(self, consulta: str, produto: Produto) -> list:
        """Palavras da frase que não se explicam: não são do nome do produto, nem das opções dos
        atributos (cor, tamanho...), nem enchimento comum, nem número/sigla curta.
        Ex.: 'ksyfg tenis' -> ['ksyfg']; 'nao quero tenis' -> ['nao'].
        Se sobrar alguma, o bot não separa direto: pergunta 'você quis dizer X?'."""
        palavras_nome = set(normalizar(produto.nome).split()) | set(self._sinonimos)
        for v in produto.variacoes:
            for valor in v.atributos.values():
                palavras_nome.update(normalizar(valor).split())
        sobra = []
        for t in consulta.split():
            if t in _NEGACAO:
                sobra.append(t)
            elif t in _ENCHIMENTO or t.isdigit() or len(t) <= 3:
                continue
            elif any(fuzz.ratio(t, w) >= 70 for w in palavras_nome):  # aceita erro de digitação e plural
                continue
            else:
                sobra.append(t)
        return sobra

    def _classificar(self, seg: str, qtd_arg: Optional[int] = None, qtd_padrao: int = 1):
        """('ok', produto, qtd, consulta) | ('duvida', [opcoes], qtd, consulta)
        | ('nada', [], qtd, consulta)."""
        q_txt, consulta = self._extrair_qtd(seg)
        qtd = qtd_arg or q_txt or qtd_padrao
        achados = self.buscar(consulta, n=self.max_opcoes)
        if not achados:
            return "nada", [], qtd, consulta
        top = achados[0]
        if top[1] >= self.limite_direto and (len(achados) == 1 or top[1] - achados[1][1] >= self.margem):
            if self._sobra(consulta, top[0]):  # tem texto que não se explica: confirmar antes
                return "duvida", [top[0]], qtd, consulta
            return "ok", top[0], qtd, consulta
        # Lista de dúvida: quem está perto da nota do 1º OU explica as mesmas palavras que ele
        # ('tenis azul': 'azul' é ruído, todos os tênis entram, nenhum fica escondido por nota).
        base = self._explicadas(consulta, top[0])
        opcoes = [p for p, nota in achados
                  if nota >= top[1] - self.faixa or (base and base <= self._explicadas(consulta, p))]
        ordem = {p.id: i for i, p in enumerate(self._obter_catalogo().produtos)}
        opcoes.sort(key=lambda p: ordem.get(p.id, 0))   # numeração estável: sempre a ordem do catálogo
        return "duvida", opcoes, qtd, consulta

    def _escolher(self, n: str, opcoes: list):
        """Interpreta a resposta do cliente (já normalizada) entre as opções.
        Devolve Produto (escolheu), False (disse não/nenhum) ou None (não deu para entender)."""
        tokens = n.split()
        if not tokens:
            return None
        if len(opcoes) == 1:
            if tokens[0] in _SIM:
                return opcoes[0]
            if tokens[0] in _NAO:
                return False
            return None
        if len(tokens) <= 3:  # "2", "o 2", "a segunda"
            for t in tokens:
                num = int(t) if t.isdigit() else _ORDINAIS.get(t)
                if num and 1 <= num <= len(opcoes):
                    return opcoes[num - 1]
        r = process.extract(n, [normalizar(p.nome) for p in opcoes],
                            scorer=fuzz.WRatio, limit=2, score_cutoff=70)
        if r and (len(r) == 1 or r[0][1] - r[1][1] >= self.margem):
            return opcoes[r[0][2]]
        if tokens[0] in _NAO:
            return False
        return None

    # ================= variações (SKUs: cor, tamanho...) =================
    def _tipos(self, skus: list) -> list:
        """Tipos de atributo presentes nos SKUs, na ordem do atributos.json (os demais, depois)."""
        presentes = list(dict.fromkeys(t for s in skus for t in s.atributos))
        return ([t for t in self._ordem_tipos if t in presentes]
                + [t for t in presentes if t not in self._ordem_tipos])

    @staticmethod
    def _valores(skus: list, tipo: str) -> list:
        """Opções distintas de um tipo, na ordem em que aparecem nos SKUs."""
        return list(dict.fromkeys(s.atributos[tipo] for s in skus if tipo in s.atributos))

    def _cita(self, texto: str, valor) -> bool:
        """O texto (normalizado) cita essa opção? Aceita plural e erro de digitação em palavras
        longas ('pretas' -> 'preto'); siglas curtas ('m', 'g') só valem exatas."""
        v = normalizar(valor)
        if not v:
            return False
        if f" {v} " in f" {texto} ":
            return True
        tokens = texto.split()
        if len(v) > 3 and " " not in v and any(
                len(t) > 3 and max(fuzz.ratio(t, v), fuzz.ratio(t.rstrip("s"), v)) >= 80 for t in tokens):
            return True
        return any(self._sinonimos.get(t) == v for t in tokens)

    def filtrar_variacoes(self, skus: list, texto: str) -> list:
        """SKUs que combinam com as opções citadas no texto (uma por tipo). Se nada foi citado,
        devolve todos; se o que foi citado não existe em combinação ([]), devolve lista vazia."""
        n = normalizar(texto)
        restantes = list(skus)
        for tipo in self._tipos(skus):
            citados = [v for v in self._valores(skus, tipo) if self._cita(n, v)]
            if len(citados) == 1:   # citou duas opções do mesmo tipo = outro item (a frase já foi dividida)
                restantes = [s for s in restantes if s.atributos.get(tipo) == citados[0]]
        return restantes

    def resolver_variacao(self, base: Produto, consulta: str):
        """Descobre qual SKU do produto-base o cliente quer, a partir do texto da busca.
        Devolve (sku, [sku], "") se está definido; (None, restantes, "") se falta perguntar;
        (None, todos os SKUs, aviso) se a combinação pedida não existe."""
        restantes = self.filtrar_variacoes(base.variacoes, consulta)
        if len(restantes) == 1:
            return restantes[0], restantes, ""
        if not restantes:
            return None, list(base.variacoes), f"Não temos {base.nome} nessa combinação."
        return None, restantes, ""

    def pergunta_variacao(self, skus: list) -> str:
        """Pergunta o PRIMEIRO atributo que ainda não está definido. Ex.: 'Qual cor você prefere: verde ou preto?'"""
        for tipo in self._tipos(skus):
            valores = self._valores(skus, tipo)
            if len(valores) > 1:
                rotulo = self._rotulos.get(tipo, tipo)
                return f"Qual {rotulo} você prefere: {juntar_ou([rotulo_opcao(v) for v in valores])}?"
        return ""

    # ================= código do carrinho (landing page) =================
    def _decodificar_codigo(self, texto):
        """Código do carrinho: itens separados por vírgula, cada item = QUANTIDADE EM HEXADECIMAL
        colada no CÓDIGO DO SKU, sem espaço. Ex.: '2A001_PR_G,1A000_VE_M, AA001_VE_M' = 2x A001_PR_G,
        1x A000_VE_M, 10x A001_VE_M. (hex: A=10, F=15, 10=16.) O SKU é procurado no catálogo, então
        códigos que começam com letra/número de hexadecimal (ex.: 'A001_PR_G') funcionam, desde que a
        leitura não fique ambígua.
        Devolve None (não é um código: segue como conversa normal) ou (itens, invalidos), onde
        itens = [(Produto, qtd)] e invalidos = pedaços que têm cara de código mas não casam
        com um produto ativo (ou casam de duas formas)."""
        tokens = [t for t in (x.strip() for x in str(texto).split(",")) if t]
        if not tokens or any(RE_ESPACO.search(t) for t in tokens):
            return None   # texto normal ("2 camisetas, 1 boné"): cada pedaço tem espaço
        por_id = self._obter_catalogo().ids_casefold
        itens, invalidos = [], []
        for t in tokens:
            candidatos = []
            for i in range(1, len(t)):
                if not RE_HEX.fullmatch(t[:i]):
                    break   # a quantidade (hex) acabou
                q = int(t[:i], 16)
                if 1 <= q <= MAX_QTD_CODIGO:
                    candidatos += [(p, q) for p in por_id.get(t[i:].casefold(), [])]
            if len(candidatos) == 1:
                itens.append(candidatos[0])
            elif RE_HEX_MAIS_ALGO.fullmatch(t):
                invalidos.append(t)   # parece "hex + algo", mas não é um produto (ou é ambíguo)
            else:
                return None           # tem pedaço que nem parece código: é conversa normal
        return (itens, invalidos) if itens else None

    def parece_codigo(self, texto: str) -> bool:
        """True se o texto é um código do carrinho válido (ao menos um item reconhecido)."""
        return self._decodificar_codigo(texto) is not None
