// Registro do consentimento (prova exigida pelo art. 8º, §2º da LGPD).
import { json, vazio, log, ipPseudonimo, dentroDoLimite, CINCO_ANOS, type Env } from "../../borda/util";

const ORIGENS = new Set(["aceitar_todos", "somente_essenciais", "personalizado", "carregar_mapa"]);
const CATEGORIAS = ["funcionais", "analiticos", "marketing"] as const;

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  const dados = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!dados) return json({ erro: "JSON inválido" }, 400);
  const { id, versao, categorias, origem, pagina } = dados as { id: unknown; versao: unknown; categorias: Record<string, unknown>; origem: unknown; pagina: unknown };
  if (typeof id !== "string" || !/^[\w-]{8,64}$/.test(id)) return json({ erro: "id inválido" }, 400);
  if (typeof versao !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(versao)) return json({ erro: "versão inválida" }, 400);
  if (typeof origem !== "string" || !ORIGENS.has(origem)) return json({ erro: "origem inválida" }, 400);
  if (!categorias || typeof categorias !== "object" || !CATEGORIAS.every((c) => typeof categorias[c] === "boolean"))
    return json({ erro: "categorias inválidas" }, 400);

  const ip = await ipPseudonimo(request, env);
  if (!(await dentroDoLimite(env, `consent:${ip}`, 30, 3600))) return json({ erro: "Muitas requisições" }, 429);

  const agora = new Date();
  const registro = {
    id,
    versao,
    origem,
    categorias: Object.fromEntries(CATEGORIAS.map((c) => [c, categorias[c] === true])),
    pagina: typeof pagina === "string" ? pagina.slice(0, 200) : "",
    recebidoEm: agora.toISOString(),
    ipPseudonimo: ip,
    pais: (request as Request & { cf?: { country?: string } }).cf?.country ?? null,
    navegador: (request.headers.get("user-agent") ?? "").slice(0, 200),
  };
  await env.VRX_KV.put(`consentimento:${agora.toISOString().slice(0, 10)}:${id}:${agora.getTime()}`, JSON.stringify(registro), { expirationTtl: CINCO_ANOS });
  log("info", "consentimento_registrado", { origem, versao, categorias: registro.categorias });
  return vazio();
};
