// Pedidos de titular (art. 18 da LGPD): validação, anti-robô, limite, criptografia AES-256 e envio ao CRM.
import { json, log, ipPseudonimo, dentroDoLimite, criptografar, hmacHex, verificarTurnstile, CINCO_ANOS, type Env } from "../../borda/util";

const TIPOS = new Set(["confirmacao_acesso", "correcao", "eliminacao", "portabilidade", "revogacao", "oposicao", "informacao"]);

function gerarProtocolo(): string {
  const d = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const aleatorio = [...crypto.getRandomValues(new Uint8Array(4))].map((b) => b.toString(36).padStart(2, "0")).join("").slice(0, 6).toUpperCase();
  return `LGPD-${d}-${aleatorio}`;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env, waitUntil }) => {
  const dados = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!dados) return json({ erro: "Dados inválidos." }, 400);
  const nome = String(dados["nome"] ?? "").trim();
  const email = String(dados["email"] ?? "").trim().toLowerCase();
  const tipo = String(dados["tipo"] ?? "");
  const mensagem = String(dados["mensagem"] ?? "").trim();

  if (nome.length < 3 || nome.length > 120) return json({ erro: "Informe o seu nome completo." }, 400);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email) || email.length > 160) return json({ erro: "Informe um e-mail válido." }, 400);
  if (!TIPOS.has(tipo)) return json({ erro: "Escolha o tipo de pedido." }, 400);
  if (mensagem.length > 1000) return json({ erro: "A mensagem passou de 1.000 caracteres." }, 400);

  if (!(await verificarTurnstile(dados["turnstile"], request, env))) return json({ erro: "Não foi possível confirmar que você não é um robô." }, 403);
  const ip = await ipPseudonimo(request, env);
  if (!(await dentroDoLimite(env, `titular:${ip}`, 5, 3600))) return json({ erro: "Muitos pedidos em pouco tempo. Tente de novo em uma hora." }, 429);

  if (!env.CHAVE_CRIPTOGRAFIA) {
    log("erro", "titular_sem_chave", {});
    return json({ erro: "Serviço temporariamente indisponível." }, 503);
  }

  const protocolo = gerarProtocolo();
  const recebidoEm = new Date().toISOString();
  const pedido = { protocolo, nome, email, tipo, mensagem, recebidoEm };
  await env.LAVO_KV.put(`titular:${protocolo}`, await criptografar(JSON.stringify(pedido), env.CHAVE_CRIPTOGRAFIA), {
    expirationTtl: CINCO_ANOS,
    metadata: { tipo, recebidoEm }, // metadados sem dados pessoais, para listar pedidos
  });
  log("info", "titular_recebido", { protocolo, tipo });

  // Integração com CRM / sistema de chamados (assinatura HMAC para o receptor validar a origem)
  if (env.WEBHOOK_TITULAR_URL) {
    waitUntil(
      (async () => {
        const corpo = JSON.stringify({ evento: "lgpd.pedido_titular", ...pedido });
        const assinatura = env.WEBHOOK_SECRET ? await hmacHex(env.WEBHOOK_SECRET, corpo) : "";
        const r = await fetch(env.WEBHOOK_TITULAR_URL!, {
          method: "POST",
          headers: { "content-type": "application/json", "x-lavo-assinatura": `sha256=${assinatura}` },
          body: corpo,
        });
        if (!r.ok) log("aviso", "webhook_titular_falhou", { protocolo, status: r.status });
      })().catch((e) => log("erro", "webhook_titular_erro", { protocolo, mensagem: String(e) })),
    );
  }

  return json({ protocolo });
};
