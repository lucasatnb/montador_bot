/* Molde 3 -- 3 ou mais categorias: um carrossel por categoria; o produto abre numa "página" de detalhe.
   Com grupos (subcategorias): título do grupo acima dos carrosséis das categorias dele. */
(function () {
  var C = Core, home = document.getElementById("home-view"), det = document.getElementById("detail-view"),
      conteudo = document.getElementById("detalhe-conteudo"), cont = document.getElementById("categorias-container");

  var grupos = (C.L.grupos || []).filter(function (g) { return g.categorias && g.categorias.length; });

  function secao(cat) {
    var s = document.createElement("div");
    s.className = "carousel-section";
    s.innerHTML = '<h2 class="carousel-title"></h2><div class="carousel"></div>';
    s.querySelector("h2").textContent = cat;
    var car = s.querySelector(".carousel");
    C.produtosDaCategoria(cat).forEach(function (p) {
      var d = document.createElement("div");
      d.className = "card-produto";
      d.innerHTML = '<img alt="" loading="lazy"><h3></h3><p></p><span class="preco"></span>';
      var im = d.querySelector("img"); im.src = C.capa(p); im.alt = p.nome;
      d.querySelector("h3").textContent = p.nome;
      d.querySelector("p").textContent = p.descricao || "";
      d.querySelector(".preco").textContent = (p.skus.some(function (s) { return s.preco !== p.preco; }) ? C.aPartirDe : "") + C.brl(Math.min.apply(null, p.skus.map(function (s) { return s.preco; })));
      d.onclick = function () { abrir(p); };
      car.appendChild(d);
    });
    cont.appendChild(s);
  }
  function titulo(texto) {
    var h = document.createElement("h2");
    h.className = "grupo-titulo"; h.textContent = texto;
    cont.appendChild(h);
  }

  if (grupos.length) {
    var usadas = [];
    grupos.forEach(function (g) {
      titulo(g.nome);
      g.categorias.forEach(function (cat) { secao(cat); usadas.push(cat); });
    });
    var resto = C.L.categorias.filter(function (c) { return usadas.indexOf(c) < 0; });
    if (resto.length) { titulo("Outras categorias"); resto.forEach(secao); }
  } else {
    C.L.categorias.forEach(secao);
  }
  if (!C.L.produtos.length) cont.innerHTML = '<p class="vazio">Nenhum produto disponível no momento.</p>';

  function abrir(p) {
    C.montarProduto(conteudo, p, { miniaturas: "sempre", aoAdicionar: fechar });
    home.classList.add("escondido"); det.classList.remove("escondido");
    window.scrollTo(0, 0);
  }
  function fechar() { det.classList.add("escondido"); home.classList.remove("escondido"); }
  document.getElementById("btn-voltar").onclick = fechar;
})();
