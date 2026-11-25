// Pós-build: gera dist/_headers (cabeçalhos de segurança) e valida o HTML gerado.
// Falha o build se encontrar script/estilo embutido (quebraria a CSP) ou imagem sem alt.
import fs from "node:fs";
import path from "node:path";

const dist = path.resolve("dist");
const env = process.env;
const erros = [];
const avisos = [];

// ---------- Content Security Policy ----------
const script = ["'self'", "https://challenges.cloudflare.com"];
const connect = ["'self'", "https://nominatim.openstreetmap.org"];
const img = ["'self'", "data:"];
const frame = ["https://www.google.com", "https://challenges.cloudflare.com"];
if (env.PUBLIC_GA_ID) {
  script.push("https://www.googletagmanager.com");
  connect.push("https://*.google-analytics.com", "https://*.analytics.google.com", "https://www.googletagmanager.com");
  img.push("https://*.google-analytics.com", "https://www.googletagmanager.com");
}
if (env.PUBLIC_META_PIXEL_ID) {
  script.push("https://connect.facebook.net");
  connect.push("https://www.facebook.com");
  img.push("https://www.facebook.com");
}
if (env.PUBLIC_SENTRY_DSN) {
  try {
    connect.push("https://" + new URL(env.PUBLIC_SENTRY_DSN).host);
  } catch {
    erros.push("PUBLIC_SENTRY_DSN inválido");
  }
}
const csp = [
  "default-src 'self'",
  `script-src ${script.join(" ")}`,
  "style-src 'self'",
  `img-src ${img.join(" ")}`,
  "font-src 'self'",
  `connect-src ${connect.join(" ")}`,
  `frame-src ${frame.join(" ")}`,
  "form-action 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const headers = `/*
  Content-Security-Policy: ${csp}
  Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Resource-Policy: same-origin
  X-Permitted-Cross-Domain-Policies: none
  ! Access-Control-Allow-Origin

/_astro/*
  Cache-Control: public, max-age=31536000, immutable

/js/*
  Cache-Control: public, max-age=86400
`;
fs.writeFileSync(path.join(dist, "_headers"), headers);

// ---------- Validação do HTML ----------
function arquivosHtml(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? arquivosHtml(p) : e.name.endsWith(".html") ? [p] : [];
  });
}
for (const arq of arquivosHtml(dist)) {
  const html = fs.readFileSync(arq, "utf8");
  const nome = path.relative(dist, arq);
  for (const m of html.matchAll(/<script\b([^>]*)>/g)) {
    const attrs = m[1];
    if (/\bsrc=/.test(attrs) || /type="application\/ld\+json"/.test(attrs)) continue;
    erros.push(`${nome}: <script> embutido (bloqueado pela CSP)`);
  }
  if (/<style[\s>]/.test(html)) erros.push(`${nome}: <style> embutido (bloqueado pela CSP)`);
  if (/\sstyle="/.test(html)) erros.push(`${nome}: atributo style= (bloqueado pela CSP)`);
  for (const m of html.matchAll(/<img\b[^>]*>/g)) if (!/\salt(=|\s|>|\/)/.test(m[0])) erros.push(`${nome}: imagem sem alt`);
  if (!/<html lang="pt-BR"/.test(html)) erros.push(`${nome}: falta lang="pt-BR"`);
  if (html.includes("PREENCHER")) avisos.push(`${nome}: contém "PREENCHER" (complete src/config/site.ts)`);
}

for (const a of [...new Set(avisos)]) console.warn("⚠️ ", a);
if (erros.length) {
  for (const e of erros) console.error("❌", e);
  process.exit(1);
}
console.log(`✅ Build verificado: ${arquivosHtml(dist).length} páginas, CSP estrita gerada em dist/_headers`);
