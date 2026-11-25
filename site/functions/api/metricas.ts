// Core Web Vitals reais dos visitantes (RUM), anônimos: sem cookies, sem IP, sem identificador.
import { vazio, json, log, type Env } from "../../borda/util";

const NOMES = new Set(["LCP", "INP", "CLS", "FCP", "TTFB"]);
const LIMITES: Record<string, [number, number]> = { LCP: [2500, 4000], INP: [200, 500], CLS: [100, 250], FCP: [1800, 3000], TTFB: [800, 1800] };

export const onRequestPost: PagesFunction<Env> = async ({ request }) => {
  const lista = (await request.json().catch(() => null)) as Array<Record<string, unknown>> | null;
  if (!Array.isArray(lista) || lista.length > 10) return json({ erro: "inválido" }, 400);
  const pais = (request as Request & { cf?: { country?: string } }).cf?.country ?? null;
  for (const m of lista) {
    const nome = String(m["nome"]);
    const valor = Number(m["valor"]);
    if (!NOMES.has(nome) || !Number.isFinite(valor) || valor < 0 || valor > 600000) continue;
    const [bom, ruim] = LIMITES[nome]!;
    log(valor > ruim ? "aviso" : "info", "web_vital", {
      nome,
      valor,
      nota: valor <= bom ? "bom" : valor <= ruim ? "melhorar" : "ruim",
      pagina: String(m["pagina"] ?? "").slice(0, 120),
      pais,
    });
  }
  return vazio();
};
