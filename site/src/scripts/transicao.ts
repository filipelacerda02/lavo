/**
 * Transições entre páginas com GSAP, integradas ao ClientRouter do Astro:
 * - ao sair: a água sobe do rodapé cobrindo a tela, as bolhas sobem e a porta com água girando aparece;
 * - ao entrar (inclusive no primeiro carregamento): a água continua subindo e sai pelo topo
 *   enquanto as bolhas estouram, revelando a página.
 */
import { gsap } from "gsap";

const reduzir = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const raiz = document.querySelector<HTMLElement>("[data-transicao]");

if (raiz) {
  const agua = raiz.querySelector<HTMLElement>("[data-agua-transicao]")!;
  const porta = raiz.querySelector<HTMLElement>("[data-porta-transicao]")!;
  const bolhas = gsap.utils.toArray<HTMLElement>(raiz.querySelectorAll("[data-bolha-transicao]"));
  raiz.classList.remove("inicial"); // a partir daqui o GSAP controla (remove a trava de segurança do CSS)

  let coberto = !reduzir();
  if (coberto) gsap.set(raiz, { autoAlpha: 1 });
  else gsap.set(raiz, { autoAlpha: 0 });

  const cobrir = () =>
    new Promise<void>((pronto) => {
      if (reduzir()) return pronto();
      coberto = true;
      gsap.killTweensOf([raiz, agua, porta, ...bolhas]);
      gsap.timeline({ onComplete: pronto })
        .set(raiz, { autoAlpha: 1 })
        .fromTo(agua, { yPercent: 115 }, { yPercent: 0, duration: 0.6, ease: "power3.inOut" })
        .fromTo(bolhas, { y: 160, scale: 0.4, opacity: 0 }, { y: 0, scale: 1, opacity: 1, duration: 0.55, ease: "back.out(1.7)", stagger: { each: 0.02, from: "random" } }, 0.15)
        .fromTo(porta, { scale: 0, rotation: -120 }, { scale: 1, rotation: 0, duration: 0.45, ease: "back.out(1.6)" }, 0.3);
    });

  const revelar = () => {
    if (!coberto || reduzir()) {
      gsap.set(raiz, { autoAlpha: 0 });
      return;
    }
    coberto = false;
    gsap.killTweensOf([raiz, agua, porta, ...bolhas]);
    gsap.timeline({ delay: 0.12 })
      .set(raiz, { autoAlpha: 1 })
      .set(agua, { yPercent: 0 })
      // as bolhas estouram uma a uma, de baixo para cima
      .to(bolhas, { scale: 1.7, opacity: 0, duration: 0.28, ease: "power2.out", stagger: { each: 0.025, from: "end" } }, 0)
      .to(porta, { scale: 0.2, rotation: 200, opacity: 0, duration: 0.4, ease: "back.in(1.4)" }, 0.05)
      // a água sobe e sai pelo topo
      .to(agua, { yPercent: -115, duration: 0.75, ease: "power3.inOut" }, 0.25)
      .set(raiz, { autoAlpha: 0 })
      .set(porta, { opacity: 1 });
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
