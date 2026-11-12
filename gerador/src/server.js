import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import express from "express";
import { config } from "./config.js";
import * as store from "./store.js";
import { validarUrl, ErroUsuario } from "./rede.js";
import { extrairSite } from "./extrair.js";
import { miniaturas, printsPrevia } from "./render.js";
import { gerarSite } from "./gerar.js";
import { verificarLimites, verificarRobo } from "./limites.js";
import { criarCheckout, pagamentoAprovado, assinaturaValida, obterPagamento } from "./pagamento.js";
import { montarZip } from "./pacote.js";

const aqui = path.dirname(fileURLToPath(import.meta.url));
const publico = path.join(aqui, "..", "public");
const app = express();
app.set("trust proxy", 1);
app.disable("x-powered-by");
app.use(express.json({ limit: "20kb" }));

// Cabeçalhos de segurança
app.use((req, res, next) => {
  res.set({
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
  });
  next();
});

// ---------------- Fila de geração ----------------
const fila = [];
let rodando = 0;
const SIMULTANEOS = 2;

function enfileirar(id) {
  fila.push(id);
  proximo();
}
function proximo() {
  while (rodando < SIMULTANEOS && fila.length) {
    const id = fila.shift();
    rodando++;
    processar(id).finally(() => {
      rodando--;
      proximo();
    });
  }
}

async function processar(id) {
  const pasta = store.pastaProjeto(id);
  const etapa = (status, texto) => store.atualizar(id, { status, etapa: texto });
  const inicio = Date.now();
  try {
    const projeto = store.obter(id);
    etapa("extraindo", "Lendo o seu site atual");
    const dados = await extrairSite(projeto.url, pasta, (t) => etapa("extraindo", t));
    fs.writeFileSync(path.join(pasta, "conteudo.json"), JSON.stringify(dados, null, 1));
    if (!dados.paginas[0]?.texto || dados.paginas[0].texto.length < 40)
      throw new ErroUsuario("Não encontramos conteúdo suficiente nesse site (ele pode depender de JavaScript para mostrar o texto).");

    etapa("gerando", "Criando o novo design (leva de 2 a 5 minutos)");
    const minis = await miniaturas(pasta, dados.imagens);
    const { html, uso } = await gerarSite(dados, minis);
    fs.writeFileSync(path.join(pasta, "index.html"), html);

    etapa("renderizando", "Preparando a pré-visualização");
    const previas = await printsPrevia(pasta, `PRÉVIA • ${config.nomeProduto.toUpperCase()}`);
    store.atualizar(id, {
      status: "pronto",
      etapa: "Pronto",
      previas,
      uso,
      tituloSite: dados.titulo,
      duracaoSeg: Math.round((Date.now() - inicio) / 1000),
    });
  } catch (e) {
    console.error(`[${id}]`, e);
    const msg = e instanceof ErroUsuario ? e.message : /ENDERECO_BLOQUEADO|ENOTFOUND|ECONNREFUSED|Página indisponível|fetch failed|timeout/i.test(String(e?.message) + String(e?.cause?.code))
      ? "Não conseguimos acessar esse site. Confira o endereço e se ele está no ar."
      : "Algo deu errado ao gerar o seu site. Tente novamente em alguns minutos.";
    store.atualizar(id, { status: "erro", etapa: msg, erroInterno: String(e?.message || e).slice(0, 500) });
  }
}

// Ao reiniciar, retoma o que ficou pela metade
for (const p of store.listar()) {
  if (["fila", "extraindo", "gerando", "renderizando"].includes(p.status)) enfileirar(p.id);
}

// ---------------- API ----------------
const emailValido = (e) => typeof e === "string" && e.length < 160 && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e);

app.get("/api/config", (req, res) => {
  res.json({ nome: config.nomeProduto, preco: config.preco, turnstileSiteKey: config.turnstileSiteKey || null });
});

app.post("/api/projetos", async (req, res) => {
  try {
    const { url, email, aceite, turnstile } = req.body || {};
    if (!aceite) throw new ErroUsuario("Confirme que você é o responsável pelo site.");
    if (!emailValido(email)) throw new ErroUsuario("Informe um e-mail válido.");
    const alvo = validarUrl(url);
    if (!(await verificarRobo(turnstile, req.ip))) throw new ErroUsuario("Não foi possível confirmar que você não é um robô.");
    const dominio = alvo.hostname.replace(/^www\./, "");

    // Mesmo domínio gerado recentemente: reaproveita sem custo de IA (cópia separada por cliente)
    const existente = store.buscarPorDominio(dominio, config.cacheDias);
    if (existente && existente.status === "pronto") {
      const novo = store.criarProjeto({
        url: alvo.toString(), dominio, email, ip: req.ip, reaproveitado: existente.id,
        status: "pronto", etapa: "Pronto", previas: existente.previas, tituloSite: existente.tituloSite,
        uso: { custoUsd: 0, modelo: "reaproveitado" },
      });
      fs.cpSync(store.pastaProjeto(existente.id), store.pastaProjeto(novo.id), {
        recursive: true,
        filter: (src) => !src.endsWith("projeto.json"),
      });
      return res.json({ id: novo.id });
    }

    const bloqueio = verificarLimites(req.ip);
    if (bloqueio) return res.status(429).json({ erro: bloqueio });

    const projeto = store.criarProjeto({ url: alvo.toString(), dominio, email, ip: req.ip });
    enfileirar(projeto.id);
    res.json({ id: projeto.id });
  } catch (e) {
    if (e instanceof ErroUsuario) return res.status(400).json({ erro: e.message });
    console.error(e);
    res.status(500).json({ erro: "Erro inesperado. Tente novamente." });
  }
});

function visaoPublica(p) {
  return {
    id: p.id,
    status: p.status,
    etapa: p.etapa,
    dominio: p.dominio,
    previas: p.status === "pronto" ? (p.previas || []).map((r) => path.basename(r, ".jpg")) : [],
    pago: !!p.pago,
    preco: config.preco,
    posicaoFila: p.status === "fila" ? fila.indexOf(p.id) + 1 : 0,
  };
}

app.get("/api/projetos/:id", (req, res) => {
  const p = store.obter(req.params.id);
  if (!p) return res.status(404).json({ erro: "Projeto não encontrado" });
  res.set("Cache-Control", "no-store").json(visaoPublica(p));
});

// Imagens da prévia (com marca d'água). O HTML gerado nunca é servido antes do pagamento.
app.get("/api/projetos/:id/previa/:nome", (req, res) => {
  const p = store.obter(req.params.id);
  const nome = req.params.nome;
  if (!p || p.status !== "pronto" || !["desktop", "celular"].includes(nome)) return res.sendStatus(404);
  res.set({ "Cache-Control": "private, max-age=600", "Content-Disposition": "inline" });
  res.sendFile(path.join(store.pastaProjeto(p.id), "previa", `${nome}.jpg`));
});

app.post("/api/projetos/:id/checkout", async (req, res) => {
  const p = store.obter(req.params.id);
  if (!p || p.status !== "pronto") return res.status(404).json({ erro: "Projeto não encontrado" });
  try {
    const { preferenciaId, url } = await criarCheckout(p);
    store.atualizar(p.id, { preferenciaId });
    res.json({ url });
  } catch (e) {
    console.error(e);
    res.status(502).json({ erro: "Não foi possível abrir o pagamento agora. Tente novamente." });
  }
});

async function liberarCompra(projetoId, pagamentoId) {
  const p = store.obter(projetoId);
  if (!p) return null;
  if (p.pago && p.pagamentoId === String(pagamentoId)) return p;
  if (!(await pagamentoAprovado(pagamentoId, projetoId))) return null;
  return store.atualizar(projetoId, {
    pago: true,
    pagamentoId: String(pagamentoId),
    pagoEm: p.pagoEm || new Date().toISOString(),
    tokenDownload: p.tokenDownload || store.novoToken(),
  });
}

// Retorno do checkout: o navegador do comprador traz o payment_id; confirmamos na API do Mercado Pago.
app.post("/api/projetos/:id/confirmar", async (req, res) => {
  try {
    const pagamentoId = String(req.body?.pagamentoId || "");
    const p = await liberarCompra(req.params.id, pagamentoId);
    if (!p) return res.json({ pago: false });
    res.json({ pago: true, download: `/download/${p.id}/${p.tokenDownload}` });
  } catch (e) {
    console.error(e);
    res.status(502).json({ erro: "Não foi possível confirmar o pagamento agora." });
  }
});

// Webhook: confirma o pagamento mesmo se o comprador fechar a aba antes de voltar.
app.post("/api/webhook/mercadopago", async (req, res) => {
  const tipo = req.query.type || req.query.topic || req.body?.type;
  const dataId = req.query["data.id"] || req.query.id || req.body?.data?.id;
  if (tipo !== "payment" || !dataId) return res.sendStatus(200);
  if (!assinaturaValida(req, dataId)) return res.sendStatus(401);
  try {
    const pag = await obterPagamento(dataId);
    if (pag.external_reference) await liberarCompra(pag.external_reference, dataId);
  } catch (e) {
    console.error("webhook", e);
    return res.sendStatus(500); // o Mercado Pago tenta de novo
  }
  res.sendStatus(200);
});

app.get("/download/:id/:token", async (req, res) => {
  const p = store.obter(req.params.id);
  const ok =
    p && p.pago && p.tokenDownload &&
    p.tokenDownload.length === req.params.token.length &&
    crypto.timingSafeEqual(Buffer.from(p.tokenDownload), Buffer.from(req.params.token));
  if (!ok) return res.status(404).send("Link inválido.");
  const zip = await montarZip(store.pastaProjeto(p.id), p);
  res.set({
    "Content-Type": "application/zip",
    "Content-Disposition": `attachment; filename="novo-site-${p.dominio.replace(/[^a-z0-9.-]/gi, "")}.zip"`,
    "Cache-Control": "no-store",
  });
  res.send(zip);
});

// ---------------- Painel de custos ----------------
app.get("/admin", (req, res) => {
  const senha = req.get("x-admin-senha") || req.query.senha;
  if (!config.adminSenha || senha !== config.adminSenha) return res.status(401).send("Acesso negado");
  const todos = store.listar();
  const gerados = todos.filter((p) => !p.reaproveitado && p.uso);
  const custoUsd = gerados.reduce((s, p) => s + (p.uso?.custoUsd || 0), 0);
  const vendas = todos.filter((p) => p.pago);
  const receita = vendas.length * config.preco;
  const linhas = todos.slice(0, 200).map((p) =>
    `<tr><td>${p.criadoEm.slice(0, 16).replace("T", " ")}</td><td>${p.dominio}</td><td>${p.status}</td><td>${p.reaproveitado ? "cache" : "US$ " + (p.uso?.custoUsd || 0).toFixed(3)}</td><td>${p.uso?.output_tokens || "-"}</td><td>${p.pago ? "✅" : ""}</td></tr>`).join("");
  res.send(`<!doctype html><meta charset="utf-8"><title>Painel</title><style>body{font:14px system-ui;margin:24px}td,th{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}.k{display:inline-block;margin:0 24px 16px 0}.k b{display:block;font-size:22px}</style>
  <h1>Painel</h1>
  <div class="k">Prévias geradas<b>${gerados.length}</b></div>
  <div class="k">Custo com IA<b>US$ ${custoUsd.toFixed(2)} ≈ R$ ${(custoUsd * config.cotacaoDolar).toFixed(2)}</b></div>
  <div class="k">Custo médio/prévia<b>R$ ${gerados.length ? ((custoUsd / gerados.length) * config.cotacaoDolar).toFixed(2) : "0,00"}</b></div>
  <div class="k">Vendas<b>${vendas.length}</b></div>
  <div class="k">Receita bruta<b>R$ ${receita.toFixed(2)}</b></div>
  <div class="k">Conversão<b>${todos.length ? ((vendas.length / todos.length) * 100).toFixed(1) : 0}%</b></div>
  <table><tr><th>Data</th><th>Domínio</th><th>Status</th><th>Custo IA</th><th>Tokens saída</th><th>Pago</th></tr>${linhas}</table>`);
});

// ---------------- Páginas ----------------
app.get("/p/:id", (req, res) => res.sendFile(path.join(publico, "previa.html")));
app.use(express.static(publico, { extensions: ["html"], maxAge: "1h" }));

app.listen(config.porta, () => {
  console.log(`${config.nomeProduto} rodando em ${config.baseUrl} (porta ${config.porta})${config.modoDemo ? " [MODO DEMO]" : ""}`);
});
