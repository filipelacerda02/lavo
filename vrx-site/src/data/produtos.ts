/**
 * Catálogo exibido no site atual ("Conheça alguns de nossos produtos").
 * Modelo e descrição são exatamente os das artes do site atual; nenhuma especificação técnica foi inventada.
 * Os tipos (lavadora/secadora) seguem os ícones de cada arte. A arte do SSG030 não tem legenda no site
 * atual: a descrição "Lavadora e secadora sobrepostas" vem dos ícones e da foto (confirmar com a VRX).
 */
import sfnn from "@/assets/img/produto-sfnn.png";
import swnn from "@/assets/img/produto-swnn.png";
import sdenSdgn from "@/assets/img/produto-sden-sdgn.png";
import ssen from "@/assets/img/produto-ssen.png";
import ssg030 from "@/assets/img/produto-ssg030.png";
import stewx from "@/assets/img/produto-stewx.png";

export type Tipo = "lavadora" | "secadora";

export interface Produto {
  id: string;
  modelo: string;
  descricao: string;
  tipos: readonly Tipo[];
  /** Agrupamento do filtro do catálogo */
  grupo: "lavadoras" | "secadoras" | "conjuntos";
  imagem: ImageMetadata;
  alt: string;
}

export const produtos: readonly Produto[] = [
  { id: "sfnn", modelo: "SFNN", descricao: "Lavadora front", tipos: ["lavadora"], grupo: "lavadoras", imagem: sfnn, alt: "Lavadora de carregamento frontal Speed Queen SFNN, branca, com porta circular" },
  { id: "swnn", modelo: "SWNN", descricao: "Top Load", tipos: ["lavadora"], grupo: "lavadoras", imagem: swnn, alt: "Lavadora de carregamento superior (top load) Speed Queen SWNN, branca" },
  { id: "sden-sdgn", modelo: "SDEN e SDGN", descricao: "Secadora front", tipos: ["secadora"], grupo: "secadoras", imagem: sdenSdgn, alt: "Secadora de carregamento frontal Speed Queen SDEN e SDGN, branca" },
  { id: "ssen", modelo: "SSEN", descricao: "Secadora elétrica", tipos: ["secadora"], grupo: "secadoras", imagem: ssen, alt: "Secadora elétrica Speed Queen SSEN, branca, com duas portas sobrepostas" },
  { id: "ssg030", modelo: "SSG030", descricao: "Lavadora e secadora sobrepostas", tipos: ["lavadora", "secadora"], grupo: "conjuntos", imagem: ssg030, alt: "Conjunto Speed Queen SSG030 de aço inox com secadora sobre lavadora" },
  { id: "stewx", modelo: "STEWX", descricao: "Stack lavadora e secadora", tipos: ["lavadora", "secadora"], grupo: "conjuntos", imagem: stewx, alt: "Conjunto empilhado Speed Queen STEWX, branco, com secadora sobre lavadora" },
] as const;

export const grupos = [
  { id: "todos", rotulo: "Todos" },
  { id: "lavadoras", rotulo: "Lavadoras" },
  { id: "secadoras", rotulo: "Secadoras" },
  { id: "conjuntos", rotulo: "Lavadora + secadora" },
] as const;
