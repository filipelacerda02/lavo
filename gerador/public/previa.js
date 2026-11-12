(function () {
  // ---------- Barreiras contra cópia ----------
  // Importante: nenhuma barreira no navegador é 100%. A proteção real é que o código do site
  // nunca é enviado antes da compra: a prévia é só uma imagem com marca d'água.
  const bloquear = (e) => e.preventDefault();
  ["contextmenu", "dragstart", "selectstart", "copy", "cut"].forEach((ev) => document.addEventListener(ev, bloquear));
  document.addEventListener("keydown", (e) => {
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    if (
      k === "f12" ||
      (ctrl && ["s", "u", "p"].includes(k)) ||
      (ctrl && e.shiftKey && ["i", "j", "c", "k"].includes(k)) ||
      (e.metaKey && e.altKey && ["i", "j", "c", "u"].includes(k))
    ) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  const id = location.pathname.split("/").pop();
  const $ = (s) => document.getElementById(s);
  const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const ordem = ["fila", "extraindo", "gerando", "renderizando", "pronto"];
  let projeto = null;
  const cache = {};

  async function status() {
    const r = await fetch(`/api/projetos/${id}`, { cache: "no-store" });
    if (r.status === 404) return mostrarFinal("<h2>Prévia não encontrada</h2><p>O link pode estar incorreto.</p><a class='btn' href='/'>Gerar uma prévia</a>");
    projeto = await r.json();
    if (projeto.status === "erro")
      return mostrarFinal(`<h2>Não deu certo desta vez</h2><p>${escapar(projeto.etapa)}</p><a class='btn' href='/'>Tentar novamente</a>`);
    if (projeto.status !== "pronto") {
      const atual = ordem.indexOf(projeto.status);
      document.querySelectorAll("#etapas li").forEach((li) => {
        const i = ordem.indexOf(li.dataset.e);
        li.className = i < atual ? "feita" : i === atual ? "atual" : "";
      });
      $("texto-status").textContent =
        projeto.status === "fila" && projeto.posicaoFila > 1
          ? `Você é o ${projeto.posicaoFila}º da fila. Já já começamos.`
          : projeto.etapa + "...";
      return setTimeout(status, 4000);
    }
    await verificarRetornoPagamento();
    if (projeto.pago && !projeto._download) {
      return mostrarFinal("<h2>Pagamento recebido 🎉</h2><p>Use o link que apareceu ao concluir o pagamento para baixar o seu site. Se fechou a página antes, fale com o nosso suporte informando o endereço do site.</p>");
    }
    mostrarPrevia();
  }

  function escapar(s) {
    return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  function mostrarFinal(html) {
    $("carregando").hidden = true;
    $("visualizador").hidden = true;
    $("final").hidden = false;
    $("final-conteudo").innerHTML = html;
  }

  // Desenha a imagem da prévia em canvas, em fatias (sem <img> para arrastar/salvar)
  async function desenhar(versao) {
    const tela = $("tela");
    tela.innerHTML = "";
    $("moldura").className = "moldura " + versao;
    document.querySelectorAll(".alternar button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === versao)));
    if (!cache[versao]) {
      const blob = await (await fetch(`/api/projetos/${id}/previa/${versao}`)).blob();
      cache[versao] = await createImageBitmap(blob);
    }
    const img = cache[versao];
    const fatia = 3000;
    for (let y = 0; y < img.height; y += fatia) {
      const h = Math.min(fatia, img.height - y);
      const c = document.createElement("canvas");
      c.width = img.width;
      c.height = h;
      c.getContext("2d").drawImage(img, 0, y, img.width, h, 0, 0, img.width, h);
      tela.appendChild(c);
    }
  }

  function mostrarPrevia() {
    $("carregando").hidden = true;
    $("visualizador").hidden = false;
    $("dominio").textContent = projeto.dominio;
    $("endereco").textContent = projeto.dominio;
    $("preco-texto").textContent = `Leve o código completo por ${brl(projeto.preco)}, pagamento único.`;
    const versoes = projeto.previas.length ? projeto.previas : ["desktop"];
    const celular = window.innerWidth < 700 && versoes.includes("celular");
    desenhar(celular ? "celular" : versoes.includes("desktop") ? "desktop" : versoes[0]);
    document.querySelectorAll(".alternar button").forEach((b) =>
      b.addEventListener("click", () => desenhar(b.dataset.v)),
    );
  }

  $("comprar").addEventListener("click", async () => {
    const b = $("comprar");
    b.disabled = true;
    b.textContent = "Abrindo pagamento...";
    try {
      const r = await fetch(`/api/projetos/${id}/checkout`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.erro);
      location.href = j.url;
    } catch (e) {
      alert(e.message || "Não foi possível abrir o pagamento.");
      b.disabled = false;
      b.textContent = "Quero este site";
    }
  });

  // Voltando do Mercado Pago: ?payment_id=...&status=approved
  async function verificarRetornoPagamento() {
    const q = new URLSearchParams(location.search);
    const pagamentoId = q.get("payment_id") || q.get("collection_id");
    if (!pagamentoId) return;
    const st = q.get("status") || q.get("collection_status");
    if (st && st !== "approved") {
      if (st === "pending" || st === "in_process") alert("Seu pagamento está sendo processado. Assim que for aprovado, volte a este link.");
      return;
    }
    for (let tentativa = 0; tentativa < 6; tentativa++) {
      const r = await fetch(`/api/projetos/${id}/confirmar`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ pagamentoId }),
      });
      const j = await r.json().catch(() => ({}));
      if (j.pago) {
        projeto._download = j.download;
        mostrarFinal(`<h2>Pronto! O site é seu 🎉</h2><p>Baixe o arquivo abaixo e guarde este link: ele é a sua chave de acesso ao download.</p><a class="btn btn-destaque" href="${escapar(j.download)}">Baixar o meu site (.zip)</a>`);
        history.replaceState(null, "", location.pathname + "?payment_id=" + encodeURIComponent(pagamentoId) + "&status=approved");
        throw "fim";
      }
      await new Promise((ok) => setTimeout(ok, 2500));
    }
  }

  status().catch((e) => {
    if (e !== "fim") console.error(e);
  });
})();
