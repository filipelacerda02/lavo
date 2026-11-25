// Lê e descriptografa os pedidos de titular (uso do encarregado/DPO).
// Requer: wrangler logado na conta Cloudflare (com MFA) e a variável CHAVE_CRIPTOGRAFIA.
//   CHAVE_CRIPTOGRAFIA=... node scripts/ler-pedidos.mjs            -> lista e mostra todos
//   CHAVE_CRIPTOGRAFIA=... node scripts/ler-pedidos.mjs LGPD-2026... -> mostra um protocolo
import { execFileSync } from "node:child_process";
import { webcrypto as crypto } from "node:crypto";

const chaveB64 = process.env.CHAVE_CRIPTOGRAFIA;
if (!chaveB64) {
  console.error("Defina CHAVE_CRIPTOGRAFIA (a mesma configurada no Cloudflare).");
  process.exit(1);
}
const local = process.argv.includes("--local") ? ["--local"] : ["--remote"];
const wrangler = (...args) => execFileSync("npx", ["wrangler", "kv", ...args, "--binding", "LAVO_KV", ...local], { encoding: "utf8" });

async function descriptografar(valor) {
  const [versao, ivB64, cifraB64] = valor.trim().split(".");
  if (versao !== "v1") throw new Error("formato desconhecido");
  const chave = await crypto.subtle.importKey("raw", Buffer.from(chaveB64, "base64"), { name: "AES-GCM" }, false, ["decrypt"]);
  const claro = await crypto.subtle.decrypt({ name: "AES-GCM", iv: Buffer.from(ivB64, "base64") }, chave, Buffer.from(cifraB64, "base64"));
  return JSON.parse(new TextDecoder().decode(claro));
}

const alvo = process.argv.slice(2).find((a) => a.startsWith("LGPD-"));
const chaves = alvo ? [`titular:${alvo}`] : JSON.parse(wrangler("key", "list", "--prefix", "titular:")).map((k) => k.name);
for (const k of chaves) {
  try {
    console.log(await descriptografar(wrangler("key", "get", k)));
  } catch (e) {
    console.error(k, "→ não foi possível ler:", e.message);
  }
}
