/* Lavô — interações gerais do site */
(function () {
  var header = document.querySelector('.site-header');
  var toggle = document.querySelector('.menu-toggle');
  var nav = document.getElementById('nav-principal');

  // Menu mobile
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var aberto = nav.classList.toggle('aberto');
      toggle.setAttribute('aria-expanded', aberto ? 'true' : 'false');
    });
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a')) {
        nav.classList.remove('aberto');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('aberto')) {
        nav.classList.remove('aberto');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  // Sombra do header ao rolar
  function onScroll() {
    if (header) header.classList.toggle('rolado', window.scrollY > 8);
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Contadores animados
  function animarNumero(el) {
    var alvo = parseFloat(el.getAttribute('data-contar'));
    if (isNaN(alvo)) return;
    var prefixo = el.getAttribute('data-prefixo') || '';
    var sufixo = el.getAttribute('data-sufixo') || '';
    var dur = 1600;
    var inicio = null;
    function passo(ts) {
      if (!inicio) inicio = ts;
      var p = Math.min((ts - inicio) / dur, 1);
      var e = 1 - Math.pow(1 - p, 3);
      el.textContent = prefixo + Math.round(alvo * e).toLocaleString('pt-BR') + sufixo;
      if (p < 1) requestAnimationFrame(passo);
    }
    requestAnimationFrame(passo);
  }

  var reduzir = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Reveal ao rolar + gatilhos
  var alvos = document.querySelectorAll('.reveal, [data-contar], .preench');
  if ('IntersectionObserver' in window && !reduzir) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        if (el.classList.contains('reveal')) el.classList.add('visivel');
        if (el.hasAttribute('data-contar')) animarNumero(el);
        if (el.classList.contains('preench')) el.style.width = el.getAttribute('data-largura');
        io.unobserve(el);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.15 });
    alvos.forEach(function (el) { io.observe(el); });
  } else {
    alvos.forEach(function (el) {
      el.classList.add('visivel');
      if (el.classList.contains('preench')) el.style.width = el.getAttribute('data-largura');
    });
  }

  // Ano no rodapé
  document.querySelectorAll('[data-ano]').forEach(function (el) {
    el.textContent = new Date().getFullYear();
  });
})();
