// Lê o site atual: textos, imagens, cores, fontes, contatos e páginas internas.
import fs from "node:fs";
import path from "node:path";
import * as cheerio from "cheerio";
import { imageSize } from "image-size";
import { baixar, validarUrl } from "./rede.js";

const MAX_PAGINAS_EXTRAS = 4;
const MAX_IMAGENS = 24;
const MAX_CARACTERES_POR_PAGINA = 9000;

const ehHtml = (tipo) => tipo.includes("text/html") || tipo.includes("application/xhtml");

function limparTexto(t) {
  return t.replace(/\s+/g, " ").trim();
}

function extrairTextos($) {
  const linhas = [];
  const vistos = new Set();
  $("h1,h2,h3,h4,h5,p,li,blockquote,figcaption,dt,dd,address,td,th,button,label").each((_, el) => {
    const $el = $(el);
    // evita duplicar texto de elementos aninhados (ex.: <li><p>)
    if ($el.parents("p,li,blockquote,td,th,button").length && !/^h\d$/.test(el.tagName)) return;
    const t = limparTexto($el.text());
    if (!t || t.length < 2 || vistos.has(t)) return;
    vistos.add(t);
    const tag = el.tagName.toLowerCase();
    const prefixo = /^h\d$/.test(tag) ? "#".repeat(Number(tag[1])) + " " : tag === "li" ? "- " : "";
    linhas.push(prefixo + t);
  });
  let texto = linhas.join("\n");
  if (texto.length > MAX_CARACTERES_POR_PAGINA) texto = texto.slice(0, MAX_CARACTERES_POR_PAGINA) + "\n[...]";
  return texto;
}

function coletarLinks($, base) {
  const internos = [];
  const contatos = new Set();
  const redes = new Set();
  $("a[href]").each((_, el) => {
    const href = ($(el).attr("href") || "").trim();
    if (/^tel:/i.test(href) || /^mailto:/i.test(href)) return void contatos.add(href);
    let u;
    try {
      u = new URL(href, base);
    } catch {
      return;
    }
    const h = u.hostname.replace(/^www\./, "");
    if (/(^|\.)wa\.me$|whatsapp\.com$/.test(h)) return void contatos.add(u.toString());
    if (/(instagram|facebook|linkedin|youtube|tiktok|x|twitter|pinterest)\.com$/.test(h))
      return void redes.add(u.toString());
    if (h !== base.hostname.replace(/^www\./, "")) return;
    if (/\.(pdf|jpe?g|png|gif|webp|zip|docx?|xlsx?|mp4|mp3)$/i.test(u.pathname)) return;
    if (/wp-(admin|login|json)|feed|xmlrpc|\?/i.test(u.pathname + u.search)) return;
    u.hash = "";
    const texto = limparTexto($(el).text());
    internos.push({ url: u.toString(), texto, noMenu: $(el).closest("nav,header").length > 0 });
  });
  return { internos, contatos: [...contatos], redes: [...redes] };
}

function coletarImagens($, base, paginaUrl) {
  const lista = [];
  const add = (src, alt, contexto, peso = 0) => {
    if (!src || src.startsWith("data:")) return;
    try {
      const u = new URL(src, base);
      if (!/^https?:$/.test(u.protocol)) return;
      lista.push({ url: u.toString(), alt: limparTexto(alt || ""), contexto, pagina: paginaUrl, peso });
    } catch {}
  };
  const og = $('meta[property="og:image"]').attr("content");
  add(og, "imagem de compartilhamento", "og:image", 1);
  $("img").each((_, el) => {
    const $el = $(el);
    const srcset = $el.attr("srcset") || $el.attr("data-srcset") || "";
    const maior = srcset
      .split(",")
      .map((s) => s.trim().split(/\s+/))
      .filter((p) => p[0])
      .sort((a, b) => parseInt(b[1] || "0") - parseInt(a[1] || "0"))[0]?.[0];
    const src = $el.attr("data-src") || $el.attr("data-lazy-src") || maior || $el.attr("src");
    const alt = $el.attr("alt") || "";
    const ehLogo = /logo|marca|brand/i.test(src + " " + alt + " " + ($el.attr("class") || "") + " " + ($el.parent().attr("class") || ""));
    const titulo = limparTexto($el.closest("section,div").find("h1,h2,h3").first().text()).slice(0, 80);
    add(src, alt, ehLogo ? "provável logo" : titulo ? `perto de "${titulo}"` : "", ehLogo ? 3 : 0);
  });
  $("[style*='background']").each((_, el) => {
    const m = ($(el).attr("style") || "").match(/url\(['"]?([^'")]+)['"]?\)/);
    if (m) add(m[1], "", "imagem de fundo", 0);
  });
  return lista;
}

function coletarEstilos($, base) {
  const cssInline = $("style").map((_, el) => $(el).html()).get().join("\n");
  const atributos = $("[style]").map((_, el) => $(el).attr("style")).get().join(";");
  const folhas = $('link[rel="stylesheet"][href]')
    .map((_, el) => {
      try {
        return new URL($(el).attr("href"), base).toString();
      } catch {
        return null;
      }
    })
    .get()
    .filter(Boolean);
  const googleFonts = folhas.filter((u) => u.includes("fonts.googleapis.com"));
  return { css: cssInline + "\n" + atributos, folhas: folhas.filter((u) => !u.includes("fonts.googleapis.com")), googleFonts };
}

function analisarCss(cssBruto) {
  // ignora as paletas padrão do WordPress, que não são da marca
  const css = cssBruto.replace(/--wp--preset--[^;]+;/g, "").replace(/\.has-[\w-]+-(?:color|background-color)\s*\{[^}]*\}/g, "");
  const cores = new Map();
  for (const m of css.matchAll(/#([0-9a-f]{6}|[0-9a-f]{3})\b/gi)) {
    let h = m[1].toLowerCase();
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    cores.set("#" + h, (cores.get("#" + h) || 0) + 1);
  }
  const variaveis = [...css.matchAll(/--[\w-]*(?:color|cor)[\w-]*\s*:\s*(#[0-9a-f]{3,8})/gi)].map((m) => m[0]);
  const fontes = new Map();
  for (const m of css.matchAll(/font-family\s*:\s*([^;}{]+)/gi)) {
    const f = m[1].split(",")[0].replace(/["']/g, "").trim();
    if (f && !/^(inherit|initial|var\(|sans-serif|serif|monospace|eicons|font ?awesome|dashicons)/i.test(f))
      fontes.set(f, (fontes.get(f) || 0) + 1);
  }
  const ordenar = (m, n) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);
  return {
    cores: ordenar(cores, 14).map(([c, n]) => `${c} (${n}x)`),
    variaveisDeCor: [...new Set(variaveis)].slice(0, 20),
    fontes: ordenar(fontes, 6).map(([f]) => f),
  };
}

function pesoFolha(u) {
  if (/elementor\/css\/post-|global|custom|theme|style\.css|main|app/i.test(u)) return 2;
  if (/wp-includes|block-library|plugins\/(?!elementor)/i.test(u)) return 0;
  return 1;
}

async function lerPagina(url) {
  const r = await baixar(url, { aceitar: "text/html,application/xhtml+xml" });
  if (r.status >= 400 || !ehHtml(r.tipo)) throw new Error(`Página indisponível (${r.status})`);
  const $ = cheerio.load(r.corpo.toString("utf8"));
  const base = r.url;
  const embeds = $("iframe[src]")
    .map((_, el) => $(el).attr("src"))
    .get()
    .filter((s) => /google\.com\/maps|youtube\.com|youtu\.be|vimeo\.com/.test(s || ""));
  const imagens = coletarImagens($, base, base.toString());
  const estilos = coletarEstilos($, base);
  const links = coletarLinks($, base);
  const formularios = $("form").length;
  $("script,style,noscript,svg,iframe,template").remove();
  $("nav,[role=navigation],.menu,.elementor-nav-menu--dropdown").remove();
  return {
    url: base.toString(),
    titulo: limparTexto($("title").first().text()),
    descricao: $('meta[name="description"]').attr("content") || "",
    idioma: $("html").attr("lang") || "",
    texto: extrairTextos($),
    imagens,
    estilos,
    links,
    embeds,
    formularios,
  };
}

/** Extrai tudo e salva as imagens em <pasta>/img. */
export async function extrairSite(urlInformada, pasta, aoProgredir = () => {}) {
  const inicio = validarUrl(urlInformada);
  aoProgredir("Lendo a página inicial");
  const home = await lerPagina(inicio);

  // páginas internas: prioriza as do menu
  const vistos = new Set([home.url.replace(/\/$/, "")]);
  const candidatas = [...home.links.internos].sort((a, b) => Number(b.noMenu) - Number(a.noMenu));
  const extras = [];
  for (const c of candidatas) {
    if (extras.length >= MAX_PAGINAS_EXTRAS) break;
    const chave = c.url.replace(/\/$/, "");
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    aoProgredir(`Lendo páginas internas (${extras.length + 1}/${MAX_PAGINAS_EXTRAS})`);
    try {
      extras.push(await lerPagina(c.url));
    } catch {}
  }
  const paginas = [home, ...extras];

  // cores e fontes (CSS inline + até 4 folhas de estilo)
  aoProgredir("Identificando cores e fontes");
  let css = paginas.map((p) => p.estilos.css).join("\n");
  // prioriza folhas de estilo do tema/construtor (onde costumam estar as cores da marca)
  const folhas = [...new Set(paginas.flatMap((p) => p.estilos.folhas))]
    .sort((a, b) => pesoFolha(b) - pesoFolha(a))
    .slice(0, 5);
  for (const f of folhas) {
    try {
      const r = await baixar(f, { limiteBytes: 1_500_000, aceitar: "text/css" });
      if (r.status < 400) css += "\n" + r.corpo.toString("utf8");
    } catch {}
  }
  const identidade = analisarCss(css);
  const googleFonts = [...new Set(paginas.flatMap((p) => p.estilos.googleFonts))];

  // imagens
  aoProgredir("Baixando imagens");
  const pastaImg = path.join(pasta, "img");
  fs.mkdirSync(pastaImg, { recursive: true });
  const unicas = new Map();
  for (const img of paginas.flatMap((p) => p.imagens)) {
    const chave = img.url.replace(/-\d+x\d+(?=\.\w+$)/, ""); // variações do WordPress
    if (!unicas.has(chave) || img.peso > unicas.get(chave).peso) unicas.set(chave, img);
  }
  const imagens = [];
  const ordenadas = [...unicas.values()].sort((a, b) => b.peso - a.peso);
  for (const img of ordenadas) {
    if (imagens.length >= MAX_IMAGENS) break;
    try {
      const r = await baixar(img.url, { limiteBytes: 6_000_000, aceitar: "image/*" });
      if (r.status >= 400 || !r.tipo.startsWith("image/")) continue;
      let dim;
      try {
        dim = imageSize(r.corpo);
      } catch {
        continue;
      }
      const ext = { jpg: "jpg", jpeg: "jpg", png: "png", webp: "webp", gif: "gif", svg: "svg", avif: "avif" }[dim.type];
      if (!ext) continue;
      const ehLogo = img.contexto === "provável logo";
      if (!ehLogo && ext !== "svg" && (dim.width < 160 || dim.height < 120)) continue;
      const nome = `img/${String(imagens.length + 1).padStart(2, "0")}.${ext}`;
      fs.writeFileSync(path.join(pasta, nome), r.corpo);
      imagens.push({ arquivo: nome, largura: dim.width, altura: dim.height, alt: img.alt, contexto: img.contexto, pagina: img.pagina });
    } catch {}
  }

  return {
    urlOriginal: home.url,
    dominio: new URL(home.url).hostname.replace(/^www\./, ""),
    titulo: home.titulo,
    descricao: home.descricao,
    idioma: home.idioma || "pt-BR",
    paginas: paginas.map((p) => ({ url: p.url, titulo: p.titulo, descricao: p.descricao, texto: p.texto, formularios: p.formularios })),
    menu: [...new Map(home.links.internos.filter((l) => l.noMenu && l.texto).map((l) => [l.url, { texto: l.texto, url: l.url }])).values()].slice(0, 12),
    contatos: [...new Set(paginas.flatMap((p) => p.links.contatos))].slice(0, 12),
    redesSociais: [...new Set(paginas.flatMap((p) => p.links.redes))].slice(0, 10),
    embeds: [...new Set(paginas.flatMap((p) => p.embeds))].slice(0, 6),
    identidade: { ...identidade, googleFonts },
    imagens,
  };
}
