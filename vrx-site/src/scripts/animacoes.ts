/**
 * Motor de animações de entrada ao rolar (sem bibliotecas, ~3 KB). GSAP fica com a jornada e a transição.
 * Atributos disponíveis no HTML:
 *  data-anim="sobe|desce|esquerda|direita|zoom|desfoque|cortina|cortina-lado|giro"  entrada ao rolar
 *  data-atraso="200"            atraso em ms
 *  data-cascata="90"            aplica atrasos em sequência aos filhos [data-anim]
 *  data-contar="700" data-prefixo="+" data-sufixo=" mil"   contador animado
 *  data-barra="31%"             barra que cresce até a largura
 *  data-paralaxe="0.15"         deslocamento suave ao rolar
 *  data-desenho                 SVG cujas linhas se desenham conforme o progresso da rolagem
 *  data-ima                     botão "magnético" que segue o cursor
 *  data-inclinar                cartão que inclina em 3D com o cursor
 *  .titulo-animado              título com palavras entrando uma a uma (marcação gerada no servidor)
 *  data-flutua-cursor           elemento que acompanha levemente o cursor dentro do [data-hero]
 * Tudo respeita prefers-reduced-motion.
 */

const reduzir = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const ponteiroFino = () => window.matchMedia("(pointer: fine)").matches;

function contar(el: HTMLElement) {
  const alvo = Number(el.dataset["contar"]);
  if (!Number.isFinite(alvo)) return;
  const prefixo = el.dataset["prefixo"] ?? "";
  const sufixo = el.dataset["sufixo"] ?? "";
  const formatar = (n: number) => prefixo + Math.round(n).toLocaleString("pt-BR") + sufixo;
  if (reduzir()) return void (el.textContent = formatar(alvo));
  const duracao = 1800;
  let inicio = 0;
  const passo = (t: number) => {
    inicio ||= t;
    const p = Math.min((t - inicio) / duracao, 1);
    el.textContent = formatar(alvo * (1 - Math.pow(1 - p, 4)));
    if (p < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}

function iniciar() {
  const ctl = new AbortController();
  const { signal } = ctl;
  document.addEventListener("astro:before-swap", () => ctl.abort(), { once: true });

  // atrasos em cascata
  document.querySelectorAll<HTMLElement>("[data-cascata]").forEach((pai) => {
    const passo = Number(pai.dataset["cascata"]) || 90;
    pai.querySelectorAll<HTMLElement>(":scope > [data-anim], :scope > * > [data-anim]").forEach((el, i) => {
      if (!el.dataset["atraso"]) el.style.setProperty("--d", String(i * passo));
    });
  });
  document.querySelectorAll<HTMLElement>("[data-atraso]").forEach((el) => el.style.setProperty("--d", el.dataset["atraso"]!));

  // entradas, contadores e barras
  const alvos = document.querySelectorAll<HTMLElement>("[data-anim], .titulo-animado, .sublinhado, [data-contar], [data-barra]");
  const ativar = (el: HTMLElement) => {
    el.classList.add("is-visible");
    if (el.dataset["contar"]) contar(el);
    if (el.dataset["barra"]) el.style.width = el.dataset["barra"];
  };
  if (!("IntersectionObserver" in window) || reduzir()) {
    alvos.forEach(ativar);
  } else {
    const io = new IntersectionObserver(
      (entradas) => {
        for (const e of entradas) {
          if (!e.isIntersecting) continue;
          ativar(e.target as HTMLElement);
          io.unobserve(e.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.12 },
    );
    alvos.forEach((el) => io.observe(el));
    signal.addEventListener("abort", () => io.disconnect());
  }

  // paralaxe, desenhos SVG e barra de leitura (um único laço por quadro)
  const paralaxes = [...document.querySelectorAll<HTMLElement>("[data-paralaxe]")];
  const desenhos = [...document.querySelectorAll<SVGSVGElement>("[data-desenho]")];
  desenhos.forEach((svg) =>
    svg.querySelectorAll<SVGGeometryElement>("path, line").forEach((p) => p.style.setProperty("--len", String(Math.ceil(p.getTotalLength())))),
  );
  const barra = document.querySelector<HTMLElement>(".progresso-leitura");
  const suportaTimeline = CSS.supports("animation-timeline: scroll()");

  let agendado = false;
  const quadro = () => {
    agendado = false;
    const vh = window.innerHeight;
    if (!reduzir()) {
      for (const el of paralaxes) {
        const r = el.getBoundingClientRect();
        if (r.bottom < -200 || r.top > vh + 200) continue;
        const centro = r.top + r.height / 2 - vh / 2;
        el.style.translate = `0 ${(-centro * Number(el.dataset["paralaxe"])).toFixed(1)}px`;
      }
    }
    for (const svg of desenhos) {
      const r = svg.getBoundingClientRect();
      const p = Math.min(Math.max((vh * 0.85 - r.top) / (r.height + vh * 0.35), 0), 1);
      svg.style.setProperty("--p", reduzir() ? "1" : p.toFixed(3));
    }
    if (barra && !suportaTimeline) {
      const max = document.documentElement.scrollHeight - vh;
      barra.style.setProperty("--progresso", String(max > 0 ? window.scrollY / max : 0));
    }
  };
  const agendar = () => {
    if (!agendado) {
      agendado = true;
      requestAnimationFrame(quadro);
    }
  };
  window.addEventListener("scroll", agendar, { passive: true, signal });
  window.addEventListener("resize", agendar, { passive: true, signal });
  quadro();

  if (!ponteiroFino() || reduzir()) return;

  // botões magnéticos
  document.querySelectorAll<HTMLElement>("[data-ima]").forEach((el) => {
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left - r.width / 2) * 0.25;
      const y = (e.clientY - r.top - r.height / 2) * 0.35;
      el.style.translate = `${x.toFixed(1)}px ${y.toFixed(1)}px`;
    }, { signal });
    el.addEventListener("pointerleave", () => (el.style.translate = ""), { signal });
  });

  // cartões com inclinação 3D
  document.querySelectorAll<HTMLElement>("[data-inclinar]").forEach((el) => {
    el.style.transformStyle = "preserve-3d";
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const rx = ((e.clientY - r.top) / r.height - 0.5) * -8;
      const ry = ((e.clientX - r.left) / r.width - 0.5) * 10;
      el.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateY(-6px)`;
    }, { signal });
    el.addEventListener("pointerleave", () => (el.style.transform = ""), { signal });
  });


  // hero: a vitrine de máquinas acompanha o cursor
  const hero = document.querySelector<HTMLElement>("[data-hero]");
  const alvo = document.querySelector<HTMLElement>("[data-flutua-cursor]");
  if (hero && alvo) {
    hero.addEventListener("pointermove", (e) => {
      const r = hero.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      alvo.style.transform = `translate(${(x * 16).toFixed(1)}px, ${(y * 12).toFixed(1)}px)`;
    }, { signal });
    hero.addEventListener("pointerleave", () => (alvo.style.transform = ""), { signal });
  }
}

document.addEventListener("astro:page-load", iniciar);
