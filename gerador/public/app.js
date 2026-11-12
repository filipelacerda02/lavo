(async function () {
  const form = document.getElementById("form");
  const erro = document.getElementById("erro");
  const botao = document.getElementById("enviar");
  document.getElementById("ano").textContent = new Date().getFullYear();

  let cfg = { preco: 499.9, nome: "Reforma", turnstileSiteKey: null };
  try {
    cfg = await (await fetch("/api/config")).json();
  } catch {}
  const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  document.getElementById("valor").firstChild.textContent = brl(cfg.preco) + " ";
  document.querySelectorAll("[data-nome-texto]").forEach((el) => (el.textContent = cfg.nome));

  // Cloudflare Turnstile (anti-robô), se configurado
  let tokenRobo = null;
  if (cfg.turnstileSiteKey) {
    window.onTurnstile = (t) => (tokenRobo = t);
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?onload=__ts";
    window.__ts = () => window.turnstile.render("#turnstile", { sitekey: cfg.turnstileSiteKey, callback: window.onTurnstile });
    document.head.appendChild(s);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    erro.textContent = "";
    const url = form.url.value.trim();
    const email = form.email.value.trim();
    const aceite = document.getElementById("aceite").checked;
    if (!url) return (erro.textContent = "Informe o endereço do seu site.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return (erro.textContent = "Informe um e-mail válido.");
    if (!aceite) return (erro.textContent = "Confirme que você é o responsável pelo site.");
    botao.disabled = true;
    botao.textContent = "Enviando...";
    try {
      const r = await fetch("/api/projetos", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url, email, aceite, turnstile: tokenRobo }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.erro || "Erro ao enviar");
      window.location.href = "/p/" + j.id;
    } catch (err) {
      erro.textContent = err.message;
      botao.disabled = false;
      botao.textContent = "Gerar prévia grátis";
      if (window.turnstile) window.turnstile.reset();
    }
  });
})();
