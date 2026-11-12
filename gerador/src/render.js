// Renderização no servidor com Chromium (Playwright):
// - miniaturas das imagens do site original (para o Claude enxergar o conteúdo)
// - prints da prévia com marca d'água (o código nunca vai para o navegador do cliente antes da compra)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

let navegador = null;
async function obterNavegador() {
  if (navegador && navegador.isConnected()) return navegador;
  const opcoes = { args: ["--no-sandbox", "--disable-dev-shm-usage"] };
  if (process.env.CHROMIUM_PATH) opcoes.executablePath = process.env.CHROMIUM_PATH;
  navegador = await chromium.launch(opcoes);
  return navegador;
}

// Durante a renderização, só deixa carregar arquivos do próprio projeto e fontes do Google.
function travarRede(pagina, pasta) {
  const raiz = pathToFileURL(pasta).href;
  return pagina.route("**/*", (rota) => {
    const url = rota.request().url();
    if (url.startsWith(raiz) || url.startsWith("data:") || /^https:\/\/fonts\.(googleapis|gstatic)\.com\//.test(url))
      return rota.continue();
    return rota.abort();
  });
}

/** Gera miniaturas JPEG (máx. 420px) e devolve [{arquivo, base64}] */
export async function miniaturas(pasta, imagens) {
  const nav = await obterNavegador();
  const ctx = await nav.newContext({ viewport: { width: 420, height: 420 }, javaScriptEnabled: false });
  const pagina = await ctx.newPage();
  await travarRede(pagina, pasta);
  const saida = [];
  try {
    for (const img of imagens) {
      const src = pathToFileURL(path.join(pasta, img.arquivo)).href;
      await pagina.setContent(
        `<html><body style="margin:0;background:#bbb;display:inline-block"><img id="i" src="${src}" style="display:block;max-width:420px;max-height:420px"></body></html>`,
        { waitUntil: "load" },
      );
      const el = await pagina.$("#i");
      const caixa = el && (await el.boundingBox());
      if (!caixa || caixa.width < 2) continue;
      const buf = await el.screenshot({ type: "jpeg", quality: 70 });
      saida.push({ arquivo: img.arquivo, base64: buf.toString("base64") });
    }
  } finally {
    await ctx.close();
  }
  return saida;
}

const MARCA = (texto) => {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='460' height='260'><text x='50%' y='50%' text-anchor='middle' dominant-baseline='middle' transform='rotate(-24 230 130)' font-family='Arial, sans-serif' font-size='30' font-weight='700' fill='rgba(20,20,20,0.16)'>${texto}</text></svg>`;
  return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
};

/**
 * Tira prints (desktop e celular) do index.html do projeto, com marca d'água.
 * Salva em <pasta>/previa/desktop.jpg e celular.jpg e devolve os caminhos relativos.
 */
export async function printsPrevia(pasta, textoMarca) {
  const nav = await obterNavegador();
  const destino = path.join(pasta, "previa");
  fs.mkdirSync(destino, { recursive: true });
  const arquivo = pathToFileURL(path.join(pasta, "index.html")).href;
  const resultados = [];
  for (const [nome, largura, altura, escala] of [
    ["desktop", 1366, 860, 1],
    ["celular", 390, 844, 2],
  ]) {
    const ctx = await nav.newContext({ viewport: { width: largura, height: altura }, deviceScaleFactor: escala });
    const pagina = await ctx.newPage();
    await travarRede(pagina, pasta);
    try {
      await pagina.goto(arquivo, { waitUntil: "load", timeout: 30_000 });
      // rola a página para disparar lazy-load e animações de entrada
      const h = await pagina.evaluate(() => document.documentElement.scrollHeight);
      for (let y = 0; y < Math.min(h, 30000); y += 500) {
        await pagina.evaluate((v) => window.scrollTo(0, v), y);
        await pagina.waitForTimeout(60);
      }
      await pagina.evaluate(() => window.scrollTo(0, 0));
      await pagina.addStyleTag({
        content: `*,*::before,*::after{animation-play-state:paused!important;transition:none!important}
          .reveal,[data-animate],[class*="fade"],[class*="reveal"]{opacity:1!important;transform:none!important}`,
      });
      // marca d'água cobrindo a página inteira
      await pagina.evaluate((fundo) => {
        const d = document.createElement("div");
        d.style.cssText = `position:absolute;left:0;top:0;width:100%;height:${document.documentElement.scrollHeight}px;z-index:2147483647;pointer-events:none;background-image:${fundo};background-repeat:repeat`;
        document.body.appendChild(d);
      }, MARCA(textoMarca));
      await pagina.waitForTimeout(400);
      const rel = `previa/${nome}.jpg`;
      await pagina.screenshot({ path: path.join(pasta, rel), fullPage: true, type: "jpeg", quality: 72 });
      resultados.push(rel);
    } finally {
      await ctx.close();
    }
  }
  return resultados;
}

export async function fecharNavegador() {
  if (navegador) await navegador.close().catch(() => {});
  navegador = null;
}
