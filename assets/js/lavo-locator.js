/* =========================================================
   BUSCADOR UNIFICADO DE UNIDADES LAVÔ
   ---------------------------------------------------------
   Engine original do site lavo.eco.br, preservada:
   - dados em TSV embutido no HTML (#lavo-dados-tsv)
     colunas: Logradouro | País | Bairro | Cidade | UF | CEP
   - busca por logradouro, bairro, cidade, UF, nome do estado ou CEP
     (sem diferenciar acentos/maiúsculas)
   - paginação de 8 unidades por página
   - mapa Google My Maps que reposiciona na cidade da 1ª unidade
     encontrada (geocodificação via Nominatim/OpenStreetMap)
   - botões "Como chegar" (Google Maps) e "Waze"

   Acréscimos desta versão (marcados com [novo]):
   - lê ?q= da URL para pré-preencher a busca (usado pela home)
   - botões de sugestão rápida ([data-lavo-sugestao])
   - mensagem de vazio com classe CSS em vez de estilo inline
   ========================================================= */
(function() {
  var mapaBaseUrl = "https://www.google.com/maps/d/u/1/embed?mid=1C070ks3zDcTEq7Z2qIbjW17pjGOd7MQ&ehbc=2E312F&noprof=1";

  var nomeEstados = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins"
  };

  var elBusca = document.getElementById('lavo-input-busca');
  var elMapa = document.getElementById('lavo-iframe-mapa');
  var statusTexto = document.getElementById('lavo-status');
  var elContador = document.getElementById('lavo-contador');
  var elListaCards = document.getElementById('lavo-lista-cards');
  var elBtnPrev = document.getElementById('lavo-btn-prev');
  var elBtnNext = document.getElementById('lavo-btn-next');
  var elInfoPagina = document.getElementById('lavo-info-pagina');

  if (!elBusca || !elListaCards) return;

  var todasUnidades = [];
  var unidadesFiltradas = [];
  var paginaAtual = 1;
  var itensPorPagina = 8;
  var mapFocusDebounce = null;

  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function(c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function norm(s) {
    return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  function formatarCep(c) {
    var d = (c || '').replace(/\D/g, '');
    return d.length === 8 ? d.slice(0, 5) + '-' + d.slice(5) : (c || '').trim();
  }

  // Formato: Logradouro(0) | País(1) | Bairro(2) | Cidade(3) | UF(4) | CEP(5)
  function processarTSV(texto) {
    var lista = [];
    var linhas = texto.trim().split('\n');
    if (linhas.length < 2) return lista;

    for (var i = 1; i < linhas.length; i++) {
      var cols = linhas[i].split('\t').map(function(c) { return c.trim(); });
      if (cols.length >= 5 && cols[4]) {
        lista.push({
          logradouro: cols[0] || '',
          bairro: cols[2] || '',
          cidade: cols[3] || '',
          uf: cols[4].toUpperCase(),
          cep: formatarCep(cols[5])
        });
      }
    }
    return lista;
  }

  function carregarUnidades() {
    var rawText = document.getElementById('lavo-dados-tsv').textContent;
    todasUnidades = processarTSV(rawText);
    unidadesFiltradas = todasUnidades;
    renderizar();
  }

  function aoDigitar() {
    aplicarFiltros();

    clearTimeout(mapFocusDebounce);
    mapFocusDebounce = setTimeout(function() {
      var termo = elBusca.value.trim();
      if (termo.length > 2 && unidadesFiltradas.length > 0) {
        var u = unidadesFiltradas[0];
        var queryFoco = u.cidade + ", " + (nomeEstados[u.uf] || u.uf) + ", Brasil";
        focarMapa(queryFoco, 12);
      } else if (!termo) {
        elMapa.src = mapaBaseUrl;
      }
    }, 1200);
  }

  elBusca.addEventListener('input', aoDigitar);

  function aplicarFiltros() {
    var termo = norm(elBusca.value.trim());

    unidadesFiltradas = todasUnidades.filter(function(u) {
      if (!termo) return true;

      var ehBuscaCep = /^[\d.\-\s]+$/.test(termo);
      var termoCep = termo.replace(/\D/g, '');
      if (ehBuscaCep) {
        return termoCep.length > 0 && u.cep.replace(/\D/g, '').indexOf(termoCep) !== -1;
      }

      var estadoNome = norm(nomeEstados[u.uf] || '');
      return norm(u.logradouro).indexOf(termo) !== -1 ||
             norm(u.bairro).indexOf(termo) !== -1 ||
             norm(u.cidade).indexOf(termo) !== -1 ||
             norm(u.uf) === termo ||
             estadoNome.indexOf(termo) !== -1;
    });

    paginaAtual = 1;
    renderizar();
  }

  function focarMapa(termo, zoom) {
    statusTexto.textContent = "Atualizando localização no mapa...";
    var url = "https://nominatim.openstreetmap.org/search?format=json&q=" + encodeURIComponent(termo);
    fetch(url)
      .then(function(res) { return res.json(); })
      .then(function(data) {
        if (data && data.length > 0) {
          elMapa.src = mapaBaseUrl + "&ll=" + data[0].lat + "," + data[0].lon + "&z=" + zoom;
        }
        statusTexto.textContent = "";
      })
      .catch(function() { statusTexto.textContent = ""; });
  }

  function renderizar() {
    elListaCards.innerHTML = '';
    elContador.textContent ='+' +unidadesFiltradas.length + ' unidades encontradas';

    if (unidadesFiltradas.length === 0) {
      elListaCards.innerHTML = '<p class="lavo-vazio">Nenhuma unidade encontrada para esta busca.</p>'; // [novo] classe CSS
      elInfoPagina.textContent = 'Página 0 de 0';
      elBtnPrev.disabled = true;
      elBtnNext.disabled = true;
      return;
    }

    var totalPaginas = Math.ceil(unidadesFiltradas.length / itensPorPagina);
    var inicio = (paginaAtual - 1) * itensPorPagina;
    var itens = unidadesFiltradas.slice(inicio, inicio + itensPorPagina);

    itens.forEach(function(u) {
      var enderecoCompleto = u.logradouro + (u.bairro ? ' - ' + u.bairro : '') + ', ' + u.cidade + ' - ' + u.uf + (u.cep ? ', CEP ' + u.cep : '');
      var encodedGoogle = encodeURIComponent(enderecoCompleto);
      var encodedWaze = encodeURIComponent(u.logradouro + ', ' + u.cidade + ' - ' + u.uf);

      var card = document.createElement('div');
      card.className = 'lavo-card';
      card.innerHTML =
        '<h3 class="lavo-card-title">Lavô ' + esc(u.cidade) + '</h3>' +
        '<div class="lavo-card-sub">' + esc(u.bairro || u.cidade) + ' — ' + esc(u.uf) + '</div>' +
        '<p class="lavo-card-address">' + esc(enderecoCompleto) + '</p>' +
        '<div class="lavo-card-actions">' +
          '<a class="lavo-btn lavo-btn-primary" href="https://www.google.com/maps/dir/?api=1&destination=' + encodedGoogle + '" target="_blank" rel="noopener">Como chegar</a>' +
          '<a class="lavo-btn lavo-btn-secondary" href="https://www.waze.com/ul?q=' + encodedWaze + '&navigate=yes" target="_blank" rel="noopener">Waze</a>' +
        '</div>';
      elListaCards.appendChild(card);
    });

    elInfoPagina.textContent = 'Página ' + paginaAtual + ' de ' + totalPaginas;
    elBtnPrev.disabled = (paginaAtual === 1);
    elBtnNext.disabled = (paginaAtual === totalPaginas);
  }

  elBtnPrev.addEventListener('click', function() {
    if (paginaAtual > 1) { paginaAtual--; renderizar(); }
  });

  elBtnNext.addEventListener('click', function() {
    var totalPaginas = Math.ceil(unidadesFiltradas.length / itensPorPagina);
    if (paginaAtual < totalPaginas) { paginaAtual++; renderizar(); }
  });

  carregarUnidades();

  // [novo] sugestões rápidas (chips) e links por estado
  function buscarPor(termo) {
    elBusca.value = termo;
    aoDigitar();
    elBusca.focus({ preventScroll: true });
  }
  document.querySelectorAll('[data-lavo-sugestao]').forEach(function(el) {
    el.addEventListener('click', function(e) {
      e.preventDefault();
      buscarPor(el.getAttribute('data-lavo-sugestao'));
      var alvo = document.getElementById('lavo-store-locator');
      if (alvo && el.closest('#lavo-store-locator') === null) alvo.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // [novo] pré-preenche com ?q= (busca vinda da home)
  try {
    var q = new URLSearchParams(window.location.search).get('q');
    if (q) buscarPor(q);
  } catch (e) {}

  // expõe contagem total para o restante da página
  window.lavoTotalUnidades = todasUnidades.length;
  document.querySelectorAll('[data-lavo-total]').forEach(function(el) {
    el.textContent = todasUnidades.length;
  });
})();
