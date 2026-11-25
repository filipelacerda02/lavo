// Middleware de todas as rotas /api: método, origem (CSRF), tamanho do corpo e erros.
import { json, log, type Env } from "../../borda/util";

export const onRequest: PagesFunction<Env> = async (ctx) => {
  const { request } = ctx;
  if (request.method !== "POST") return json({ erro: "Método não permitido" }, 405);

  // Só aceita chamadas do próprio site (proteção contra CSRF)
  const origem = request.headers.get("origin");
  const meuHost = new URL(request.url).host;
  if (origem && new URL(origem).host !== meuHost) return json({ erro: "Origem não permitida" }, 403);
  const site = request.headers.get("sec-fetch-site");
  if (site && !["same-origin", "none"].includes(site)) return json({ erro: "Origem não permitida" }, 403);

  const tamanho = Number(request.headers.get("content-length") ?? "0");
  if (tamanho > 8192) return json({ erro: "Requisição grande demais" }, 413);
  if (!(request.headers.get("content-type") ?? "").includes("application/json")) return json({ erro: "Use JSON" }, 415);

  try {
    return await ctx.next();
  } catch (e) {
    log("erro", "api_falhou", { rota: new URL(request.url).pathname, mensagem: String((e as Error)?.message ?? e).slice(0, 300) });
    return json({ erro: "Erro interno. Tente novamente." }, 500);
  }
};
