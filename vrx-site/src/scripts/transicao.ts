/**
 * Transições entre páginas com GSAP, integradas ao ClientRouter do Astro:
 * - ao sair (astro:before-preparation): as seis pás do cata-vento VRX giram a partir do centro e se
 *   fecham cobrindo a tela; o logo aparece no meio. O carregamento da próxima página só termina
 *   quando a tela está coberta;
 * - ao entrar (astro:page-load, inclusive na primeira carga): o cata-vento gira e se recolhe para o
 *   centro, uma pá de cada vez, revelando a página.
 * A trava de segurança em CSS (.transicao.inicial) esconde a cobertura se este script não rodar.
 */
import { gsap } from "gsap";

const reduzir = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const raiz = document.querySelector<HTMLElement>("[data-transicao]");

if (raiz) {
  const pas = gsap.utils.toArray<SVGPathElement>(raiz.querySelectorAll("[data-pa-transicao]"));
  const centro = raiz.querySelector<HTMLElement>("[data-centro-transicao]")!;
  raiz.classList.remove("inicial"); // a partir daqui o GSAP controla (remove a trava de segurança do CSS)
  gsap.set(pas, { svgOrigin: "0 0" });

  let coberto = !reduzir();
  gsap.set(raiz, { autoAlpha: coberto ? 1 : 0 });

  const cobrir = () =>
    new Promise<void>((pronto) => {
      if (reduzir()) return pronto();
      coberto = true;
      gsap.killTweensOf([raiz, centro, ...pas]);
      gsap.timeline({ onComplete: pronto })
        .set(raiz, { autoAlpha: 1 })
        .fromTo(pas, { rotation: -75, scale: 0 }, { rotation: 0, scale: 1, duration: 0.62, ease: "power3.inOut", stagger: 0.045 })
        .fromTo(centro, { autoAlpha: 0, scale: 0.6 }, { autoAlpha: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)" }, 0.38);
    });

  let revelando: gsap.core.Timeline | null = null;
  const revelar = () => {
    if (!coberto || reduzir()) {
      // chamada repetida (primeira carga + astro:page-load): não interrompe a revelação em curso
      if (!revelando || revelando.progress() >= 1) gsap.set(raiz, { autoAlpha: 0 });
      return;
    }
    coberto = false;
    gsap.killTweensOf([raiz, centro, ...pas]);
    revelando = gsap.timeline({ delay: 0.1 })
      .set(raiz, { autoAlpha: 1 })
      .set(pas, { rotation: 0, scale: 1 })
      .to(centro, { autoAlpha: 0, scale: 0.7, rotation: -8, duration: 0.3, ease: "power2.in" }, 0)
      // o cata-vento gira e se recolhe para o centro, pá por pá
      .to(pas, { rotation: 80, scale: 0, duration: 0.7, ease: "power3.inOut", stagger: { each: 0.05, from: "end" } }, 0.12)
      .set(raiz, { autoAlpha: 0 })
      .set(centro, { rotation: 0 });
  };

  // sair da página: segura o carregamento da próxima até a tela estar coberta
  document.addEventListener("astro:before-preparation", (ev) => {
    const original = ev.loader;
    ev.loader = async () => {
      await Promise.all([cobrir(), original()]);
    };
  });
  // entrar na página (navegações) e primeira carga (chamada direta: não depende da ordem dos eventos)
  document.addEventListener("astro:page-load", revelar);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", revelar, { once: true });
  else revelar();
}
