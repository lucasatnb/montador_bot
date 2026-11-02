/* Molde 4 -- muitas categorias e itens: busca (sem acento) + abas + grade.
   Com grupos (subcategorias): as abas viram os grupos; escolher um grupo mostra os produtos
   das categorias dele. Categorias soltas também viram abas. */
(function () {
  var C = Core, home = document.getElementById("home-view"), det = document.getElementById("detail-view"),
      conteudo = document.getElementById("detalhe-conteudo"), tabs = document.getElementById("tabs-container"),
      grade = document.getElementById("produtos-grid"), busca = document.getElementById("input-busca");
  var categoriaAtiva = "Todos", termo = "";

  var grupos = (C.L.grupos || []).filter(function (g) { return g.categorias && g.categorias.length; });
  var emGrupo = [];
  grupos.forEach(function (g) { g.categorias.forEach(function (c) { if (emGrupo.indexOf(c) < 0) emGrupo.push(c); }); });
  var soltas = C.L.categorias.filter(function (c) { return emGrupo.indexOf(c) < 0; });

  ["Todos"].concat(grupos.map(function (g) { return g.nome; }), soltas).forEach(function (aba) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "tab-btn" + (aba === categoriaAtiva ? " ativo" : ""); b.textContent = aba;
    b.onclick = function () {
      categoriaAtiva = aba;
      tabs.querySelectorAll(".tab-btn").forEach(function (x) { x.classList.remove("ativo"); });
      b.classList.add("ativo");
      desenhar();
    };
    tabs.appendChild(b);
  });
  busca.oninput = function () { termo = C.norm(busca.value).trim(); desenhar(); };

  function categoriasDaAba(aba) {
    if (aba === "Todos") return null;
    for (var i = 0; i < grupos.length; i++) {
      if (grupos[i].nome === aba) return grupos[i].categorias;
    }
    return [aba];
  }

  function desenhar() {
    grade.innerHTML = "";
    var cats = categoriasDaAba(categoriaAtiva);
    var lista = C.L.produtos.filter(function (p) {
      var naCategoria = !cats || cats.indexOf(p.categoria) >= 0;
      var noTermo = !termo || C.norm(p.nome).indexOf(termo) >= 0 || C.norm(p.descricao).indexOf(termo) >= 0 ||
                    C.norm(p.categoria).indexOf(termo) >= 0;
      return naCategoria && noTermo;
    });
    if (!lista.length) { grade.innerHTML = '<p class="vazio">Nenhum produto encontrado.</p>'; return; }
    lista.forEach(function (p) {
      var d = document.createElement("div");
      d.className = "card-produto";
      d.innerHTML = '<div><img alt="" loading="lazy"><h3></h3><p></p><span class="card-cat"></span></div><div><span class="preco"></span></div>';
      var im = d.querySelector("img"); im.src = C.capa(p); im.alt = p.nome;
      d.querySelector("h3").textContent = p.nome;
      d.querySelector("p").textContent = p.descricao || "";
      var catEl = d.querySelector(".card-cat");
      catEl.textContent = cats && cats.length > 1 ? p.categoria : "";
      d.querySelector(".preco").textContent = (p.skus.some(function (s) { return s.preco !== p.preco; }) ? C.aPartirDe : "") + C.brl(Math.min.apply(null, p.skus.map(function (s) { return s.preco; })));
      d.onclick = function () { abrir(p); };
      grade.appendChild(d);
    });
  }
  function abrir(p) {
    C.montarProduto(conteudo, p, { miniaturas: "sempre", aoAdicionar: fechar });
    home.classList.add("escondido"); det.classList.remove("escondido");
    window.scrollTo(0, 0);
  }
  function fechar() { det.classList.add("escondido"); home.classList.remove("escondido"); }
  document.getElementById("btn-voltar").onclick = fechar;
  desenhar();
})();
