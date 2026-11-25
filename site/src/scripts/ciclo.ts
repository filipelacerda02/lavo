/**
 * Coreografia do "Como funciona", guiada pela rolagem.
 *
 *  0.00–0.12  Passo 01  cesto medidor recebe as peças
 *  0.12–0.24  Passo 02  cartão no totem, LED verde-lima libera a máquina
 *  0.24–0.36  Passo 03  peças voam para o tambor e a porta fecha
 *  0.36–0.48  Passo 04  visor alterna os programas
 *  0.48–0.62  Passo 05  INICIAR: sabão e amaciante entram
 *  0.62–0.82  Lavagem   água, espuma, tambor acelera; pílula 35 min
 *  0.82–1.00  Secagem   água escoa, calor e vapor; porta destrava; pílula 45 min
 */

const FAIXAS = [0, 0.12, 0.24, 0.36, 0.48, 0.62, 0.82, 1] as const;
const LEGENDAS = [
  "Meça as roupas no cesto medidor",
  "Pague no totem: máquina liberada",
  "Roupas no tambor, porta travada",
  "Escolha o programa no visor",
  "INICIAR: sabão e amaciante entram sozinhos",
  "Lavando… o tambor acelera na centrifugação",
  "Secando com ar quente",
  "Pronto! Pode retirar suas roupas",
];
const PROGRAMAS = ["NORMAL 35'", "PESADO 50'", "DELICADO 30'", "SECAR 45'", "NORMAL 35'"];

const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const suave = (t: number) => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** progresso local (0–1) da etapa i */
const etapa = (p: number, i: number) => clamp((p - FAIXAS[i]!) / (FAIXAS[i + 1]! - FAIXAS[i]!));
const mmss = (min: number) => {
  const s = Math.max(0, Math.round(min * 60));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

// zonas do "foco" na ilustração (x, y, largura, altura)
const ZONAS: Array<[number, number, number, number]> = [
  [476, 330, 164, 146], // cesto
  [10, 140, 120, 212], // totem
  [194, 164, 252, 252], // escotilha
  [274, 48, 186, 60], // visor
  [178, 48, 286, 72], // painel (dispensador + iniciar)
  [194, 164, 252, 252], // lavagem
  [194, 164, 252, 252], // secagem
];

function iniciar() {
  const encontrada = document.querySelector<HTMLElement>("[data-ciclo]");
  if (!encontrada) return;
  const secao: HTMLElement = encontrada;
  const ctl = new AbortController();
  const { signal } = ctl;
  document.addEventListener("astro:before-swap", () => ctl.abort(), { once: true });

  const $ = <T extends Element>(s: string) => secao.querySelector<T>(s)!;
  const $$ = <T extends Element>(s: string) => [...secao.querySelectorAll<T>(s)];
  const cards = $$<HTMLElement>("[data-card]");
  const listaCards = $<HTMLElement>("[data-cards]");
  const trilho = $<HTMLElement>("[data-trilho]");
  const el = {
    foco: $<SVGRectElement>("[data-foco]"),
    cartao: $<SVGGElement>("[data-cartao]"),
    telaTotem: $<SVGTextElement>("[data-tela-totem]"),
    ledTotem: $<SVGCircleElement>("[data-led-totem]"),
    led: $<SVGCircleElement>("[data-led]"),
    visor: $<SVGTextElement>("[data-visor]"),
    travaAlca: $<SVGPathElement>("[data-trava-alca]"),
    travaCorpo: $<SVGRectElement>("[data-trava-corpo]"),
    trava: $<SVGGElement>("[data-trava]"),
    tambor: $<SVGGElement>("[data-tambor]"),
    roupas: $<SVGGElement>("[data-roupas-tambor]"),
    gotas: $<SVGGElement>("[data-gotas]"),
    agua: $<SVGGElement>("[data-agua]"),
    onda: $<SVGPathElement>("[data-onda]"),
    espuma: $<SVGGElement>("[data-espuma]"),
    brilho: $<SVGCircleElement>("[data-brilho]"),
    vapor: $<SVGGElement>("[data-vapor]"),
    porta: $<SVGGElement>("[data-porta]"),
    pecas: $$<SVGEllipseElement>("[data-peca]"),
    fluxos: $$<SVGPathElement>("[data-fluxo]"),
    legenda: $<HTMLElement>("[data-legenda]"),
    play: $<HTMLButtonElement>("[data-iniciar]"),
    pilulas: $$<HTMLElement>("[data-pilula]"),
  };
  const origemPecas = el.pecas.map((e) => ({ x: Number(e.getAttribute("cx")), y: Number(e.getAttribute("cy")) }));
  const comprimentoFluxo = el.fluxos.map((f) => f.getTotalLength());
  el.fluxos.forEach((f, i) => (f.style.strokeDasharray = String(comprimentoFluxo[i])));

  let cardAtivoAnterior = -1;
  function desenhar(p: number) {
    const t = FAIXAS.slice(0, 7).map((_, i) => etapa(p, i));
    const [t1, t2, t3, t4, t5, tl, ts] = t as [number, number, number, number, number, number, number];
    const indice = p >= 1 ? 7 : Math.min(6, FAIXAS.findIndex((f, i) => p >= f && p < (FAIXAS[i + 1] ?? 2)));
    const fase = indice <= 4 ? `passo-${indice + 1}` : indice === 5 ? "lavagem" : indice === 6 && ts < 0.92 ? "secagem" : "fim";
    secao.dataset["fase"] = fase;
    secao.classList.toggle("compacto", p >= FAIXAS[5]);

    // ---- cards ----
    cards.forEach((c, i) => {
      const estado = i < Math.min(indice, 5) ? "feito" : i === indice ? "ativo" : "";
      if (estado) c.dataset["estado"] = estado;
      else delete c.dataset["estado"];
    });
    const ativo = Math.min(indice, 4);
    if (ativo !== cardAtivoAnterior && window.matchMedia("(max-width: 1023px)").matches) {
      const card = cards[ativo]!;
      const max = listaCards.scrollWidth - trilho.clientWidth + 32;
      const x = clamp(card.offsetLeft - (trilho.clientWidth - card.offsetWidth) / 2, 0, Math.max(0, max));
      listaCards.style.transform = `translateX(${-x}px)`;
    } else if (!window.matchMedia("(max-width: 1023px)").matches) {
      listaCards.style.transform = "";
    }
    cardAtivoAnterior = ativo;

    // ---- foco deslizante ----
    const zi = Math.min(indice, 6);
    const anterior = ZONAS[Math.max(0, zi - 1)]!;
    const atual = ZONAS[zi]!;
    const k = suave(clamp(t[zi]! / 0.3));
    const [x, y, w, h] = atual.map((v, i) => lerp(anterior[i]!, v, zi === 0 ? 1 : k));
    el.foco.setAttribute("x", x!.toFixed(1));
    el.foco.setAttribute("y", y!.toFixed(1));
    el.foco.setAttribute("width", w!.toFixed(1));
    el.foco.setAttribute("height", h!.toFixed(1));
    el.foco.style.opacity = String(fase === "fim" ? 0 : 1);
    el.foco.style.strokeDashoffset = String(-p * 600);

    // ---- passo 1 e 3: peças caem no cesto e depois voam para o tambor ----
    el.pecas.forEach((peca, i) => {
      const o = origemPecas[i]!;
      const queda = suave(clamp(t1 * 1.6 - i * 0.14));
      const voo = suave(clamp((t3 - i * 0.08) / 0.55));
      const px = lerp(o.x, 320, voo);
      const py = lerp(o.y - 150 * (1 - queda), 316, voo) - Math.sin(Math.PI * voo) * 90;
      const escala = lerp(1, 0.55, voo);
      peca.setAttribute("transform", `translate(${(px - o.x).toFixed(1)} ${(py - o.y).toFixed(1)}) translate(${o.x} ${o.y}) scale(${escala.toFixed(3)}) translate(${-o.x} ${-o.y})`);
      peca.style.opacity = String(queda * (voo > 0.85 ? 1 - (voo - 0.85) / 0.15 : 1));
    });
    el.roupas.style.opacity = String(clamp((t3 - 0.55) / 0.3));

    // ---- passo 2: cartão encosta no leitor ----
    const pag = suave(clamp(t2 / 0.6));
    el.cartao.setAttribute("transform", `translate(${lerp(150, 46, pag).toFixed(1)} ${lerp(186, 252, pag).toFixed(1)}) rotate(${lerp(-24, 0, pag).toFixed(1)})`);
    el.cartao.style.opacity = String(t2 > 0.95 || p >= FAIXAS[2] ? Math.max(0, 1 - (p - FAIXAS[2]) * 20) : clamp(t1 * 3));
    const pago = p >= FAIXAS[1] + 0.06;
    el.ledTotem.setAttribute("fill", pago ? "#c5d539" : "#8a8494");
    el.telaTotem.textContent = pago ? "OK ✓" : "R$";
    el.telaTotem.setAttribute("fill", pago ? "#c5d539" : "#be94ff");
    el.led.setAttribute("fill", pago ? "#c5d539" : "#8a8494");

    // ---- porta: aberta → fecha no fim do passo 3 → destrava no fim ----
    const fechamento = suave(clamp((t3 - 0.6) / 0.4));
    const abertura = fase === "fim" ? suave(clamp((ts - 0.9) / 0.1)) : 0;
    const escalaPorta = lerp(0.16, 1, fechamento) - abertura * 0.42;
    el.porta.setAttribute("transform", `translate(202 0) scale(${escalaPorta.toFixed(3)} 1) translate(-202 0)`);
    const travada = fechamento >= 1 && fase !== "fim";
    el.travaAlca.setAttribute("transform", travada ? "" : "translate(0 -5)");
    el.trava.setAttribute("stroke", travada ? "#532458" : "#6d6977");
    el.travaCorpo.setAttribute("fill", travada ? "#532458" : "#6d6977");

    // ---- visor ----
    let visor = "INSIRA";
    if (pago) visor = "LIBERADA";
    if (p >= FAIXAS[2]) visor = fechamento >= 1 ? "PORTA OK" : "ABERTA";
    if (p >= FAIXAS[3]) visor = PROGRAMAS[Math.min(PROGRAMAS.length - 1, Math.floor(t4 * PROGRAMAS.length))]!;
    if (p >= FAIXAS[4]) visor = t5 < 0.35 ? "INICIAR ▶" : "35:00";
    if (p >= FAIXAS[5]) visor = mmss(35 * (1 - tl));
    if (p >= FAIXAS[6]) visor = mmss(45 * (1 - ts));
    if (fase === "fim") visor = "PRONTO";
    el.visor.textContent = visor;

    // ---- passo 5: botão pressionado e fluxos de sabão/amaciante ----
    if (t5 > 0.2 && t5 < 0.4) el.play.dataset["pressionado"] = "";
    else delete el.play.dataset["pressionado"];
    el.fluxos.forEach((f, i) => {
      const desenho = suave(clamp((t5 - 0.35 - i * 0.1) / 0.4));
      f.style.strokeDashoffset = String(comprimentoFluxo[i]! * (1 - desenho));
      f.style.opacity = String(p >= FAIXAS[5] ? Math.max(0, 1 - tl * 6) : desenho > 0 ? 1 : 0);
    });
    el.gotas.style.opacity = String(t5 > 0.6 && tl < 0.2 ? 1 : 0);
    el.gotas.setAttribute("transform", `translate(0 ${((p * 4000) % 60).toFixed(1)})`);

    // ---- lavagem e secagem ----
    const nivel = p < FAIXAS[5] ? 0 : p < FAIXAS[6] ? suave(clamp(tl / 0.35)) * 110 : 110 * (1 - suave(clamp(ts / 0.2)));
    el.agua.setAttribute("transform", `translate(${(-((p * 3000) % 80)).toFixed(1)} ${(388 - nivel).toFixed(1)})`);
    el.espuma.style.opacity = String(p < FAIXAS[6] ? clamp(tl / 0.3) : Math.max(0, 1 - ts * 6));
    const angulo =
      p < FAIXAS[5] ? 0 : p < FAIXAS[6] ? 360 * (tl * 4 + Math.pow(tl, 3) * 12) : 360 * 16 + 360 * ts * 7;
    el.tambor.setAttribute("transform", `rotate(${angulo.toFixed(1)} 320 290)`);
    el.roupas.setAttribute("transform", `rotate(${(angulo * 0.92).toFixed(1)} 320 290)`);
    const calor = p >= FAIXAS[6] ? suave(clamp((ts - 0.1) / 0.3)) * (1 - suave(clamp((ts - 0.82) / 0.12))) : 0;
    el.brilho.style.opacity = String(calor);
    el.vapor.style.opacity = String(calor * 0.8);
    el.vapor.setAttribute("transform", `translate(0 ${(-((p * 2400) % 70)).toFixed(1)})`);

    // ---- pílulas e legenda ----
    const preencher = (pil: HTMLElement, v: number, total: number) => {
      pil.style.setProperty("--fill", v.toFixed(3));
      pil.setAttribute("aria-valuenow", String(Math.round(v * 100)));
      pil.querySelector("[data-tempo]")!.textContent = mmss(total * (1 - v));
    };
    preencher(el.pilulas[0]!, tl, 35);
    preencher(el.pilulas[1]!, ts, 45);
    el.legenda.textContent =
      indice === 2 && fechamento < 1 ? "Colocando as roupas no tambor" : LEGENDAS[fase === "fim" ? 7 : Math.min(indice, 6)]!;
  }

  // ---------- modo estático (sem animação) ----------
  const reduzir = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (reduzir.matches) {
    secao.classList.remove("animado");
    desenhar(0.7);
    secao.classList.remove("compacto");
    el.pilulas.forEach((pil) => {
      pil.style.setProperty("--fill", "1");
      pil.querySelector("[data-tempo]")!.textContent = "";
    });
    el.legenda.textContent = "Lavando: sabão e amaciante entram sozinhos";
    return;
  }

  // ---------- modo animado ----------
  secao.classList.add("animado");
  const progresso = () => {
    const r = secao.getBoundingClientRect();
    const total = secao.offsetHeight - window.innerHeight;
    return total > 0 ? clamp(-r.top / total) : 0;
  };
  let agendado = false;
  const atualizar = () => {
    agendado = false;
    desenhar(progresso());
  };
  const agendar = () => {
    if (!agendado) {
      agendado = true;
      requestAnimationFrame(atualizar);
    }
  };
  window.addEventListener("scroll", agendar, { passive: true, signal });
  window.addEventListener("resize", agendar, { passive: true, signal });
  atualizar();

  // ---------- botão INICIAR: rolagem automática pela lavagem e secagem ----------
  let rolando = 0;
  const cancelar = () => cancelAnimationFrame(rolando);
  ["wheel", "touchstart", "keydown", "pointerdown"].forEach((ev) => window.addEventListener(ev, cancelar, { passive: true, signal }));
  el.play.addEventListener("click", (e) => {
    e.stopPropagation();
    const topoSecao = secao.getBoundingClientRect().top + window.scrollY;
    const total = secao.offsetHeight - window.innerHeight;
    const destino = topoSecao + total;
    const inicioY = Math.max(window.scrollY, topoSecao + total * (FAIXAS[4] + 0.04));
    const duracao = 8000 * ((destino - inicioY) / (total * (1 - FAIXAS[4])));
    const t0 = performance.now();
    // "instant": o CSS do site usa scroll-behavior smooth, que amorteceria cada quadro
    window.scrollTo({ top: inicioY, behavior: "instant" });
    cancelAnimationFrame(rolando);
    const passo = (agora: number) => {
      const k = clamp((agora - t0) / Math.max(duracao, 1500));
      window.scrollTo({ top: lerp(inicioY, destino, 0.5 - 0.5 * Math.cos(Math.PI * k)), behavior: "instant" });
      if (k < 1) rolando = requestAnimationFrame(passo);
    };
    // o próprio clique dispara "pointerdown": inicia no próximo quadro para não se cancelar
    requestAnimationFrame(() => (rolando = requestAnimationFrame(passo)));
  }, { signal });
}

document.addEventListener("astro:page-load", iniciar);

export {};
