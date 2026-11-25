/**
 * Rolagem suave com Lenis (MIT) sincronizada ao GSAP ScrollTrigger.
 * Desligada quando o sistema pede movimento reduzido.
 */
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

declare global {
  interface Window { lavoLenis?: Lenis }
}

if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && !window.lavoLenis) {
  const lenis = new Lenis({ autoRaf: false, anchors: true, lerp: 0.12 });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
  window.lavoLenis = lenis;
  // nova página (View Transitions): volta ao topo sem animação
  document.addEventListener("astro:after-swap", () => lenis.scrollTo(0, { immediate: true, force: true }));
}
