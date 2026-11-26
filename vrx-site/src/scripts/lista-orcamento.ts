/**
 * Lista de orçamento: os equipamentos que a pessoa marcou no catálogo.
 * Fica só no navegador (localStorage), é essencial para a função pedida pelo usuário
 * e não contém dados pessoais (apenas os códigos dos produtos).
 */
const CHAVE = "vrx-lista-orcamento";
const IDS_VALIDOS = new Set(["sfnn", "swnn", "sden-sdgn", "ssen", "ssg030", "stewx"]);

export function lerLista(): string[] {
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE) ?? "[]") as unknown;
    return Array.isArray(bruto) ? bruto.filter((x): x is string => typeof x === "string" && IDS_VALIDOS.has(x)) : [];
  } catch {
    return [];
  }
}

export function salvarLista(ids: string[]): void {
  const limpa = [...new Set(ids.filter((x) => IDS_VALIDOS.has(x)))];
  try {
    if (limpa.length) localStorage.setItem(CHAVE, JSON.stringify(limpa));
    else localStorage.removeItem(CHAVE);
  } catch {
    /* navegação privada: a lista vale só nesta página */
  }
  document.dispatchEvent(new CustomEvent("vrx:lista", { detail: limpa }));
}

export function alternar(id: string): boolean {
  const atual = lerLista();
  const tem = atual.includes(id);
  salvarLista(tem ? atual.filter((x) => x !== id) : [...atual, id]);
  return !tem;
}
