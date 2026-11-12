// Limites para proteger o orçamento com IA.
import { config } from "./config.js";
import { listar } from "./store.js";

const hoje = () => new Date().toISOString().slice(0, 10);

export function verificarLimites(ip) {
  const doDia = listar().filter((p) => p.criadoEm.startsWith(hoje()) && !p.reaproveitado);
  if (doDia.length >= config.limiteGlobalDia)
    return "Estamos com muita procura hoje. Tente novamente amanhã.";
  if (doDia.filter((p) => p.ip === ip).length >= config.limitePorIpDia)
    return `Você já gerou ${config.limitePorIpDia} prévias hoje. Volte amanhã para gerar outra.`;
  return null;
}

export async function verificarRobo(token, ip) {
  if (!config.turnstileSecret) return true;
  if (!token) return false;
  const corpo = new URLSearchParams({ secret: config.turnstileSecret, response: token, remoteip: ip });
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: corpo });
    const j = await r.json();
    return j.success === true;
  } catch {
    return false;
  }
}
