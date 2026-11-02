"""Constantes do bot de estoque: status, vocabulário, limites e regex pré-compiladas.

Todas as expressões regulares são compiladas UMA vez, aqui, na importação do módulo;
o resto do código só usa os objetos prontos (RE_*). Não importa nenhum módulo do projeto.
"""
import re

# ---------------- status das respostas ----------------
OK = "ok"
REPERGUNTAR = "reperguntar"
SEM_ESTOQUE = "sem_estoque"
NAO_ENCONTRADO = "nao_encontrado"
CANCELADO = "cancelado"
ERRO = "erro"

# ---------------- textos fixos ----------------
# Resposta quando não há loja configurada, o banco ainda não existe ou o catálogo está vazio.
TEXTO_SEM_PRODUTOS = "Ainda não temos produtos disponíveis por aqui. Tente de novo mais tarde."

# ---------------- vocabulário ----------------
_SIM = {"sim", "s", "isso", "esse", "ok", "pode", "claro", "confirmo", "exato", "correto"}
_NAO = {"nao", "n", "nenhum", "nenhuma", "errado", "outro"}
_SO_ESSE = {"so", "somente", "apenas", "esquece", "deixa"}   # "só esse mesmo"
_CANCELAR = {"cancela", "cancelar", "cancelado"}
# Palavras que o cliente costuma escrever junto do produto e que não indicam outro item.
_ENCHIMENTO = {"quero", "queria", "gostaria", "preciso", "vou", "levar", "me", "ve", "manda",
               "separa", "separe", "de", "do", "da", "dos", "das", "um", "uma", "uns", "umas",
               "por", "favor", "pfv", "pra", "para", "tambem", "tb", "eu", "que", "esse", "essa",
               "aquele", "aquela", "tipo", "oi", "ola", "bom", "boa", "dia", "tarde", "noite",
               "obrigado", "obrigada", "obg", "valeu", "unidade", "unidades", "tamanho", "tam",
               "cor", "mais", "e"}
_NEGACAO = {"nao", "nem", "sem", "nunca", "jamais"}   # "não quero tênis" nunca é pedido de tênis
_ORDINAIS = {"primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3}
# Palavras que o cliente escreve ANTES da quantidade/produto ("quero", "me dê", "pode me mandar"...).
_ABERTURA = {"oi", "ola", "opa", "eai", "bom", "boa", "dia", "tarde", "noite", "tudo", "bem",
             "eu", "pode", "poderia", "podia", "vou", "vai", "me", "mim", "pra", "para", "e", "mais",
             "tambem", "tb", "quero", "queria", "querer", "gostaria", "preciso", "precisava",
             "de", "da", "dar", "ve", "manda", "mande", "separa", "separe", "coloca", "colocar",
             "poe", "adiciona", "adicionar", "inclui", "incluir", "traz", "trazer", "mandar", "enviar",
             "separar", "ver", "vender", "arrumar", "pegar", "levar", "comprar"}
_NUM_EXT = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
            "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
            "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
            "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
            "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
            "cem": 100, "cento": 100}
_UNIDADES = {"x", "un", "und", "unid", "unids", "unidade", "unidades", "peca", "pecas", "pc", "pcs"}
_LIGACAO = _UNIDADES | {"de", "do", "da", "dos", "das"}   # "40 de blusas", "40 unidades de blusa"

# ---------------- arquivos da pasta de saída do painel ----------------
ARQ_CONFIG = "config.json"
ARQ_ATRIBUTOS = "atributos.json"
ARQ_CATALOGO = "catalogo.db"   # só lido (opcional): dá a categoria para distinguir produtos com o mesmo nome
# config.json -> "modo": qual banco guarda o estoque desse modo
DB_POR_MODO = {"especializado": "produtos_especializados.db"}

# ---------------- limites ----------------
MAX_QTD_CODIGO = 999   # maior quantidade aceita por item num código do carrinho (trava contra código errado)

# Cache do catálogo: se o arquivo do banco foi modificado há menos que isso (segundos), o
# catálogo é relido mesmo que a data de modificação pareça igual à da última leitura.
# Protege contra relógios de arquivo com resolução grossa (duas escritas no mesmo "tick").
JANELA_RELEITURA_S = 2.0

# ---------------- regex pré-compiladas ----------------
RE_NAO_ALFANUM = re.compile(r"[^a-z0-9\s]")        # normalizar(): tira pontuação
RE_SEPARADORES = re.compile(r"[,;+\n]")            # _dividir(): vírgula, ';', '+', quebra de linha
RE_E_MAIS_PALAVRA = re.compile(r"\b(?:e|mais)\b")  # nome de produto que contém " e " / " mais "
RE_DIVIDIR_E_MAIS = re.compile(r"\s+(?:e|mais)\s+")  # _dividir(): separa itens em " e " / " mais "
RE_QTD_INICIO = re.compile(r"x?(\d{1,3})x?")       # '40', 'x40', '40x' no começo da frase
RE_QTD_FIM = re.compile(r"x(\d{1,3})|(\d{1,3})x")  # 'blusa x40', 'blusa 40x' no fim da frase
RE_ESPACO = re.compile(r"\s")                      # _decodificar_codigo(): código não tem espaço
RE_HEX = re.compile(r"[0-9a-fA-F]+")               # quantidade em hexadecimal do código
RE_HEX_MAIS_ALGO = re.compile(r"[0-9a-fA-F]+\S+")  # "parece código": hex colado em algo
