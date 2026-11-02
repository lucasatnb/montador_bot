/* Molde 1 -- sem categorias: cada produto é um bloco; foto geral na capa, as outras ao clicar nela.
   Com grupos (subcategorias): os blocos aparecem agrupados sob o título de cada grupo. */
(function () {
  var C = Core, vit = document.getElementById("vitrine-full");
  if (!C.L.produtos.length) { vit.innerHTML = '<p class="vazio">Nenhum produto disponível no momento.</p>'; return; }

  var grupos = (C.L.grupos || []).filter(function (g) { return g.categorias && g.categorias.length; });
  var emGrupo = [];

  function bloco(p) {
    var d = document.createElement("div");
    d.className = "card-bloco"; d.id = "prod-" + p.id;
    vit.appendChild(d);
    C.montarProduto(d, p, { miniaturas: "ao-clicar" });
  }
  function titulo(texto) {
    var h = document.createElement("h2");
    h.className = "grupo-titulo"; h.textContent = texto;
    vit.appendChild(h);
  }

  if (grupos.length) {
    grupos.forEach(function (g) {
      titulo(g.nome);
      g.categorias.forEach(function (cat) {
        C.produtosDaCategoria(cat).forEach(function (p) { bloco(p); emGrupo.push(p); });
      });
    });
    var resto = C.L.produtos.filter(function (p) { return emGrupo.indexOf(p) < 0; });
    if (resto.length) { titulo("Outros produtos"); resto.forEach(bloco); }
  } else {
    C.L.produtos.forEach(bloco);
  }
})();
