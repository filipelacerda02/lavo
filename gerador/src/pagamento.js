// Mercado Pago - Checkout Pro (Pix, cartão e boleto)
// Documentação: https://www.mercadopago.com.br/developers/pt/docs/checkout-pro
import crypto from "node:crypto";
import { config } from "./config.js";

const API = "https://api.mercadopago.com";

async function mp(caminho, opcoes = {}) {
  if (!config.mpAccessToken) throw new Error("MP_ACCESS_TOKEN não configurado");
  const resp = await fetch(API + caminho, {
    ...opcoes,
    headers: {
      authorization: `Bearer ${config.mpAccessToken}`,
      "content-type": "application/json",
      ...(opcoes.headers || {}),
    },
  });
  const corpo = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(`Mercado Pago ${resp.status}: ${corpo.message || JSON.stringify(corpo).slice(0, 200)}`);
  return corpo;
}

export async function criarCheckout(projeto) {
  const retorno = `${config.baseUrl}/p/${projeto.id}`;
  const corpo = {
    items: [
      {
        id: projeto.id,
        title: `Novo site pronto - ${projeto.dominio}`,
        description: "Código completo do novo site (HTML, CSS, JS e imagens)",
        quantity: 1,
        unit_price: config.preco,
        currency_id: "BRL",
      },
    ],
    payer: projeto.email ? { email: projeto.email } : undefined,
    external_reference: projeto.id,
    back_urls: { success: retorno, failure: retorno, pending: retorno },
    notification_url: `${config.baseUrl}/api/webhook/mercadopago`,
    statement_descriptor: config.nomeProduto.slice(0, 13).toUpperCase(),
  };
  // o Mercado Pago só aceita retorno automático com endereço https
  if (config.baseUrl.startsWith("https://")) corpo.auto_return = "approved";
  const pref = await mp("/checkout/preferences", {
    method: "POST",
    body: JSON.stringify(corpo),
    headers: { "x-idempotency-key": `${projeto.id}-${Date.now()}` },
  });
  return { preferenciaId: pref.id, url: pref.init_point };
}

/** Consulta o pagamento direto na API (nunca confie só no que chega pelo webhook ou pela URL). */
export async function pagamentoAprovado(pagamentoId, projetoId) {
  if (!/^\d{3,20}$/.test(String(pagamentoId || ""))) return false;
  const p = await mp(`/v1/payments/${pagamentoId}`);
  return (
    p.status === "approved" &&
    p.external_reference === projetoId &&
    p.currency_id === "BRL" &&
    Number(p.transaction_amount) + 0.001 >= config.preco
  );
}

export async function obterPagamento(pagamentoId) {
  return mp(`/v1/payments/${pagamentoId}`);
}

/** Valida o cabeçalho x-signature do webhook (se MP_WEBHOOK_SECRET estiver configurado). */
export function assinaturaValida(req, dataId) {
  if (!config.mpWebhookSecret) return true;
  const assinatura = req.get("x-signature") || "";
  const requestId = req.get("x-request-id") || "";
  const partes = Object.fromEntries(assinatura.split(",").map((p) => p.trim().split("=")));
  if (!partes.ts || !partes.v1) return false;
  const manifesto = `id:${String(dataId).toLowerCase()};request-id:${requestId};ts:${partes.ts};`;
  const esperado = crypto.createHmac("sha256", config.mpWebhookSecret).update(manifesto).digest("hex");
  const a = Buffer.from(esperado);
  const b = Buffer.from(String(partes.v1));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
