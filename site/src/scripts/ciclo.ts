/**
 * "Como funciona" — coreografia com GSAP + ScrollTrigger (scrub) + SplitText + DrawSVG + MotionPath.
 * A seção fica presa (pin) e a rolagem conduz uma timeline com rótulos:
 *  p0 Medir · p1 Pagar · p2 Colocar · p3 Escolher · p4 Iniciar · lav Lavagem · sec Secagem · fim
 */
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { ScrollToPlugin } from "gsap/ScrollToPlugin";

gsap.registerPlugin(ScrollTrigger, SplitText, DrawSVGPlugin, MotionPathPlugin, ScrollToPlugin);

const CX = 410, CY = 380;
const PROGRAMAS = ["NORMAL 35'", "PESADO 50'", "DELICADO 30'", "SECAR 45'", "NORMAL 35'"];
// início de cada etapa na timeline (em "segundos" de timeline; a rolagem é que manda)
const T = { p0: 0, p1: 1, p2: 2, p3: 3, p4: 4, lav: 5, sec: 6.7, fim: 8.2, final: 8.7 };
const INICIOS = [T.p0, T.p1, T.p2, T.p3, T.p4, T.lav, T.sec];
// zonas do foco: x, y, largura, altura
const ZONAS: Array<[number, number, number, number]> = [
  [632, 440, 168, 210], // cesto
  [26, 216, 172, 278], // totem
  [252, 224, 316, 316], // porta
  [362, 52, 152, 74], // visor
  [242, 52, 120, 120], // dispensador
  [252, 224, 316, 316], // lavagem
  [252, 224, 316, 316], // secagem
];
const mmss = (min: number) => {
  const s = Math.max(0, Math.round(min * 60));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};
const clamp = gsap.utils.clamp(0, 1);

function iniciar() {
  const encontrada = document.querySelector<HTMLElement>("[data-ciclo]");
  if (!encontrada) return;
  const secao: HTMLElement = encontrada;
  const q = <T extends Element>(s: string) => secao.querySelector<T>(s)!;
  const qa = <T extends Element>(s: string) => gsap.utils.toArray<T>(secao.querySelectorAll(s));

  const el = {
    palco: q<HTMLElement>("[data-palco]"),
    paineis: qa<HTMLElement>("[data-painel]"),
    pontos: qa<HTMLElement>("[data-ponto]"),
    pilulas: qa<HTMLElement>("[data-pilula]"),
    cta: q<HTMLElement>("[data-cta]"),
    play: q<HTMLButtonElement>("[data-iniciar]"),
    foco: q<SVGRectElement>("[data-foco]"),
    pecas: qa<SVGGElement>("[data-peca]"),
    cartao: q<SVGGElement>("[data-cartao]"),
    ledTotem: q<SVGCircleElement>("[data-led-totem]"),
    telaTotem: q<SVGTextElement>("[data-tela-totem]"),
    led: q<SVGCircleElement>("[data-led]"),
    visor: q<SVGTextElement>("[data-visor]"),
    porta: q<SVGGElement>("[data-porta]"),
    alca: q<SVGPathElement>("[data-trava-alca]"),
    trava: q<SVGRectElement>("[data-trava-corpo]"),
    tambor: q<SVGGElement>("[data-tambor]"),
    roupas: q<SVGGElement>("[data-roupas-tambor]"),
    gotas: q<SVGGElement>("[data-gotas]"),
    fluxos: qa<SVGPathElement>("[data-fluxo]"),
    agua: q<SVGGElement>("[data-agua]"),
    onda: q<SVGPathElement>("[data-onda]"),
    onda2: q<SVGPathElement>("[data-onda2]"),
    bolhas: q<SVGGElement>("[data-bolhas-agua]"),
    espuma: q<SVGGElement>("[data-espuma]"),
    brilho: q<SVGCircleElement>("[data-brilho]"),
    vapor: q<SVGGElement>("[data-vapor]"),
  };
  const origens = el.pecas.map((p) => {
    const m = /translate\(([\d.]+)[ ,]+([\d.]+)\)/.exec(p.getAttribute("transform") ?? "")!;
    return { x: Number(m[1]), y: Number(m[2]) };
  });

  const ctx = gsap.context(() => {
    const mm = gsap.matchMedia();

    // ---------- movimento reduzido: cena estática e legível ----------
    mm.add("(prefers-reduced-motion: reduce)", () => {
      secao.classList.remove("animado");
      gsap.set(el.pecas, { opacity: 0 });
      gsap.set(el.roupas, { opacity: 1 });
      gsap.set(el.agua, { y: 420 });
      gsap.set(el.espuma, { opacity: 1 });
      gsap.set(el.cartao, { opacity: 0 });
      el.visor.textContent = "21:00";
      el.pilulas.forEach((p) => { p.style.setProperty("--fill", "1"); p.querySelector("[data-tempo]")!.textContent = ""; });
    });

    // ---------- animação completa ----------
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      secao.classList.add("animado");

      // estado inicial
      gsap.set(el.paineis, { autoAlpha: 0 });
      gsap.set(el.paineis[0]!, { autoAlpha: 1 });
      gsap.set(el.porta, { scaleX: 0.16, svgOrigin: "262 380" });
      gsap.set(el.cartao, { x: 200, y: 300, rotation: -22, transformOrigin: "50% 50%", opacity: 0 });
      gsap.set(el.agua, { y: 520 });
      gsap.set(el.foco, { opacity: 1 });
      gsap.set(el.alca, { y: -6 });
      el.pecas.forEach((p, i) => gsap.set(p, { x: origens[i]!.x, y: origens[i]!.y - 200, opacity: 0, scale: 1, transformOrigin: "50% 50%" }));
      gsap.set(el.fluxos, { drawSVG: "0%", opacity: 1 });
      gsap.set(el.cta, { autoAlpha: 0, y: 16 });

      const titulos = el.paineis.map((p) => new SplitText(p.querySelector("[data-split]"), { type: "words", mask: "words" }));

      const tl = gsap.timeline({ defaults: { ease: "power2.out" } });
      Object.entries(T).forEach(([nome, t]) => tl.addLabel(nome, t));

      // troca de painéis de texto: o anterior sobe e some, o novo entra palavra por palavra
      el.paineis.forEach((painel, i) => {
        if (i === 0) return;
        const inicio = INICIOS[i]!;
        tl.to(el.paineis[i - 1]!, { autoAlpha: 0, y: -40, duration: 0.3, ease: "power2.in" }, inicio)
          .fromTo(painel, { autoAlpha: 0, y: 0 }, { autoAlpha: 1, duration: 0.01 }, inicio + 0.25)
          .from(titulos[i]!.words, { yPercent: 110, duration: 0.4, stagger: 0.05 }, inicio + 0.25)
          .from(painel.querySelectorAll(".ciclo-painel-texto, .ciclo-painel-icone, .ciclo-painel-rotulo, .ciclo-dica"), { y: 24, opacity: 0, duration: 0.4, stagger: 0.06 }, inicio + 0.3);
      });

      // foco deslizante
      ZONAS.forEach(([x, y, w, h], i) => {
        tl.to(el.foco, { attr: { x, y, width: w, height: h }, duration: 0.35, ease: "power3.inOut" }, INICIOS[i]! + (i ? 0.05 : 0));
      });
      tl.to(el.foco, { attr: { "stroke-dashoffset": -400 }, duration: T.final, ease: "none" }, 0);

      // 01 — peças caem no cesto
      el.pecas.forEach((p, i) => {
        tl.to(p, { y: origens[i]!.y, opacity: 1, duration: 0.45, ease: "bounce.out" }, 0.1 + i * 0.1);
      });

      // 02 — cartão no totem, LEDs verde-lima
      tl.to(el.cartao, { opacity: 1, duration: 0.15 }, T.p1)
        .to(el.cartao, { x: 72, y: 367, rotation: 0, duration: 0.5, ease: "power3.out" }, T.p1 + 0.1)
        .to([el.ledTotem, el.led], { attr: { fill: "#c5d539" }, duration: 0.15 }, T.p1 + 0.62)
        .to(el.cartao, { opacity: 0, y: 330, duration: 0.25 }, T.p2 - 0.05);

      // 03 — peças voam para o tambor (MotionPath) e a porta fecha
      el.pecas.forEach((p, i) => {
        const o = origens[i]!;
        tl.to(p, {
          motionPath: { path: [{ x: o.x, y: o.y }, { x: (o.x + CX) / 2 + 40, y: 230 - i * 8 }, { x: CX + (i - 2) * 14, y: CY + 30 }], curviness: 1.4 },
          scale: 0.5, duration: 0.55, ease: "power1.inOut",
        }, T.p2 + 0.05 + i * 0.07)
          .to(p, { opacity: 0, duration: 0.1 }, T.p2 + 0.55 + i * 0.07);
      });
      tl.to(el.roupas, { opacity: 1, duration: 0.2 }, T.p2 + 0.6)
        .to(el.porta, { scaleX: 1, duration: 0.3, ease: "power2.in" }, T.p2 + 0.68)
        .to(el.alca, { y: 0, duration: 0.1 }, T.p2 + 0.95)
        .to([el.alca, el.trava], { attr: { stroke: "#532458", fill: (i: number) => (i ? "#532458" : "none") }, duration: 0.1 }, T.p2 + 0.95);

      // 05 — sabão e amaciante
      tl.to(el.fluxos, { drawSVG: "100%", duration: 0.45, stagger: 0.12, ease: "power1.in" }, T.p4 + 0.35)
        .to(el.gotas, { opacity: 1, duration: 0.1 }, T.p4 + 0.75)
        .to(el.fluxos, { opacity: 0, duration: 0.2 }, T.lav + 0.15)
        .to(el.gotas, { opacity: 0, duration: 0.2 }, T.lav + 0.3);

      // LAVAGEM — água sobe, espuma, tambor acelera até centrifugar
      tl.to(el.agua, { y: 404, duration: 0.6, ease: "power2.out" }, T.lav)
        .to(el.espuma, { opacity: 1, duration: 0.4 }, T.lav + 0.2)
        .fromTo(el.tambor, { rotation: 0 }, { rotation: 360 * 6, svgOrigin: `${CX} ${CY}`, duration: T.sec - T.lav, ease: "power3.in" }, T.lav)
        .fromTo(el.roupas, { rotation: 0 }, { rotation: 360 * 5.6, svgOrigin: `${CX} ${CY}`, duration: T.sec - T.lav, ease: "power3.in" }, T.lav);

      // SECAGEM — água escoa, calor e vapor, tambor gira devagar
      tl.to(el.agua, { y: 540, duration: 0.35, ease: "power2.in" }, T.sec)
        .to(el.espuma, { opacity: 0, duration: 0.2 }, T.sec)
        .to(el.brilho, { opacity: 1, duration: 0.4 }, T.sec + 0.25)
        .to(el.vapor, { opacity: 0.85, duration: 0.4 }, T.sec + 0.35)
        .to(el.tambor, { rotation: `+=${360 * 4}`, svgOrigin: `${CX} ${CY}`, duration: T.fim - T.sec, ease: "none" }, T.sec)
        .to(el.roupas, { rotation: `+=${360 * 4}`, svgOrigin: `${CX} ${CY}`, duration: T.fim - T.sec, ease: "none" }, T.sec)
        .to([el.brilho, el.vapor], { opacity: 0, duration: 0.3 }, T.fim - 0.2);

      // FIM — porta destrava e abre um pouco, chamada para ação
      tl.to(el.alca, { y: -6, duration: 0.1 }, T.fim)
        .to(el.porta, { scaleX: 0.62, duration: 0.3, ease: "back.out(1.6)" }, T.fim + 0.05)
        .to(el.foco, { opacity: 0, duration: 0.2 }, T.fim)
        .to(el.cta, { autoAlpha: 1, y: 0, duration: 0.3 }, T.fim + 0.1)
        .to({}, { duration: T.final - T.fim - 0.4 });

      // textos dinâmicos (visor, totem, trilha, pílulas)
      const pontosEstado = (indice: number) =>
        el.pontos.forEach((p, i) => (p.dataset["estado"] = i < indice ? "feito" : i === indice ? "ativo" : ""));
      tl.eventCallback("onUpdate", () => {
        const t = tl.time();
        const indice = t >= T.fim ? 7 : Math.max(0, INICIOS.findLastIndex((i) => t >= i));
        secao.dataset["fase"] = ["medir", "pagar", "colocar", "escolher", "iniciar", "lavagem", "secagem", "fim"][indice]!;
        pontosEstado(indice);
        const pago = t >= T.p1 + 0.62;
        el.telaTotem.textContent = pago ? "OK ✓" : "R$";
        el.telaTotem.setAttribute("fill", pago ? "#c5d539" : "#be94ff");
        const tl1 = clamp((t - T.lav) / (T.sec - T.lav));
        const ts = clamp((t - T.sec) / (T.fim - T.sec));
        let visor = pago ? "LIBERADA" : "INSIRA";
        if (t >= T.p2) visor = t >= T.p2 + 0.95 ? "PORTA OK" : "ABERTA";
        if (t >= T.p3) visor = PROGRAMAS[Math.min(PROGRAMAS.length - 1, Math.floor(((t - T.p3) / 1) * PROGRAMAS.length))]!;
        if (t >= T.p4) visor = t < T.p4 + 0.35 ? "INICIAR ▶" : "35:00";
        if (t >= T.lav) visor = mmss(35 * (1 - tl1));
        if (t >= T.sec) visor = mmss(45 * (1 - ts));
        if (t >= T.fim) visor = "PRONTO";
        el.visor.textContent = visor;
        [tl1, ts].forEach((v, i) => {
          const pil = el.pilulas[i]!;
          pil.style.setProperty("--fill", v.toFixed(3));
          pil.setAttribute("aria-valuenow", String(Math.round(v * 100)));
          pil.querySelector("[data-tempo]")!.textContent = mmss((i ? 45 : 35) * (1 - v));
        });
        el.play.toggleAttribute("data-pressionado", t > T.p4 + 0.2 && t < T.p4 + 0.4);
      });

      // presa na tela durante ~7 telas de rolagem
      const st = ScrollTrigger.create({
        trigger: secao,
        pin: el.palco,
        start: "top top",
        end: () => `+=${window.innerHeight * 7}`,
        scrub: 0.7,
        animation: tl,
        anticipatePin: 1,
        invalidateOnRefresh: true,
        onToggle: (self) => ambiente.forEach((a) => (self.isActive ? a.play() : a.pause())),
      });

      // vida contínua (independente da rolagem): ondas, bolhas e vapor
      const ambiente = [
        gsap.to(el.onda, { x: -100, duration: 2.4, ease: "none", repeat: -1, paused: true }),
        gsap.to(el.onda2, { x: -100, duration: 1.7, ease: "none", repeat: -1, paused: true }),
        gsap.fromTo(el.bolhas.children, { y: 40, opacity: 0 }, { y: -90, opacity: 1, duration: 2.2, ease: "power1.out", stagger: { each: 0.28, repeat: -1 }, paused: true }),
        gsap.fromTo(el.vapor.children, { y: 20 }, { y: -40, duration: 2.6, ease: "sine.inOut", stagger: { each: 0.4, repeat: -1, yoyo: true }, paused: true }),
        gsap.fromTo(el.gotas, { y: -10 }, { y: 40, duration: 0.6, ease: "none", repeat: -1, paused: true }),
      ];

      // botão INICIAR: rola sozinho pela lavagem e secagem (qualquer rolagem do usuário interrompe)
      el.play.addEventListener("click", () => {
        const inicio = st.start + (st.end - st.start) * (T.p4 + 0.45) / T.final;
        const destino = st.end;
        const atual = Math.max(window.scrollY, inicio);
        const duracao = 7 * ((destino - atual) / (destino - inicio || 1));
        if (window.lavoLenis) {
          window.lavoLenis.scrollTo(atual, { immediate: true });
          window.lavoLenis.scrollTo(destino, { duration: Math.max(duracao, 1.5), easing: (x: number) => 0.5 - 0.5 * Math.cos(Math.PI * x), lock: false });
        } else {
          window.scrollTo({ top: atual, behavior: "instant" });
          gsap.to(window, { scrollTo: { y: destino, autoKill: true }, duration: Math.max(duracao, 1.5), ease: "sine.inOut" });
        }
      });

      return () => titulos.forEach((s) => s.revert());
    });
  }, secao);

  document.addEventListener("astro:before-swap", () => ctx.revert(), { once: true });
}

document.addEventListener("astro:page-load", iniciar);
export {};
