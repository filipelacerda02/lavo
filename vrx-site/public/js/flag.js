// Marca que o JavaScript está ativo antes da primeira pintura (habilita as animações de entrada).
// O ClientRouter troca os atributos do <html> a cada navegação: a classe é recolocada logo após a troca.
document.documentElement.classList.add("js");
document.addEventListener("astro:after-swap", function () {
  document.documentElement.classList.add("js");
});
