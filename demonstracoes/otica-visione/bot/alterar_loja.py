"""alterar_loja.py -- mudança SIMPLES na loja do bot: preço, nome, descrição e categoria.

    alterar_loja.bat           (ou:  python alterar_loja.py)

Só biblioteca padrão do Python, sem telas: abre, pergunta, grava e fecha (não pesa no computador).
Quantidade, ilimitado e ativo continuam no painel (abrir_painel.bat). Para mexer em variações, fotos ou
cadastrar produto novo, monte o bot de novo pelo montador (o catálogo fica lá).

Pode ser usado com o bot ligado: cada gravação é uma transação curta (BEGIN IMMEDIATE), a mesma trava do bot.
O bot e o painel percebem a mudança sozinhos (eles relêem o banco quando o arquivo muda).
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PASTA_BOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_BOT))

BANCO = "produtos_especializados.db"   # o único modo que o bot suporta (estoque/constantes.py: DB_POR_MODO)
CATALOGO = "catalogo.db"
CAMPOS_TEXTO = {"descricao": "descrição", "categoria": "categoria"}


class ErroLoja(Exception):
    """Algo que a pessoa resolve; a mensagem já está em linguagem simples."""


def pasta_loja() -> Path:
    try:
        import bot_config
        bruto = bot_config.pasta_loja()
    except Exception:
        bruto = ""
    return Path(os.environ.get("BOT_PASTA_ESTOQUE") or bruto or PASTA_BOT / "loja")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conectar(caminho: Path) -> sqlite3.Connection:
    if not caminho.is_file():
        raise ErroLoja(f"Não achei '{caminho.name}' em {caminho.parent}.")
    con = sqlite3.connect(str(caminho), timeout=10, isolation_level=None)   # transações manuais
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _executar(caminho: Path, instrucoes) -> None:
    """Roda várias instruções numa transação só: ou grava tudo ou nada."""
    con = _conectar(caminho)
    try:
        con.execute("BEGIN IMMEDIATE")
        for sql, params in instrucoes:
            con.execute(sql, params)
        con.execute("COMMIT")
    except sqlite3.Error as e:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise ErroLoja(f"Não consegui gravar ({e}). O arquivo está aberto em outro programa?") from e
    finally:
        con.close()


def _ler(caminho: Path, sql: str, params=()) -> list:
    con = _conectar(caminho)
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.Error as e:
        raise ErroLoja(f"Não consegui ler '{caminho.name}' ({e}).") from e
    finally:
        con.close()


def numero(texto) -> float:
    """'12,50' / 'R$ 1.299,90' / '12.5' -> float (não negativo)."""
    t = str(texto).replace("R$", "").replace(" ", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        valor = float(t)
    except ValueError:
        raise ErroLoja(f"'{texto}' não é um preço. Use, por exemplo, 12,50.") from None
    if valor < 0 or valor != valor or valor == float("inf"):
        raise ErroLoja("O preço não pode ser negativo.")
    return round(valor, 2)


def _id(texto) -> str:
    return str(texto or "").strip().upper()


# ------------------------------------------------------------------ o que dá para fazer
def listar(pasta: Path) -> list:
    """[(produto_id, nome, sku, variação, preço, ativo)] só dos produtos ativos."""
    linhas = _ler(pasta / BANCO,
                  "SELECT p.id, p.nome, s.sku, s.atributos, s.preco, s.ativo FROM skus s "
                  "JOIN produtos p ON p.id = s.produto_id WHERE p.ativo = 1 ORDER BY p.rowid, s.rowid")
    return [(pid, nome, sku, atrib, float(preco), bool(ativo)) for pid, nome, sku, atrib, preco, ativo in linhas]


def mudar_preco(pasta: Path, alvo: str, preco) -> list:
    """`alvo` = SKU (muda só ela) ou ID do produto (muda todas as SKUs ativas dele). Devolve os SKUs mudados."""
    valor = numero(preco)
    alvo = _id(alvo)
    achadas = _ler(pasta / BANCO, "SELECT sku, produto_id FROM skus WHERE sku = ?", (alvo,))
    if not achadas:
        achadas = _ler(pasta / BANCO, "SELECT sku, produto_id FROM skus WHERE produto_id = ? AND ativo = 1", (alvo,))
    if not achadas:
        raise ErroLoja(f"Não achei '{alvo}'. Digite o código do item (ex.: A000_M_AZ) ou do produto (ex.: A000).")
    agora = _agora()
    _executar(pasta / BANCO, [("UPDATE skus SET preco = ?, atualizado_em = ? WHERE sku = ?", (valor, agora, sku))
                              for sku, _ in achadas])
    if (pasta / CATALOGO).is_file():   # o preço base do catálogo acompanha quando o produto inteiro mudou de preço
        for pid in {pid for _, pid in achadas}:
            ativas = {r[0] for r in _ler(pasta / BANCO, "SELECT sku FROM skus WHERE produto_id = ? AND ativo = 1", (pid,))}
            if ativas <= {sku for sku, _ in achadas}:
                _executar(pasta / CATALOGO, [("UPDATE produtos SET preco = ? WHERE id = ?", (valor, pid))])
    return [sku for sku, _ in achadas]


def mudar_nome(pasta: Path, id_produto: str, nome: str) -> None:
    nome = " ".join(str(nome or "").split())
    if not nome:
        raise ErroLoja("O nome não pode ficar vazio.")
    pid = _id(id_produto)
    if not _ler(pasta / BANCO, "SELECT 1 FROM produtos WHERE id = ?", (pid,)):
        raise ErroLoja(f"Não achei o produto '{pid}'.")
    _executar(pasta / BANCO, [("UPDATE produtos SET nome = ?, atualizado_em = ? WHERE id = ?", (nome, _agora(), pid))])
    if (pasta / CATALOGO).is_file():
        _executar(pasta / CATALOGO, [("UPDATE produtos SET nome = ? WHERE id = ?", (nome, pid))])


def mudar_texto(pasta: Path, id_produto: str, campo: str, valor: str) -> None:
    """Muda a descrição ou a categoria (que ficam no catalogo.db e alimentam a vitrine do bot)."""
    if campo not in CAMPOS_TEXTO:
        raise ErroLoja(f"Só dá para mudar: {', '.join(CAMPOS_TEXTO.values())}.")
    valor = " ".join(str(valor or "").split()) if campo == "categoria" else str(valor or "").strip()
    if not valor:
        raise ErroLoja(f"A {CAMPOS_TEXTO[campo]} não pode ficar vazia.")
    pid = _id(id_produto)
    if not _ler(pasta / CATALOGO, "SELECT 1 FROM produtos WHERE id = ?", (pid,)):
        raise ErroLoja(f"Não achei o produto '{pid}' no catálogo da loja.")
    _executar(pasta / CATALOGO, [(f"UPDATE produtos SET {campo} = ? WHERE id = ?", (valor, pid)),
                                 ("UPDATE produtos SET aprovado = CASE WHEN TRIM(COALESCE(descricao, '')) <> '' "
                                  "AND TRIM(COALESCE(categoria, '')) <> '' THEN 1 ELSE 0 END WHERE id = ?", (pid,))])


# ------------------------------------------------------------------ conversa no terminal
def _reais(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _mostrar(pasta: Path) -> None:
    ultimo = None
    for pid, nome, sku, atrib, preco, ativo in listar(pasta):
        if pid != ultimo:
            print(f"\n{pid}  {nome}")
            ultimo = pid
        print(f"    {sku:<18} {_reais(preco):>12}{'' if ativo else '   (inativo)'}   {atrib if atrib != '{}' else ''}")
    if ultimo is None:
        print("A loja não tem produtos ativos.")
    print()


def menu() -> int:
    pasta = pasta_loja()
    if not (pasta / BANCO).is_file():
        print(f"Não achei a loja em {pasta}. Rode este programa dentro da pasta do bot.")
        return 1
    print(f"Loja: {pasta}")
    while True:
        print("\n1) Ver produtos e preços\n2) Mudar preço\n3) Mudar nome do produto\n"
              "4) Mudar descrição\n5) Mudar categoria\n0) Sair")
        escolha = input("Escolha: ").strip()
        try:
            if escolha == "1":
                _mostrar(pasta)
            elif escolha == "2":
                alvo = input("Código do item (A000_M_AZ) ou do produto inteiro (A000): ")
                skus = mudar_preco(pasta, alvo, input("Novo preço (ex.: 12,50): "))
                print(f"Pronto: preço mudado em {len(skus)} item(ns): {', '.join(skus)}")
            elif escolha == "3":
                mudar_nome(pasta, input("Código do produto (A000): "), input("Novo nome: "))
                print("Pronto.")
            elif escolha in ("4", "5"):
                campo = "descricao" if escolha == "4" else "categoria"
                mudar_texto(pasta, input("Código do produto (A000): "), campo, input(f"Nova {CAMPOS_TEXTO[campo]}: "))
                print("Pronto.")
            elif escolha == "0":
                return 0
            else:
                print("Digite um número do menu.")
        except ErroLoja as e:
            print(f"\nNão foi alterado: {e}")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    sys.exit(menu())
