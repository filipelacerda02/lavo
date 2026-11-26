/**
 * Gestão de consentimento (CMP) - LGPD.
 * - Nada de terceiros é carregado antes do aceite da categoria correspondente.
 * - A escolha fica no navegador (localStorage) e é registrada no servidor (/api/consentimento)
 *   com id anônimo, versão da política, categorias e data, como prova do consentimento.
 */
import { site } from "@/config/site";

export type Categoria = "funcionais" | "analiticos" | "marketing";
export interface Consentimento {
  id: string;
  versao: string;
  data: string;
  categorias: Record<Categoria, boolean>;
}

const CHAVE = "vrx-consentimento";
const ouvintes = new Map<Categoria, Array<() => void>>();

function ler(): Consentimento | null {
  try {
    const bruto = localStorage.getItem(CHAVE);
    if (!bruto) return null;
    const c = JSON.parse(bruto) as Consentimento;
    return c.versao === site.versaoPolitica ? c : null; // política mudou: pergunta de novo
  } catch {
    return null;
  }
}

export function obterConsentimento(): Consentimento | null {
  return ler();
}

export function permitido(cat: Categoria): boolean {
  return ler()?.categorias[cat] === true;
}

/** Executa fn quando (e se) a categoria for consentida. */
export function quandoPermitido(cat: Categoria, fn: () => void): void {
  if (permitido(cat)) return void fn();
  const lista = ouvintes.get(cat) ?? [];
  lista.push(fn);
  ouvintes.set(cat, lista);
}

function novoId(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function salvarConsentimento(categorias: Record<Categoria, boolean>, origem: string): void {
  const anterior = ler();
  const registro: Consentimento = {
    id: anterior?.id ?? novoId(),
    versao: site.versaoPolitica,
    data: new Date().toISOString(),
    categorias,
  };
  try {
    localStorage.setItem(CHAVE, JSON.stringify(registro));
  } catch {
    /* navegação privada: vale só para esta página */
  }

  // registro no servidor (prova do consentimento, art. 8º §2º da LGPD)
  const corpo = JSON.stringify({ ...registro, origem, pagina: location.pathname });
  try {
    if (!navigator.sendBeacon?.("/api/consentimento", new Blob([corpo], { type: "application/json" }))) {
      void fetch("/api/consentimento", { method: "POST", body: corpo, headers: { "content-type": "application/json" }, keepalive: true }).catch(() => {});
    }
  } catch {
    /* sem rede: a escolha local continua valendo */
  }

  // revogação: scripts já carregados não têm como ser "descarregados" -> limpa cookies e recarrega
  const revogou = anterior && (Object.keys(categorias) as Categoria[]).some((c) => anterior.categorias[c] && !categorias[c]);
  if (revogou) {
    apagarCookiesDeTerceiros();
    location.reload();
    return;
  }

  for (const cat of Object.keys(categorias) as Categoria[]) {
    if (!categorias[cat]) continue;
    for (const fn of ouvintes.get(cat) ?? []) fn();
    ouvintes.delete(cat);
  }
  document.dispatchEvent(new CustomEvent("vrx:consentimento", { detail: registro }));
}

function apagarCookiesDeTerceiros(): void {
  const dominios = [location.hostname, "." + location.hostname.replace(/^www\./, "")];
  for (const nome of document.cookie.split(";").map((c) => c.split("=")[0]?.trim() ?? "")) {
    if (!/^(_ga|_gid|_gat|_fbp|_fbc)/.test(nome)) continue;
    for (const d of dominios) document.cookie = `${nome}=; Max-Age=0; path=/; domain=${d}`;
    document.cookie = `${nome}=; Max-Age=0; path=/`;
  }
}

// ---------- Ferramentas de terceiros (só existem se configuradas no build) ----------
type Gtag = (...args: unknown[]) => void;
declare global {
  interface Window { dataLayer?: unknown[]; gtag?: Gtag; fbq?: Gtag & { queue?: unknown[]; loaded?: boolean; version?: string; callMethod?: Gtag; push?: Gtag } }
}

function carregarScript(src: string): void {
  if (document.querySelector(`script[src="${src}"]`)) return;
  const s = document.createElement("script");
  s.src = src;
  s.async = true;
  document.head.appendChild(s);
}

const GA_ID = import.meta.env.PUBLIC_GA_ID as string | undefined;
const PIXEL_ID = import.meta.env.PUBLIC_META_PIXEL_ID as string | undefined;

if (GA_ID) {
  quandoPermitido("analiticos", () => {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() {
      // eslint-disable-next-line prefer-rest-params
      window.dataLayer!.push(arguments);
    };
    window.gtag("js", new Date());
    window.gtag("config", GA_ID, { anonymize_ip: true });
    carregarScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_ID)}`);
  });
}

if (PIXEL_ID) {
  quandoPermitido("marketing", () => {
    if (window.fbq) return;
    const fbq = function (...args: unknown[]) {
      if (fbq.callMethod) fbq.callMethod(...args);
      else fbq.queue!.push(args);
    } as NonNullable<Window["fbq"]>;
    fbq.push = fbq;
    fbq.loaded = true;
    fbq.version = "2.0";
    fbq.queue = [];
    window.fbq = fbq;
    carregarScript("https://connect.facebook.net/en_US/fbevents.js");
    fbq("init", PIXEL_ID);
    fbq("track", "PageView");
  });
}
