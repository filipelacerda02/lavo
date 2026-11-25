/**
 * BUSCADOR UNIFICADO DE UNIDADES LAVÔ
 * Engine original do lavo.eco.br, portada para TypeScript com a mesma lógica:
 *  - dados em TSV (src/data/unidades.tsv): Logradouro | País | Bairro | Cidade | UF | CEP
 *  - busca por logradouro, bairro, cidade, UF, nome do estado ou CEP (sem acentos)
 *  - 8 unidades por página
 *  - mapa Google My Maps reposicionado na cidade da 1ª unidade (geocodificação Nominatim)
 *  - botões "Como chegar" (Google Maps) e "Waze"
 * Diferenças: os dados vêm embutidos no JavaScript da página (e não num <script> do HTML),
 * o mapa e a geocodificação só rodam com consentimento "Funcionais" (LGPD), e a busca aceita ?q=.
 */
import tsv from "@/data/unidades.tsv?raw";
import { permitido, quandoPermitido, salvarConsentimento, obterConsentimento } from "./consentimento";

const mapaBaseUrl = "https://www.google.com/maps/d/u/1/embed?mid=1C070ks3zDcTEq7Z2qIbjW17pjGOd7MQ&ehbc=2E312F&noprof=1";

export const nomeEstados: Record<string, string> = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia",
  CE: "Ceará", DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás",
  MA: "Maranhão", MT: "Mato Grosso", MS: "Mato Grosso do Sul", MG: "Minas Gerais",
  PA: "Pará", PB: "Paraíba", PR: "Paraná", PE: "Pernambuco", PI: "Piauí",
  RJ: "Rio de Janeiro", RN: "Rio Grande do Norte", RS: "Rio Grande do Sul",
  RO: "Rondônia", RR: "Roraima", SC: "Santa Catarina", SP: "São Paulo",
  SE: "Sergipe", TO: "Tocantins",
};

interface Unidade { logradouro: string; bairro: string; cidade: string; uf: string; cep: string }

function esc(s: string): string {
  return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
function norm(s: string): string {
  return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}
function formatarCep(c?: string): string {
  const d = (c || "").replace(/\D/g, "");
  return d.length === 8 ? d.slice(0, 5) + "-" + d.slice(5) : (c || "").trim();
}

// Formato: Logradouro(0) | País(1) | Bairro(2) | Cidade(3) | UF(4) | CEP(5)
export function processarTSV(texto: string): Unidade[] {
  const lista: Unidade[] = [];
  const linhas = texto.trim().split("\n");
  if (linhas.length < 2) return lista;
  for (let i = 1; i < linhas.length; i++) {
    const cols = linhas[i]!.split("\t").map((c) => c.trim());
    if (cols.length >= 5 && cols[4]) {
      lista.push({ logradouro: cols[0] || "", bairro: cols[2] || "", cidade: cols[3] || "", uf: cols[4].toUpperCase(), cep: formatarCep(cols[5]) });
    }
  }
  return lista;
}

export const todasUnidades = processarTSV(tsv);

function iniciar() {
  const elBusca = document.getElementById("lavo-input-busca") as HTMLInputElement | null;
  const elListaCards = document.getElementById("lavo-lista-cards");
  if (!elBusca || !elListaCards) return;
  const elMapaWrap = document.getElementById("lavo-mapa")!;
  const statusTexto = document.getElementById("lavo-status")!;
  const elContador = document.getElementById("lavo-contador")!;
  const elBtnPrev = document.getElementById("lavo-btn-prev") as HTMLButtonElement;
  const elBtnNext = document.getElementById("lavo-btn-next") as HTMLButtonElement;
  const elInfoPagina = document.getElementById("lavo-info-pagina")!;

  let unidadesFiltradas = todasUnidades;
  let paginaAtual = 1;
  const itensPorPagina = 8;
  let mapFocusDebounce: ReturnType<typeof setTimeout> | undefined;
  let elMapa: HTMLIFrameElement | null = null;
  let urlMapa = mapaBaseUrl;

  // ----- mapa só com consentimento "Funcionais" -----
  function montarMapa() {
    if (elMapa) return;
    elMapa = document.createElement("iframe");
    elMapa.id = "lavo-iframe-mapa";
    elMapa.title = "Mapa das unidades Lavô (Google Maps)";
    elMapa.loading = "lazy";
    elMapa.allowFullscreen = true;
    elMapa.referrerPolicy = "strict-origin-when-cross-origin";
    elMapa.className = "size-full border-0";
    elMapa.src = urlMapa;
    elMapaWrap.replaceChildren(elMapa);
  }
  quandoPermitido("funcionais", montarMapa);
  document.getElementById("lavo-carregar-mapa")?.addEventListener("click", () => {
    const atual = obterConsentimento()?.categorias ?? { funcionais: false, analiticos: false, marketing: false };
    salvarConsentimento({ ...atual, funcionais: true }, "carregar_mapa");
    montarMapa();
  });

  function aoDigitar() {
    aplicarFiltros();
    clearTimeout(mapFocusDebounce);
    mapFocusDebounce = setTimeout(() => {
      const termo = elBusca!.value.trim();
      if (termo.length > 2 && unidadesFiltradas.length > 0) {
        const u = unidadesFiltradas[0]!;
        focarMapa(`${u.cidade}, ${nomeEstados[u.uf] || u.uf}, Brasil`, 12);
      } else if (!termo) {
        urlMapa = mapaBaseUrl;
        if (elMapa) elMapa.src = mapaBaseUrl;
      }
    }, 1200);
  }
  elBusca.addEventListener("input", aoDigitar);

  function aplicarFiltros() {
    const termo = norm(elBusca!.value.trim());
    unidadesFiltradas = todasUnidades.filter((u) => {
      if (!termo) return true;
      const ehBuscaCep = /^[\d.\-\s]+$/.test(termo);
      const termoCep = termo.replace(/\D/g, "");
      if (ehBuscaCep) return termoCep.length > 0 && u.cep.replace(/\D/g, "").indexOf(termoCep) !== -1;
      const estadoNome = norm(nomeEstados[u.uf] || "");
      return norm(u.logradouro).includes(termo) || norm(u.bairro).includes(termo) || norm(u.cidade).includes(termo) || norm(u.uf) === termo || estadoNome.includes(termo);
    });
    paginaAtual = 1;
    renderizar();
  }

  function focarMapa(termo: string, zoom: number) {
    if (!permitido("funcionais") || !elMapa) return; // sem consentimento, não consulta serviços de terceiros
    statusTexto.textContent = "Atualizando localização no mapa...";
    fetch("https://nominatim.openstreetmap.org/search?format=json&q=" + encodeURIComponent(termo))
      .then((res) => res.json() as Promise<Array<{ lat: string; lon: string }>>)
      .then((data) => {
        if (data && data.length > 0) {
          urlMapa = `${mapaBaseUrl}&ll=${data[0]!.lat},${data[0]!.lon}&z=${zoom}`;
          if (elMapa) elMapa.src = urlMapa;
        }
        statusTexto.textContent = "";
      })
      .catch(() => (statusTexto.textContent = ""));
  }

  function renderizar() {
    elListaCards!.innerHTML = "";
    elContador.textContent = "+" + unidadesFiltradas.length + " unidades encontradas";

    if (unidadesFiltradas.length === 0) {
      elListaCards!.innerHTML = '<p class="col-span-full py-10 text-center text-tinta-suave">Nenhuma unidade encontrada para esta busca.</p>';
      elInfoPagina.textContent = "Página 0 de 0";
      elBtnPrev.disabled = true;
      elBtnNext.disabled = true;
      return;
    }

    const totalPaginas = Math.ceil(unidadesFiltradas.length / itensPorPagina);
    const inicio = (paginaAtual - 1) * itensPorPagina;
    const itens = unidadesFiltradas.slice(inicio, inicio + itensPorPagina);

    itens.forEach((u, i) => {
      const enderecoCompleto = u.logradouro + (u.bairro ? " - " + u.bairro : "") + ", " + u.cidade + " - " + u.uf + (u.cep ? ", CEP " + u.cep : "");
      const encodedGoogle = encodeURIComponent(enderecoCompleto);
      const encodedWaze = encodeURIComponent(u.logradouro + ", " + u.cidade + " - " + u.uf);
      const card = document.createElement("li");
      card.className = "lavo-card";
      card.style.setProperty("--d", String(i * 45));
      card.innerHTML =
        '<div class="min-w-0"><h3 class="lavo-card-title">Lavô ' + esc(u.cidade) + "</h3>" +
        '<div class="lavo-card-sub">' + esc(u.bairro || u.cidade) + " — " + esc(u.uf) + "</div>" +
        '<p class="lavo-card-address">' + esc(enderecoCompleto) + "</p></div>" +
        '<div class="lavo-card-actions">' +
        '<a class="lavo-btn lavo-btn-primary" href="https://www.google.com/maps/dir/?api=1&destination=' + encodedGoogle + '" target="_blank" rel="noopener">Como chegar<span class="sr-only"> à Lavô ' + esc(u.cidade) + " (abre o Google Maps)</span></a>" +
        '<a class="lavo-btn lavo-btn-secondary" href="https://www.waze.com/ul?q=' + encodedWaze + '&navigate=yes" target="_blank" rel="noopener">Waze<span class="sr-only"> (abre em nova aba)</span></a>' +
        "</div>";
      elListaCards!.appendChild(card);
    });

    elInfoPagina.textContent = "Página " + paginaAtual + " de " + totalPaginas;
    elBtnPrev.disabled = paginaAtual === 1;
    elBtnNext.disabled = paginaAtual === totalPaginas;
  }

  elBtnPrev.addEventListener("click", () => {
    if (paginaAtual > 1) { paginaAtual--; renderizar(); elListaCards!.scrollIntoView({ block: "nearest" }); }
  });
  elBtnNext.addEventListener("click", () => {
    const totalPaginas = Math.ceil(unidadesFiltradas.length / itensPorPagina);
    if (paginaAtual < totalPaginas) { paginaAtual++; renderizar(); elListaCards!.scrollIntoView({ block: "nearest" }); }
  });

  // sugestões e links por estado
  const buscarPor = (termo: string) => { elBusca!.value = termo; aoDigitar(); };
  document.querySelectorAll<HTMLElement>("[data-lavo-sugestao]").forEach((el) =>
    el.addEventListener("click", (e) => {
      e.preventDefault();
      buscarPor(el.dataset["lavoSugestao"]!);
      if (!el.closest("#lavo-store-locator")) document.getElementById("lavo-store-locator")?.scrollIntoView({ behavior: "smooth" });
    }),
  );

  renderizar();
  const q = new URLSearchParams(location.search).get("q");
  if (q) buscarPor(q.slice(0, 80));
}

document.addEventListener("astro:page-load", iniciar);
