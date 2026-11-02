/* core.js -- parte COMUM a todos os moldes: carrinho, pedido no WhatsApp e a "ficha" do produto
   (fotos + variações + preço). Os dados da loja vêm do dados.js (window.LOJA), gerado pelo gerador_site.py.
   Não precisa editar este arquivo: nome, WhatsApp, cores e molde são ajustados na tela do criador de site do montador. */
(function () {
  "use strict";
  var L = window.LOJA || { produtos: [], categorias: [] };
  var QTD_MAX = 999;
  var USAR_ESTOQUE = L.usar_estoque === true;   // liga/desliga na tela do criador de site ("Mostrar/limitar pelo estoque")
  var ORCAMENTO = L.orcamento === true;         // loja por orçamento (config.json da loja): "A combinar" no lugar dos preços
  var TELEGRAM = String(L.telegram || "").replace(/^@/, "");   // @usuario do bot: o pedido vai para o Telegram em vez do WhatsApp
  var A_PARTIR_DE = ORCAMENTO ? "" : "a partir de ";

  // ================= formato do item do pedido (espelha o formato_ids.py) =================
  // <quantidade em hexa><SKU completa>, colados:  3 un. de A001_VE_G -> "3A001_VE_G" ; 12 -> "CA001_VE_G"
  function montarItem(sku, qtd) {
    return Number(qtd).toString(16).toUpperCase() + String(sku).toUpperCase();
  }
  function decodificarItem(txt) {   // só para testes/conferência: devolve null se inválido
    var bruto = String(txt || "").trim().toUpperCase();
    var i = bruto.indexOf("_");
    var primeiro = i < 0 ? bruto : bruto.slice(0, i), resto = i < 0 ? "" : bruto.slice(i + 1);
    if (primeiro.length < 5) return null;
    var id = primeiro.slice(-4), hex = primeiro.slice(0, -4);
    if (!/^[A-Z][0-9]{3}$/.test(id) || !/^[1-9A-F][0-9A-F]*$/.test(hex)) return null;
    var qtd = parseInt(hex, 16);
    if (qtd < 1 || qtd > QTD_MAX) return null;
    var sku = id + (i < 0 ? "" : "_" + resto);
    if (!/^[A-Z][0-9]{3}(?:_[A-Z0-9]+)*$/.test(sku)) return null;
    return { id: id, quantidade: qtd, sku: sku };
  }

  // ================= utilidades =================
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function brl(v) {
    if (ORCAMENTO) return "A combinar";
    var n = Math.round(Number(v) * 100) / 100;
    var p = n.toFixed(2).split(".");
    p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return "R$ " + p[0] + "," + p[1];
  }
  function cap(s) { s = String(s == null ? "" : s); return s.charAt(0).toUpperCase() + s.slice(1); }
  function norm(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  function placeholder(nome) {
    var ini = esc(String(nome || "?").trim().charAt(0).toUpperCase());
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="100%" height="100%" fill="#dfe6e9"/>' +
      '<text x="50%" y="56%" font-family="sans-serif" font-size="110" fill="#b2bec3" text-anchor="middle">' + ini + "</text></svg>";
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }
  // foto de capa = a primeira foto GERAL do produto (as das variações só aparecem ao abrir o produto)
  function capa(prod) {
    if (prod.imagens && prod.imagens[0]) return prod.imagens[0];
    var s = prod.skus && prod.skus[0];
    if (s && s.fotos && s.fotos[0]) return s.fotos[0];
    return placeholder(prod.nome);
  }
  // foto que não carrega -> imagem padrão
  document.addEventListener("error", function (e) {
    var t = e.target;
    if (t && t.tagName === "IMG" && !t.dataset.fallback) {
      t.dataset.fallback = "1";
      t.src = placeholder(t.getAttribute("alt") || "?");
    }
  }, true);

  function produtosDaCategoria(cat) { return L.produtos.filter(function (p) { return p.categoria === cat; }); }

  // ================= estoque (só vale se "usar_estoque" estiver ligado na tela do criador de site) =================
  function disponivel(sku) {
    if (!USAR_ESTOQUE || !sku.estoque || sku.estoque.ilimitado) return Infinity;
    return Math.max(0, sku.estoque.quantidade | 0);
  }

  // ================= carrinho =================
  var carrinho = [];   // {sku, id, nome, desc, preco, qtd, max}
  var el = {};

  function toast(msg) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.classList.remove("escondido");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.toast.classList.add("escondido"); }, 2000);
  }

  function adicionar(prod, sku, descricao) {
    var ex = carrinho.filter(function (i) { return i.sku === sku.sku; })[0];
    var limite = Math.min(QTD_MAX, disponivel(sku));
    if ((ex ? ex.qtd : 0) >= limite) {
      toast(limite <= 0 ? "Produto esgotado" : "Máximo de " + limite + " unidades");
      return false;
    }
    if (ex) ex.qtd += 1;
    else carrinho.push({ sku: sku.sku, id: prod.id, nome: prod.nome, desc: descricao || "", preco: sku.preco, qtd: 1, max: limite });
    renderCarrinho();
    toast("Adicionado ao carrinho!");
    return true;
  }

  function total() { return carrinho.reduce(function (t, i) { return t + i.preco * i.qtd; }, 0); }

  function renderCarrinho() {
    if (!el.itens) return;
    var n = carrinho.reduce(function (t, i) { return t + i.qtd; }, 0);
    if (el.count) el.count.textContent = n;
    if (!carrinho.length) {
      el.itens.innerHTML = '<p class="vazio">Seu carrinho está vazio.</p>';
    } else {
      el.itens.innerHTML = carrinho.map(function (i, k) {
        return '<div class="item-carrinho"><div class="item-info"><strong>' + esc(i.nome) + "</strong>" +
          (i.desc ? "<small>" + esc(i.desc) + "</small>" : "") + "</div>" +
          '<div class="item-dir"><div class="item-preco">' + brl(i.preco * i.qtd) + "</div>" +
          '<div class="qtd-ctl"><button data-a="menos" data-i="' + k + '" aria-label="Diminuir">−</button><span>' + i.qtd +
          '</span><button data-a="mais" data-i="' + k + '" aria-label="Aumentar">+</button></div>' +
          '<small class="remover" data-a="remover" data-i="' + k + '">Remover</small></div></div>';
      }).join("");
    }
    if (el.total) el.total.textContent = brl(total());
  }

  // Pedido "só com os nomes" (opção do site: L.pedido_so_nomes). Texto pronto vem do dados.js (L.texto_pedido).
  // Para mandar só o nome, sem cor/tamanho, troque INCLUIR_VARIACAO para false.
  var INCLUIR_VARIACAO = true;
  function mensagemSoNomes() {
    var t = L.texto_pedido || {};
    var linhas = carrinho.map(function (i) {
      var var_ = INCLUIR_VARIACAO && i.desc ? " (" + String(i.desc).split(" · ").join(", ") + ")" : "";
      return "• " + i.qtd + "x " + i.nome + var_;
    });
    var partes = [];
    if (t.abertura) partes.push(String(t.abertura).trim(), "");
    partes.push(linhas.join("\n"));
    if (t.fechamento) partes.push("", String(t.fechamento).trim());
    return partes.join("\n");
  }

  function mensagemPedido() {
    if (L.pedido_so_nomes === true) return mensagemSoNomes();
    var linhas = carrinho.map(function (i) { return montarItem(i.sku, i.qtd); });
    var ini = String(L.mensagem_inicial || "").trim();
    return (ini ? ini + "\n" : "") + linhas.join("\n");
  }
  function numeroZap() { return String(L.whatsapp || "").replace(/\D/g, ""); }
  function urlWhatsapp() { return "https://wa.me/" + numeroZap() + "?text=" + encodeURIComponent(mensagemPedido()); }

  // Telegram: https://t.me/<bot>?start=<carrinho>. O parâmetro só aceita A-Z a-z 0-9 _ - (até 64 caracteres), então o
  // carrinho vai com "-" no lugar de "," (o bot desfaz a troca). Carrinho maior: abre o bot sem parâmetro e o cliente cola o código.
  function codigoCarrinho(sep) { return carrinho.map(function (i) { return montarItem(i.sku, i.qtd); }).join(sep); }
  function urlTelegram() {
    var c = codigoCarrinho("-");
    return "https://t.me/" + TELEGRAM + (c && c.length <= 64 ? "?start=" + c : "");
  }
  function pedirNoTelegram() {
    var c = codigoCarrinho("-");
    if (c.length <= 64) { window.open(urlTelegram(), "_blank"); return; }
    var codigo = codigoCarrinho(",");
    var aviso = "Seu pedido é grande demais para o link. Vamos abrir o bot: cole o código do pedido na conversa.";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(codigo).then(function () { toast("Código copiado! Cole na conversa."); },
        function () { window.prompt(aviso + " (Ctrl+C para copiar)", codigo); });
    } else {
      window.prompt(aviso + " (Ctrl+C para copiar)", codigo);
    }
    window.open("https://t.me/" + TELEGRAM, "_blank");
  }

  function iniciarCarrinho() {
    el = {
      gaveta: document.getElementById("gaveta-carrinho"), btn: document.getElementById("btn-carrinho"),
      count: document.getElementById("cart-count"), itens: document.getElementById("itens-carrinho"),
      total: document.getElementById("valor-total"), toast: document.getElementById("toast"),
      fechar: document.getElementById("fechar-carrinho"), finalizar: document.getElementById("btn-finalizar")
    };
    if (el.btn) el.btn.onclick = function () { el.gaveta.classList.remove("escondido"); };
    if (el.fechar) el.fechar.onclick = function () { el.gaveta.classList.add("escondido"); };
    if (el.itens) el.itens.addEventListener("click", function (e) {
      var a = e.target.getAttribute && e.target.getAttribute("data-a");
      if (!a) return;
      var i = carrinho[+e.target.getAttribute("data-i")];
      if (!i) return;
      if (a === "mais") { if (i.qtd < Math.min(QTD_MAX, i.max)) i.qtd++; else toast(i.max < QTD_MAX ? "Máximo de " + i.max + " unidades" : "Máximo de " + QTD_MAX + " unidades"); }
      if (a === "menos") i.qtd--;
      if (a === "remover" || i.qtd <= 0) carrinho.splice(carrinho.indexOf(i), 1);
      renderCarrinho();
    });
    if (ORCAMENTO) document.body.classList.add("orcamento");   // o CSS esconde preços e total do carrinho
    if (el.finalizar) {
      el.finalizar.textContent = (ORCAMENTO ? "Pedir orçamento" : "Pedir") + " no " + (TELEGRAM ? "Telegram" : "WhatsApp");
      el.finalizar.onclick = function () {
        if (!carrinho.length) return alert("Seu carrinho está vazio!");
        if (TELEGRAM) return pedirNoTelegram();
        if (!numeroZap()) return alert("O número do WhatsApp desta loja ainda não foi configurado.");
        window.open(urlWhatsapp(), "_blank");
      };
    }
    renderCarrinho();
  }

  // ================= ficha do produto: fotos + variações + preço =================
  // opts.miniaturas: "sempre" (miniaturas sempre visíveis) | "ao-clicar" (só aparecem ao clicar na foto)
  // opts.aoAdicionar: função chamada depois de adicionar ao carrinho
  function montarProduto(alvo, prod, opts) {
    opts = opts || {};
    var aoClicar = opts.miniaturas === "ao-clicar";
    var skuAtual = prod.skus[0];
    var sel = {};
    prod.tipos.forEach(function (t) { sel[t.tipo] = skuAtual.atributos[t.tipo]; });
    var fotos = [], idx = 0;

    alvo.innerHTML =
      '<div class="produto-ui"><div class="galeria"><img class="galeria-principal" alt="">' +
      '<div class="miniaturas' + (aoClicar ? " recolhida" : "") + '"></div><small class="dica-fotos"></small></div>' +
      '<h2 class="produto-nome"></h2><p class="produto-desc"></p><div class="variacoes"></div>' +
      '<div class="preco-final"><span class="preco-valor"></span><div class="acrescimo-texto"></div></div>' +
      '<button class="btn-principal btn-add" type="button">Adicionar ao Carrinho</button></div>';
    var $ = function (s) { return alvo.querySelector(s); };
    var principal = $(".galeria-principal"), minis = $(".miniaturas"), dica = $(".dica-fotos");
    $(".produto-nome").textContent = prod.nome;
    $(".produto-desc").textContent = prod.descricao || "";
    principal.alt = prod.nome;

    function achar(s2) {
      return prod.skus.filter(function (s) {
        return prod.tipos.every(function (t) { return s.atributos[t.tipo] === s2[t.tipo]; });
      })[0];
    }
    function descricaoSku(s) {
      return prod.tipos.map(function (t) { return cap(s.atributos[t.tipo]); }).join(" · ");
    }
    function fotoDaOpcao(tipo, opcao) {
      var t = prod.tipos.filter(function (x) { return x.tipo === tipo; })[0];
      var o = t && t.opcoes.filter(function (x) { return x.nome === opcao; })[0];
      return o && o.fotos && o.fotos[0];
    }

    // --- fotos ---
    function desenharFotos() {
      principal.src = fotos[idx] || capa(prod);
      minis.innerHTML = "";
      if (fotos.length > 1) fotos.forEach(function (f, k) {
        var im = document.createElement("img");
        im.className = "mini" + (k === idx ? " ativo" : "");
        im.src = f; im.alt = prod.nome;
        im.onclick = function () { idx = k; desenharFotos(); };
        minis.appendChild(im);
      });
      dica.textContent = fotos.length > 1 ? (aoClicar ? "Clique na foto para ver mais (" + fotos.length + ")" : "") : "";
      minis.style.display = fotos.length > 1 ? "" : "none";
    }
    principal.onclick = function () {
      if (fotos.length < 2) return;
      if (aoClicar) minis.classList.toggle("recolhida");
      else { idx = (idx + 1) % fotos.length; desenharFotos(); }
    };

    // --- variações ---
    var caixa = $(".variacoes");
    caixa.innerHTML = prod.tipos.map(function (t) {
      return '<h4>' + esc(cap(t.rotulo)) + '</h4><div class="opcoes-grid" data-tipo="' + esc(t.tipo) + '">' +
        t.opcoes.map(function (o) {
          return '<button type="button" class="opcao-btn" data-opcao="' + esc(o.nome) + '">' + esc(cap(o.nome)) + "</button>";
        }).join("") + "</div>";
    }).join("");
    caixa.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest(".opcao-btn");
      if (!b) return;
      var tipo = b.parentNode.getAttribute("data-tipo"), opcao = b.getAttribute("data-opcao");
      var novo = Object.assign({}, sel); novo[tipo] = opcao;
      var s = achar(novo);
      if (!s) {   // combinação não existe: vai para a primeira SKU que tem essa opção
        s = prod.skus.filter(function (x) { return x.atributos[tipo] === opcao; })[0];
        if (!s) return;
        novo = Object.assign({}, s.atributos);
      }
      sel = novo; skuAtual = s;
      atualizar(fotoDaOpcao(tipo, opcao));
    });

    function atualizar(irParaFoto) {
      fotos = (skuAtual.fotos && skuAtual.fotos.length) ? skuAtual.fotos : (prod.imagens || []);
      if (irParaFoto && fotos.indexOf(irParaFoto) >= 0) idx = fotos.indexOf(irParaFoto);
      else if (idx >= fotos.length) idx = 0;
      desenharFotos();
      caixa.querySelectorAll(".opcoes-grid").forEach(function (g) {
        var tipo = g.getAttribute("data-tipo");
        g.querySelectorAll(".opcao-btn").forEach(function (b) {
          b.classList.toggle("ativo", b.getAttribute("data-opcao") === sel[tipo]);
        });
      });
      $(".preco-valor").textContent = brl(skuAtual.preco);
      var dif = skuAtual.preco - prod.preco;
      $(".acrescimo-texto").textContent = dif > 0.004 && !ORCAMENTO ? "Inclui + " + brl(dif) + " pelas opções escolhidas" : "";
      var btn = $(".btn-add"), esgotado = disponivel(skuAtual) <= 0;
      btn.disabled = esgotado;
      btn.textContent = esgotado ? "Esgotado" : "Adicionar ao Carrinho";
    }

    $(".btn-add").onclick = function () {
      if (adicionar(prod, skuAtual, descricaoSku(skuAtual)) && opts.aoAdicionar) opts.aoAdicionar();
    };
    atualizar(null);
    return { sku: function () { return skuAtual; } };
  }

  window.Core = {
    L: L, esc: esc, brl: brl, cap: cap, norm: norm, capa: capa, placeholder: placeholder,
    produtosDaCategoria: produtosDaCategoria, montarProduto: montarProduto, adicionar: adicionar,
    montarItem: montarItem, decodificarItem: decodificarItem, mensagemPedido: mensagemPedido,
    urlWhatsapp: urlWhatsapp, urlTelegram: urlTelegram, aPartirDe: A_PARTIR_DE, orcamento: ORCAMENTO,
    toast: toast, carrinho: function () { return carrinho; }
  };
  iniciarCarrinho();
})();
