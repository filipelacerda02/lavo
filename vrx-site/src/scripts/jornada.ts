/**
 * Jornada "Da escolha à lavanderia funcionando" — GSAP + ScrollTrigger (pin + scrub) + SplitText + DrawSVG.
 * A seção fica presa e a rolagem conduz uma timeline com rótulos:
 *  escolha · orcamento · ponto · instalacao · operacao · suporte · fim
 */
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";

gsap.registerPlugin(ScrollTrigger, SplitText, DrawSVGPlugin);

const T = { escolha: 0, orcamento: 1, ponto: 2, instalacao: 3, operacao: 4, suporte: 5.2, fim: 6.3, final: 6.8 };
const INICIOS = [T.escolha, T.orcamento, T.ponto, T.instalacao, T.operacao, T.suporte];
const FASES = ["escolha", "orcamento", "ponto", "instalacao", "operacao", "suporte"] as const;
const VISOR: Record<string, string> = { a: "LAVANDO", b1: "SECANDO", b2: "LAVANDO", c: "SECANDO" };

function iniciar() {
  const encontrada = document.querySelector<HTMLElement>("[data-jornada]");
  if (!encontrada) return;
  const secao: HTMLElement = encontrada;
  const q = <E extends Element>(s: string) => secao.querySelector<E>(s)!;
  const qa = <E extends Element>(s: string) => gsap.utils.toArray<E>(secao.querySelectorAll(s));

  const el = {
    palco: q<HTMLElement>("[data-palco]"),
    paineis: qa<HTMLElement>("[data-painel]"),
    pontos: qa<HTMLElement>("[data-ponto]"),
    cta: q<HTMLElement>("[data-cta]"),
    contornos: q<SVGGElement>("[data-contornos]"),
    contorno: qa<SVGRectElement>("[data-contorno]"),
    etiquetas: q<SVGGElement>("[data-etiquetas]"),
    etiqueta: qa<SVGGElement>("[data-etiqueta]"),
    celular: q<SVGGElement>("[data-celular]"),
    bolhas: qa<SVGGElement>("[data-bolha]"),
    documento: q<SVGGElement>("[data-documento]"),
    linhasDoc: q<SVGPathElement>("[data-linhas-doc]"),
    planta: q<SVGGElement>("[data-planta]"),
    material: q<SVGGElement>("[data-material]"),
    agua: qa<SVGPathElement>('[data-linha="agua"]'),
    energia: qa<SVGPathElement>('[data-linha="energia"]'),
    esgoto: qa<SVGPathElement>('[data-linha="esgoto"]'),
    pontosInst: qa<SVGGElement>("[data-pontos] > g"),
    maquinas: qa<SVGGElement>("[data-maquina]"),
    sombras: qa<SVGEllipseElement>("[data-sombra]"),
    visores: qa<SVGTextElement>("[data-visor]"),
    leds: qa<SVGCircleElement>("[data-led]"),
    tambores: qa<SVGGElement>("[data-tambor]"),
    aguaTambor: qa<SVGGElement>("[data-agua]"),
    ondas: qa<SVGPathElement>("[data-onda]"),
    calor: qa<SVGCircleElement>("[data-calor]"),
    placa: q<SVGRectElement>("[data-placa]"),
    placaTexto: q<SVGTextElement>("[data-placa-texto]"),
    eficiencia: q<SVGGElement>("[data-eficiencia]"),
    indicadores: qa<SVGGElement>("[data-indicador]"),
    pinos: q<SVGGElement>("[data-pinos]"),
    pino: qa<SVGGElement>("[data-pino]"),
    selo: q<SVGGElement>("[data-selo]"),
    check: q<SVGPathElement>("[data-check]"),
    chave: q<SVGGElement>("[data-chave]"),
  };

  const ctx = gsap.context(() => {
    const mm = gsap.matchMedia();

    // ---------- movimento reduzido: cena estática, loja pronta ----------
    mm.add("(prefers-reduced-motion: reduce)", () => {
      secao.classList.remove("animado");
    });

    // ---------- animação completa ----------
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      secao.classList.add("animado");

      // estado inicial
      gsap.set(el.paineis, { autoAlpha: 0 });
      gsap.set(el.paineis[0]!, { autoAlpha: 1 });
      gsap.set(el.cta, { autoAlpha: 0, y: 16 });
      gsap.set([el.contornos, el.etiquetas], { opacity: 1 });
      gsap.set(el.contorno, { opacity: 0, scale: 0.9, transformOrigin: "50% 100%" });
      gsap.set(el.etiqueta, { opacity: 0, y: 14, scale: 0.6, transformOrigin: "50% 100%" });
      gsap.set(el.celular, { opacity: 0, y: 90 });
      gsap.set(el.bolhas, { opacity: 0, scale: 0.6, transformOrigin: "100% 50%" });
      gsap.set(el.documento, { opacity: 0, y: 20 });
      gsap.set(el.linhasDoc, { drawSVG: "0%" });
      gsap.set([...el.agua, ...el.energia, ...el.esgoto], { drawSVG: "0%" });
      gsap.set(el.pontosInst, { scale: 0, transformOrigin: "50% 50%" });
      gsap.set(el.planta, { opacity: 0 });
      gsap.set(el.material, { opacity: 0, x: -30 });
      gsap.set(el.maquinas, { y: (i: number) => -560 - i * 40, opacity: 0 });
      gsap.set(el.sombras, { scale: 0.2, opacity: 0, transformOrigin: "50% 50%" });
      gsap.set(el.leds, { attr: { fill: "#9a9b96" } });
      el.visores.forEach((v) => (v.textContent = ""));
      gsap.set(el.placa, { attr: { fill: "#2a2b29" } });
      gsap.set(el.placaTexto, { attr: { fill: "#6b6c68" } });
      gsap.set(el.eficiencia, { opacity: 1 });
      gsap.set(el.indicadores, { opacity: 0, y: -16 });
      gsap.set(el.pinos, { opacity: 1 });
      gsap.set(el.pino, { opacity: 0, y: -40 });
      gsap.set(el.selo, { opacity: 0, scale: 0.5, svgOrigin: "400 230" });
      gsap.set(el.check, { drawSVG: "0%" });

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
          .from(painel.querySelectorAll(".jornada-painel-texto, .jornada-painel-icone, .jornada-painel-rotulo"), { y: 24, opacity: 0, duration: 0.4, stagger: 0.06 }, inicio + 0.3);
      });

      // 01 — ESCOLHA: os contornos dos equipamentos aparecem e recebem as etiquetas dos modelos
      tl.to(el.contorno, { opacity: 1, scale: 1, duration: 0.4, stagger: 0.12, ease: "back.out(1.6)" }, 0.05)
        .to(el.contorno, { attr: { "stroke-dashoffset": -60 }, duration: T.instalacao, ease: "none" }, 0)
        .to(el.etiqueta, { opacity: 1, y: 0, scale: 1, duration: 0.35, stagger: 0.12, ease: "back.out(2)" }, 0.35);

      // 02 — ORÇAMENTO: o celular sobe, as mensagens chegam e o orçamento é montado
      tl.to(el.celular, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out" }, T.orcamento)
        .to(el.bolhas, { opacity: 1, scale: 1, duration: 0.25, stagger: 0.18, ease: "back.out(1.8)" }, T.orcamento + 0.25)
        .to(el.documento, { opacity: 1, y: 0, duration: 0.3 }, T.orcamento + 0.75)
        .to(el.linhasDoc, { drawSVG: "100%", duration: 0.3 }, T.orcamento + 0.85)
        .to(el.celular, { opacity: 0, y: 120, duration: 0.3, ease: "power2.in" }, T.ponto - 0.05);

      // 03 — PONTO: planta técnica, material de apoio e as linhas de água, energia e esgoto se desenhando
      tl.to(el.planta, { opacity: 1, duration: 0.3 }, T.ponto)
        .to(el.material, { opacity: 1, x: 0, duration: 0.35 }, T.ponto + 0.1)
        .to(el.agua, { drawSVG: "100%", duration: 0.45, stagger: 0.05, ease: "power1.inOut" }, T.ponto + 0.2)
        .to(el.energia, { drawSVG: "100%", duration: 0.45, stagger: 0.05, ease: "power1.inOut" }, T.ponto + 0.35)
        .to(el.esgoto, { drawSVG: "100%", duration: 0.4, stagger: 0.05, ease: "power1.inOut" }, T.ponto + 0.5)
        .to(el.pontosInst, { scale: 1, duration: 0.25, stagger: 0.05, ease: "back.out(2.5)" }, T.ponto + 0.7);

      // 04 — INSTALAÇÃO: projeto sai de cena e os equipamentos descem para o lugar
      tl.to([el.planta, el.material], { opacity: 0, duration: 0.25 }, T.instalacao)
        .to(el.etiqueta, { opacity: 0, y: -10, duration: 0.2 }, T.instalacao)
        .to(el.maquinas, { y: 0, opacity: 1, duration: 0.55, stagger: 0.14, ease: "power3.out" }, T.instalacao + 0.1)
        .to(el.sombras, { scale: 1, opacity: 0.22, duration: 0.55, stagger: 0.14, ease: "power3.out" }, T.instalacao + 0.1)
        .to(el.contorno, { opacity: 0, duration: 0.2 }, T.instalacao + 0.6);

      // 05 — OPERAÇÃO: visores e LEDs acendem, tambores giram, água e calor, placa ABERTO e eficiência
      tl.to(el.leds, { attr: { fill: "#4cd07d" }, duration: 0.1, stagger: 0.05 }, T.operacao)
        .to(el.placa, { attr: { fill: "#3a1d08" }, duration: 0.2 }, T.operacao + 0.1)
        .to(el.placaTexto, { attr: { fill: "#ff9a4d" }, duration: 0.2 }, T.operacao + 0.1)
        .to(el.aguaTambor, { opacity: 1, duration: 0.3 }, T.operacao + 0.15)
        .to(el.calor, { opacity: 0.9, duration: 0.4 }, T.operacao + 0.2)
        .to(el.tambores, { rotation: 360 * 3, svgOrigin: (_i: number, alvo: SVGGElement) => centro(alvo), duration: T.final - T.operacao, ease: "power1.in" }, T.operacao)
        .to(el.indicadores, { opacity: 1, y: 0, duration: 0.3, stagger: 0.12, ease: "back.out(1.8)" }, T.operacao + 0.4);

      // 06 — SUPORTE: indicadores dão lugar ao selo de garantia e aos técnicos espalhados
      tl.to(el.indicadores, { opacity: 0, y: -12, duration: 0.2 }, T.suporte)
        .to(el.selo, { opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.7)" }, T.suporte + 0.05)
        .to(el.check, { drawSVG: "100%", duration: 0.3 }, T.suporte + 0.35)
        .fromTo(el.chave, { rotation: -60 }, { rotation: 0, svgOrigin: "458 150", duration: 0.4, ease: "back.out(2)" }, T.suporte + 0.3)
        .to(el.pino, { opacity: 1, y: 0, duration: 0.3, stagger: 0.07, ease: "bounce.out" }, T.suporte + 0.4)
        .to(el.cta, { autoAlpha: 1, y: 0, duration: 0.3 }, T.fim)
        .to({}, { duration: T.final - T.fim - 0.3 });

      // textos dinâmicos (trilha, visores)
      tl.eventCallback("onUpdate", () => {
        const t = tl.time();
        const indice = Math.max(0, INICIOS.findLastIndex((i) => t >= i));
        secao.dataset["fase"] = FASES[indice]!;
        el.pontos.forEach((p, i) => (p.dataset["estado"] = i < indice ? "feito" : i === indice ? "ativo" : ""));
        const ligado = t >= T.operacao;
        el.visores.forEach((v) => {
          const id = v.dataset["visor"] ?? "";
          const texto = ligado ? (VISOR[id] ?? "") : "";
          if (v.textContent !== texto) v.textContent = texto;
        });
      });

      // presa na tela durante ~6 telas de rolagem
      const st = ScrollTrigger.create({
        trigger: secao,
        pin: el.palco,
        start: "top top",
        end: () => `+=${window.innerHeight * 6}`,
        scrub: 0.7,
        animation: tl,
        anticipatePin: 1,
        invalidateOnRefresh: true,
        onToggle: (self) => ambiente.forEach((a) => (self.isActive ? a.play() : a.pause())),
      });

      // vida contínua (independente da rolagem): ondas na água das lavadoras
      const ambiente = el.ondas.map((o) => gsap.to(o, { x: Number(o.dataset["periodo"] ?? 40), duration: 1.6, ease: "none", repeat: -1, paused: true }));

      return () => {
        titulos.forEach((s) => s.revert());
        st.kill();
      };
    });
  }, secao);

  document.addEventListener("astro:before-swap", () => ctx.revert(), { once: true });
}

/** Centro de rotação de um tambor (o círculo base do grupo) */
function centro(alvo: SVGGElement): string {
  const c = alvo.querySelector("circle");
  return `${c?.getAttribute("cx") ?? 0} ${c?.getAttribute("cy") ?? 0}`;
}

document.addEventListener("astro:page-load", iniciar);
export {};
