/**
 * Formulário de orçamento: pré-seleciona os equipamentos da lista (ou de ?produto=), valida,
 * envia para /api/orcamento (Turnstile + limite + criptografia na borda) e monta a alternativa
 * pelo WhatsApp com a mesma lista.
 */
import { lerLista, salvarLista } from "./lista-orcamento";
import { montarTurnstile } from "./turnstile";

import { site } from "@/config/site";
const WHATS = site.whatsapp;
const EMAIL_OK = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function iniciar() {
  const form = document.getElementById("form-orcamento") as HTMLFormElement | null;
  if (!form) return;
  const resultado = document.getElementById("resultado-orcamento")!;
  const botao = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
  const whats = form.querySelector<HTMLAnchorElement>("[data-whats-orcamento]")!;
  const opcoes = [...form.querySelectorAll<HTMLInputElement>("[data-produto-opcao]")];
  const desafio = montarTurnstile("#turnstile-orcamento", form.dataset["turnstile"]);

  // ----- pré-seleção: lista do catálogo + ?produto= -----
  const daUrl = new URLSearchParams(location.search).getAll("produto");
  const iniciais = new Set([...lerLista(), ...daUrl]);
  opcoes.forEach((o) => (o.checked = iniciais.has(o.value)));
  const selecionados = () => opcoes.filter((o) => o.checked);
  const nomeDe = (o: HTMLInputElement) => o.closest("label")?.querySelector("strong")?.textContent?.trim() ?? o.value;

  // ----- WhatsApp com a mesma lista -----
  const atualizarWhats = () => {
    const itens = selecionados().map((o) => `• ${nomeDe(o)}`);
    const cidade = (form.elements.namedItem("cidade") as HTMLInputElement).value.trim();
    const uf = (form.elements.namedItem("uf") as HTMLSelectElement).value;
    const local = [cidade, uf].filter(Boolean).join(" - ");
    const texto = ["Olá! Quero um orçamento" + (itens.length ? " para:" : "."), ...itens, local ? `Cidade: ${local}` : ""].filter(Boolean).join("\n");
    whats.href = `https://wa.me/${WHATS}?text=${encodeURIComponent(texto)}`;
  };
  form.addEventListener("change", (e) => {
    if ((e.target as HTMLElement).matches("[data-produto-opcao]")) salvarLista(selecionados().map((o) => o.value));
    atualizarWhats();
  });
  form.addEventListener("input", atualizarWhats);
  atualizarWhats();

  // ----- validação e envio -----
  const erro = (campo: string, msg: string) => {
    const el = document.getElementById(`erro-${campo}`);
    const input = form.elements.namedItem(campo) as HTMLInputElement | null;
    if (el) el.textContent = msg;
    input?.setAttribute("aria-invalid", msg ? "true" : "false");
    return !msg;
  };
  const estilo = (classes: string[]) => (resultado.className = ["mt-6 rounded-2xl p-4 font-semibold empty:hidden", ...classes].join(" "));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    resultado.textContent = "";
    const v = (n: string) => ((form.elements.namedItem(n) as HTMLInputElement | null)?.value ?? "").trim();
    const digitos = v("telefone").replace(/\D/g, "");
    const ok = [
      erro("nome", v("nome").length < 3 ? "Informe o seu nome." : ""),
      erro("telefone", digitos.length < 10 || digitos.length > 13 ? "Informe um telefone com DDD." : ""),
      erro("email", v("email") && !EMAIL_OK.test(v("email")) ? "Confira o e-mail ou deixe em branco." : ""),
    ].every(Boolean);
    if (!ok) return (form.querySelector('[aria-invalid="true"]') as HTMLElement | null)?.focus();
    if (desafio.ativo && !desafio.token()) {
      resultado.textContent = "Confirme a verificação de segurança acima.";
      estilo(["bg-laranja-claro", "text-laranja-noite"]);
      return;
    }
    botao.disabled = true;
    try {
      const r = await fetch("/api/orcamento", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          nome: v("nome"), telefone: v("telefone"), email: v("email"), cidade: v("cidade"), uf: v("uf"),
          produtos: selecionados().map((o) => o.value), mensagem: v("mensagem"), turnstile: desafio.token(),
        }),
      });
      const j = (await r.json().catch(() => ({}))) as { protocolo?: string; erro?: string };
      if (!r.ok || !j.protocolo) throw new Error(j.erro || "Não foi possível enviar agora. Tente novamente ou use o WhatsApp.");
      form.reset();
      salvarLista([]);
      atualizarWhats();
      resultado.textContent = `Pedido recebido! Seu protocolo é ${j.protocolo}. A VRX vai entrar em contato pelo telefone informado.`;
      estilo(["bg-[#e5f6ec]", "text-[#0d5a2f]"]);
      resultado.focus();
    } catch (err) {
      resultado.textContent = (err as Error).message;
      estilo(["bg-red-50", "text-red-800"]);
    } finally {
      botao.disabled = false;
      desafio.reiniciar();
    }
  });
}

document.addEventListener("astro:page-load", iniciar);
