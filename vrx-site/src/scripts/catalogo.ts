/**
 * Catálogo: filtro por tipo (com contagem anunciada por aria-live) e botões "Adicionar ao orçamento".
 * Sem JavaScript, os filtros ficam ocultos e cada botão é um link para /orcamento?produto=...
 */
import { lerLista, alternar } from "./lista-orcamento";

function iniciar() {
  const catalogo = document.querySelector<HTMLElement>("[data-catalogo]");
  if (!catalogo) return;
  const itens = [...catalogo.querySelectorAll<HTMLElement>("[data-item]")];
  const filtros = [...document.querySelectorAll<HTMLButtonElement>("[data-filtro]")];
  const contagem = document.querySelector<HTMLElement>("[data-contagem]");
  const barra = document.querySelector<HTMLElement>("[data-barra-lista]");
  const total = document.querySelector<HTMLElement>("[data-total-lista]");
  const plural = (n: number, s: string, p: string) => `${n} ${n === 1 ? s : p}`;

  // ----- filtros -----
  filtros.forEach((f) =>
    f.addEventListener("click", () => {
      const grupo = f.dataset["filtro"];
      filtros.forEach((b) => b.setAttribute("aria-pressed", String(b === f)));
      let visiveis = 0;
      for (const it of itens) {
        const mostrar = grupo === "todos" || it.dataset["item"] === grupo;
        it.hidden = !mostrar;
        if (mostrar) {
          visiveis++;
          it.classList.add("is-visible"); // garante a entrada mesmo se o item ainda não tinha sido observado
        }
      }
      if (contagem) contagem.textContent = `${plural(visiveis, "equipamento", "equipamentos")}${grupo === "todos" ? "" : ` em ${f.textContent?.trim().toLowerCase()}`}`;
    }),
  );

  // ----- lista de orçamento: o link vira um botão de alternar (aria-pressed) -----
  const botoes = [...catalogo.querySelectorAll<HTMLAnchorElement>("a[data-adicionar]")].map((a) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = a.className;
    b.dataset["adicionar"] = a.dataset["adicionar"]!;
    b.append(...a.childNodes);
    a.replaceWith(b);
    b.addEventListener("click", () => {
      alternar(b.dataset["adicionar"]!);
    });
    return b;
  });

  const atualizar = () => {
    const lista = lerLista();
    botoes.forEach((b) => b.setAttribute("aria-pressed", String(lista.includes(b.dataset["adicionar"]!))));
    if (barra) barra.hidden = lista.length === 0;
    if (total) total.textContent = plural(lista.length, "item", "itens");
  };
  const ctl = new AbortController();
  document.addEventListener("vrx:lista", atualizar, { signal: ctl.signal });
  document.addEventListener("astro:before-swap", () => ctl.abort(), { once: true });
  atualizar();
}

document.addEventListener("astro:page-load", iniciar);
