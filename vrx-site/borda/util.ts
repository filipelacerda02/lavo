/** Utilitários compartilhados pelas funções de borda (Cloudflare Pages Functions). */

export interface Env {
  VRX_KV: KVNamespace;
  /** Chave AES-256 em base64 (32 bytes). Gere com: openssl rand -base64 32 */
  CHAVE_CRIPTOGRAFIA?: string;
  TURNSTILE_SECRET?: string;
  /** Webhook do CRM / automação de e-mail que recebe os pedidos de orçamento (RD Station, HubSpot, Pipedrive, Zapier, Make...) */
  WEBHOOK_ORCAMENTO_URL?: string;
  /** Webhook do sistema de chamados que recebe os pedidos LGPD */
  WEBHOOK_TITULAR_URL?: string;
  WEBHOOK_SECRET?: string;
  /** Sal para pseudonimizar IPs (nunca guardamos o IP puro) */
  SALT_IP?: string;
}

const CABECALHOS_API = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
};

export function json(corpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(corpo), { status, headers: CABECALHOS_API });
}

export function vazio(status = 204): Response {
  return new Response(null, { status, headers: CABECALHOS_API });
}

/** Log estruturado (aparece no Workers Logs / Logpush) */
export function log(nivel: "info" | "aviso" | "erro", evento: string, dados: Record<string, unknown> = {}): void {
  const linha = JSON.stringify({ nivel, evento, ts: new Date().toISOString(), ...dados });
  if (nivel === "erro") console.error(linha);
  else console.log(linha);
}

const enc = new TextEncoder();

export async function hmacHex(segredo: string, mensagem: string): Promise<string> {
  const chave = await crypto.subtle.importKey("raw", enc.encode(segredo), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const assinatura = await crypto.subtle.sign("HMAC", chave, enc.encode(mensagem));
  return [...new Uint8Array(assinatura)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** IP pseudonimizado (HMAC com sal): permite limitar abusos sem guardar o IP. */
export async function ipPseudonimo(req: Request, env: Env): Promise<string> {
  const ip = req.headers.get("cf-connecting-ip") ?? "desconhecido";
  return (await hmacHex(env.SALT_IP ?? "trocar-este-sal", ip)).slice(0, 32);
}

function b64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

/** Criptografa com AES-256-GCM. Retorna "v1.<iv>.<cifra>" em base64. */
export async function criptografar(texto: string, chaveB64: string): Promise<string> {
  const bruta = Uint8Array.from(atob(chaveB64), (c) => c.charCodeAt(0));
  if (bruta.length !== 32) throw new Error("CHAVE_CRIPTOGRAFIA deve ter 32 bytes (AES-256)");
  const chave = await crypto.subtle.importKey("raw", bruta, { name: "AES-GCM" }, false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cifra = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, chave, enc.encode(texto)));
  return `v1.${b64(iv)}.${b64(cifra)}`;
}

/** Limite simples por janela de tempo usando KV (complementa as regras de Rate Limiting do WAF). */
export async function dentroDoLimite(env: Env, chave: string, maximo: number, janelaSeg: number): Promise<boolean> {
  const k = `limite:${chave}:${Math.floor(Date.now() / 1000 / janelaSeg)}`;
  const atual = Number((await env.VRX_KV.get(k)) ?? "0");
  if (atual >= maximo) return false;
  await env.VRX_KV.put(k, String(atual + 1), { expirationTtl: Math.max(60, janelaSeg * 2) });
  return true;
}

export async function verificarTurnstile(token: unknown, req: Request, env: Env): Promise<boolean> {
  if (!env.TURNSTILE_SECRET) return true; // desligado (desenvolvimento)
  if (typeof token !== "string" || !token || token.length > 2048) return false;
  const corpo = new FormData();
  corpo.append("secret", env.TURNSTILE_SECRET);
  corpo.append("response", token);
  corpo.append("remoteip", req.headers.get("cf-connecting-ip") ?? "");
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: corpo });
  const j = (await r.json()) as { success?: boolean };
  return j.success === true;
}

export const CINCO_ANOS = 5 * 365 * 24 * 3600;
export const UM_ANO = 365 * 24 * 3600;

/** Protocolo legível e difícil de adivinhar, ex.: ORC-20261126-K3F9QX */
export function gerarProtocolo(prefixo: string): string {
  const d = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const aleatorio = [...crypto.getRandomValues(new Uint8Array(6))].map((b) => "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[b % 32]).join("");
  return `${prefixo}-${d}-${aleatorio}`;
}

/** Envia um evento ao webhook com assinatura HMAC-SHA256 (cabeçalho x-vrx-assinatura) para o receptor validar a origem. */
export async function enviarWebhook(url: string, segredo: string | undefined, corpo: Record<string, unknown>, ref: string): Promise<void> {
  const texto = JSON.stringify(corpo);
  const assinatura = segredo ? await hmacHex(segredo, texto) : "";
  try {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json", "x-vrx-assinatura": `sha256=${assinatura}` }, body: texto });
    if (!r.ok) log("aviso", "webhook_falhou", { ref, status: r.status });
  } catch (e) {
    log("erro", "webhook_erro", { ref, mensagem: String(e).slice(0, 200) });
  }
}
