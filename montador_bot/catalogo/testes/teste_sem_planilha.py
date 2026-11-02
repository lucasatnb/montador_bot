import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # raiz do projeto
import json, sqlite3, tempfile, sys
from pathlib import Path
from variacoes import constantes_especializado as ce
from nucleo import gerar_pastas as gp
from nucleo import banco_loja as bl
from variacoes import planilha_especializada as pe
with tempfile.TemporaryDirectory() as td:
    loja = gp.Loja(Path(td) / "minha-loja"); loja.raiz.mkdir(); loja.imagens.mkdir()
    loja.definir_modo(gp.MODO_ESP)
    (loja.raiz/"atributos.json").write_text(json.dumps({"tipos":{
        "tamanho":{"rotulo":"Tamanho","opcoes":{"P":"P","M":"M","G":"G"}},
        "cor":{"rotulo":"Cor","opcoes":{"Azul":"AZ","Verde":"VD"}}}}), encoding="utf-8")
    ce.carregar(loja.arquivo_atributos)

    # loja vazia
    try: gp.ler_catalogo(loja); raise SystemExit("deveria dar FileNotFoundError")
    except FileNotFoundError: pass

    # ---- produto novo com variações
    pid = "A000"
    (loja.pasta_produto(pid)).mkdir(parents=True)
    (loja.pasta_produto(pid)/"01.jpg").write_bytes(b"x")
    linhas = [{"atributos":{"tamanho":t,"cor":"Azul"},"preco":50.0,"quantidade":q,"ilimitado":False,"imagem":""} for t,q in (("M",5),("G",3))]
    assert bl.validar_antes_de_gravar(loja.banco_estoque(gp.MODO_ESP), pid, "Blusa", linhas, gp.MODO_ESP) == []
    gp.gravar_produto_catalogo(loja, pid, "Blusa", 50.0, "Blusa bonita", "Roupas")
    for l in linhas: l["imagem"] = ";".join(gp.fotos_do_sku(loja, pid, l["atributos"], list(ce.VARIANTES)))
    r = bl.gravar_esp(loja.banco_estoque(gp.MODO_ESP), pid, "Blusa", linhas)
    assert sorted(r["novos"]) == ["A000_G_AZ","A000_M_AZ"], r
    assert not list(loja.raiz.glob("*.xlsx")), "não deve criar planilhas"
    cat = gp.ler_catalogo(loja); assert cat[0]["nome"]=="Blusa" and gp.aprovado(cat[0])
    con = sqlite3.connect(loja.db); assert con.execute("select count(*) from imagens").fetchone()[0]==1; con.close()

    # ---- o bot vende 2 do M; reeditar (preço novo, qtd digitada diferente) NÃO mexe na quantidade
    db = loja.banco_estoque(gp.MODO_ESP)
    c = sqlite3.connect(db); c.execute("update skus set quantidade=3 where sku='A000_M_AZ'"); c.commit(); c.close()
    est = bl.estado_inicial_esp(db, pid, 50.0)
    assert est["tem_variacoes"] and est["tipos"]=={"tamanho":["M","G"],"cor":["Azul"]}, est
    linhas2 = [dict(l, preco=55.0, quantidade=99) for l in linhas]
    r = bl.gravar_esp(db, pid, "Blusa Nova", linhas2)
    assert not r["novos"] and len(r["atualizados"])==2
    c = sqlite3.connect(db)
    assert dict(c.execute("select sku,quantidade from skus")) == {"A000_M_AZ":3,"A000_G_AZ":3}
    assert {x[0] for x in c.execute("select preco from skus")}=={55.0}
    assert c.execute("select nome from produtos").fetchone()[0]=="Blusa Nova"

    # ---- tira G, põe P: G fica inativa, P nasce com qtd
    linhas3 = [dict(linhas[0]), dict(linhas[0], atributos={"tamanho":"P","cor":"Azul"}, quantidade=7)]
    r = bl.gravar_esp(db, pid, "Blusa Nova", linhas3)
    assert r["novos"]==["A000_P_AZ"] and r["desativados"]==["A000_G_AZ"], r
    assert set(bl.carregar_produto_esp(db,pid)["tipos"]["tamanho"])=={"M","P"}
    # reativa G
    r = bl.gravar_esp(db, pid, "Blusa Nova", linhas)
    assert "A000_G_AZ" in r["atualizados"] and "A000_P_AZ" in r["desativados"]

    # ---- validação recusa erro sem tocar no banco
    ruim = [{"atributos":{"tamanho":"XXL"},"preco":1,"quantidade":1,"ilimitado":False,"imagem":""}]
    e = bl.validar_antes_de_gravar(db, pid, "Blusa", ruim, gp.MODO_ESP); assert e and "XXL" in e[0], e
    e = bl.validar_antes_de_gravar(db, "camiseta1", "X", linhas, gp.MODO_ESP); assert e and "ID inválido" in e[0], e

    # ---- simples (sem variação) no mesmo modo ESP
    gp.gravar_produto_catalogo(loja, "A001", "Caneca", 7.0, "Legal", "Casa")
    bl.gravar_esp(db, "A001", "Caneca", [{"atributos":{},"preco":7.0,"quantidade":9,"ilimitado":False,"imagem":""}])
    est = bl.estado_inicial_esp(db, "A001", 7.0)
    assert est["simples"]=={"preco":7.0,"quantidade":9,"ilimitado":False} and not est["tem_variacoes"], est

    # ---- ids em uso, catálogo em ordem
    assert {"A000","A001"} <= gp.ids_em_uso(loja, [])
    assert [p["id"] for p in gp.ler_catalogo(loja)]==["A000","A001"]
    gp.gerar_db(loja, gp.ler_catalogo(loja)); assert len(gp.ler_catalogo(loja))==2   # "Regerar"

    # ---- modo simples
    sdb = loja.banco_estoque(gp.MODO_SIMPLES)
    assert bl.ler_estoque_simples_db(sdb,"A002") is None
    assert bl.gravar_simples_db(sdb,"A002","Suco",4.5,10,False) is True
    assert bl.gravar_simples_db(sdb,"A002","Suco 2",5.0,999,True) is False
    assert bl.ler_estoque_simples_db(sdb,"A002")=={"preco":5.0,"quantidade":10,"ilimitado":False}

    # ---- o validador do banco do projeto aceita o resultado
    from variacoes import criar_banco_especializado as banco
    print("problemas do banco.validar:", banco.validar(str(db)))
print("TUDO OK")
