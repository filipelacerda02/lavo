// Pedidos de orçamento: minimização de dados, validação, anti-robô (Turnstile), limite por IP pseudonimizado,
// criptografia AES-256-GCM antes de salvar no KV e envio assinado (HMAC) ao CRM / automação de e-mail.
import { json, log, ipPseudonimo, dentroDoLimite, criptografar, verificarTurnstile, gerarProtocolo, enviarWebhook, UM_ANO, type Env } from "../../borda/util";

const PRODUTOS = new Set(["sfnn", "swnn", "sden-sdgn", "ssen", "ssg030", "stewx"]);
const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "));
const texto = (v: unknown, max: number) => String(v ?? "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim().slice(0, max + 1);

export const onRequestPost: PagesFunction<Env> = async ({ request, env, waitUntil }) => {
  const dados = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!dados || typeof dados !== "object") return json({ erro: "Dados inválidos." }, 400);

  // só os campos previstos (o resto é descartado)
  const nome = texto(dados["nome"], 120);
  const telefone = texto(dados["telefone"], 20);
  const digitos = telefone.replace(/\D/g, "");
  const email = texto(dados["email"], 160).toLowerCase();
  const cidade = texto(dados["cidade"], 80);
  const uf = texto(dados["uf"], 2).toUpperCase();
  const mensagem = texto(dados["mensagem"], 1000);
  const produtos = Array.isArray(dados["produtos"]) ? [...new Set((dados["produtos"] as unknown[]).filter((p): p is string => typeof p === "string" && PRODUTOS.has(p)))] : [];

  if (nome.length < 3 || nome.length > 120) return json({ erro: "Informe o seu nome." }, 400);
  if (digitos.length < 10 || digitos.length > 13) return json({ erro: "Informe um telefone com DDD." }, 400);
  if (email && (email.length > 160 || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email))) return json({ erro: "Confira o e-mail ou deixe em branco." }, 400);
  if (cidade.length > 80) return json({ erro: "Cidade muito longa." }, 400);
  if (uf && !UFS.has(uf)) return json({ erro: "Estado inválido." }, 400);
  if (mensagem.length > 1000) return json({ erro: "A mensagem passou de 1.000 caracteres." }, 400);

  if (!(await verificarTurnstile(dados["turnstile"], request, env))) return json({ erro: "Não foi possível confirmar que você não é um robô." }, 403);
  const ip = await ipPseudonimo(request, env);
  if (!(await dentroDoLimite(env, `orcamento:${ip}`, 5, 3600))) return json({ erro: "Muitos pedidos em pouco tempo. Tente de novo em uma hora ou fale pelo WhatsApp." }, 429);

  if (!env.CHAVE_CRIPTOGRAFIA) {
    log("erro", "orcamento_sem_chave", {});
    return json({ erro: "Serviço temporariamente indisponível. Fale com a VRX pelo WhatsApp." }, 503);
  }

  const protocolo = gerarProtocolo("ORC");
  const recebidoEm = new Date().toISOString();
  const pedido = { protocolo, nome, telefone: digitos, email, cidade, uf, produtos, mensagem, recebidoEm };
  await env.VRX_KV.put(`orcamento:${protocolo}`, await criptografar(JSON.stringify(pedido), env.CHAVE_CRIPTOGRAFIA), {
    expirationTtl: UM_ANO,
    metadata: { recebidoEm, produtos: produtos.length }, // metadados sem dados pessoais, para listar pedidos
  });
  log("info", "orcamento_recebido", { protocolo, produtos, uf: uf || null });

  // CRM / automação de e-mail (assinatura HMAC para o receptor validar a origem)
  if (env.WEBHOOK_ORCAMENTO_URL) waitUntil(enviarWebhook(env.WEBHOOK_ORCAMENTO_URL, env.WEBHOOK_SECRET, { evento: "vrx.pedido_orcamento", ...pedido }, protocolo));

  return json({ protocolo });
};
