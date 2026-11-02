/* Molde 2 -- exatamente 2 categorias: uma de cada lado; ao abrir um produto o lado dele ocupa a tela. */
(function () {
  var C = Core, cats = C.L.categorias;
  var lados = {
    left:  { cat: cats[0], panel: document.getElementById("panel-left"),  vitrine: document.getElementById("vitrine-left"),  detalhe: document.getElementById("detalhe-left"),  lista: document.getElementById("lista-left"),  titulo: document.getElementById("titulo-left") },
    right: { cat: cats[1], panel: document.getElementById("panel-right"), vitrine: document.getElementById("vitrine-right"), detalhe: document.getElementById("detalhe-right"), lista: document.getElementById("lista-right"), titulo: document.getElementById("titulo-right") }
  };

  function card(p, lado) {
    var d = document.createElement("div");
    d.className = "card-produto";
    d.innerHTML = '<img alt="" loading="lazy"><div class="card-info"><h3></h3><p></p><span class="preco"></span></div>';
    var im = d.querySelector("img"); im.src = C.capa(p); im.alt = p.nome;
    d.querySelector("h3").textContent = p.nome;
    d.querySelector("p").textContent = p.descricao || "";
    d.querySelector(".preco").textContent = (p.skus.length > 1 && p.skus.some(function (s) { return s.preco !== p.preco; }) ? C.aPartirDe : "") + C.brl(Math.min.apply(null, p.skus.map(function (s) { return s.preco; })));
    d.onclick = function () { abrir(p, lado); };
    return d;
  }

  function rotulo(cat) {
    var g = null;
    (C.L.grupos || []).forEach(function (x) { if ((x.categorias || []).indexOf(cat) >= 0) g = x.nome; });
    return g ? g + " · " + cat : cat;
  }

  Object.keys(lados).forEach(function (k) {
    var l = lados[k];
    l.titulo.textContent = rotulo(l.cat) || "";
    var lista = C.produtosDaCategoria(l.cat);
    if (!lista.length) l.lista.innerHTML = '<p class="vazio">Nenhum produto nesta categoria.</p>';
    lista.forEach(function (p) { l.lista.appendChild(card(p, k)); });
  });

  function abrir(p, k) {
    var outro = k === "left" ? "right" : "left";
    lados[k].panel.classList.add("expanded");
    lados[outro].panel.classList.add("collapsed");
    lados[k].vitrine.classList.add("escondido");
    lados[k].detalhe.innerHTML = '<button class="btn-voltar" type="button">← Voltar às categorias</button><div class="ficha"></div>';
    lados[k].detalhe.querySelector(".btn-voltar").onclick = fechar;
    C.montarProduto(lados[k].detalhe.querySelector(".ficha"), p, { miniaturas: "sempre", aoAdicionar: fechar });
    lados[k].detalhe.classList.remove("escondido");
    lados[k].panel.scrollTop = 0;
  }
  function fechar() {
    Object.keys(lados).forEach(function (k) {
      lados[k].panel.classList.remove("expanded", "collapsed");
      lados[k].vitrine.classList.remove("escondido");
      lados[k].detalhe.classList.add("escondido");
    });
  }
})();
