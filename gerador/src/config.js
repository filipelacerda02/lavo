import fs from "node:fs";
import path from "node:path";

// Carrega .env simples (sem dependência externa)
const envPath = path.resolve(".env");
if (fs.existsSync(envPath)) {
  for (const linha of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = linha.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}

const env = (k, padrao = "") => (process.env[k] ?? "").trim() || padrao;
const num = (k, padrao) => Number(env(k, String(padrao)));

export const config = {
  porta: num("PORT", 3000),
  baseUrl: env("BASE_URL", "http://localhost:3000").replace(/\/$/, ""),
  nomeProduto: env("NOME_PRODUTO", "Reforma"),
  preco: num("PRECO", 499.9),
  modelo: env("MODELO", "claude-opus-5-5"),
  esforco: env("ESFORCO", "high"),
  limitePorIpDia: num("LIMITE_POR_IP_DIA", 2),
  limiteGlobalDia: num("LIMITE_GLOBAL_DIA", 150),
  cacheDias: num("CACHE_DIAS", 7),
  cotacaoDolar: num("COTACAO_DOLAR", 5.6),
  mpAccessToken: env("MP_ACCESS_TOKEN"),
  mpWebhookSecret: env("MP_WEBHOOK_SECRET"),
  turnstileSiteKey: env("TURNSTILE_SITE_KEY"),
  turnstileSecret: env("TURNSTILE_SECRET"),
  adminSenha: env("ADMIN_SENHA"),
  pastaDados: path.resolve(env("PASTA_DADOS", "./dados")),
  modoDemo: env("MODO_DEMO", "0") === "1",
  // Preço por milhão de tokens (US$). Atualize se mudar de modelo.
  precoTokens: {
    "claude-opus-5-5": { entrada: 4, saida: 20, cacheLeitura: 0.2 },
    "claude-sonnet-5-5": { entrada: 2, saida: 10, cacheLeitura: 0.1 },
  },
};

fs.mkdirSync(path.join(config.pastaDados, "projetos"), { recursive: true });
