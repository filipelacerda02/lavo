/**
 * Dados institucionais, de contato e de privacidade da VRX.
 * Tudo aqui foi retirado do site atual (vrxequipamentos.com.br).
 * Campos com "PREENCHER" NÃO existem no site atual e precisam ser completados antes de publicar:
 * o build avisa enquanto existirem (scripts/verificar-build.mjs).
 */
export const site = {
  nome: "VRX Laundry Supply",
  nomeCurto: "VRX",
  razaoSocial: "PREENCHER: razão social da VRX",
  cnpj: "PREENCHER: CNPJ",
  endereco: "PREENCHER: endereço da sede",
  url: "https://vrxequipamentos.com.br",
  descricao:
    "Distribuidor homologado Alliance Laundry Systems: lavadoras e secadoras Speed Queen de nível industrial para você ser dono da sua lavanderia sem complicação.",
  whatsapp: "5519994388153",
  whatsappExibicao: "(19) 99438-8153",
  email: "comercial@vrxequipamentos.com.br",
  instagram: "https://www.instagram.com/vrxequipamentos/",
  /** Canal da Alliance para acionar a garantia (informado no FAQ do site atual) */
  emailGarantia: "sac@alliancels.com",
  /** Encarregado pelo tratamento de dados pessoais (DPO), art. 41 da LGPD */
  encarregado: {
    nome: "PREENCHER: nome do encarregado (DPO)",
    email: "PREENCHER: e-mail do encarregado",
  },
  /** Versão da política: mude quando o texto mudar (os consentimentos são registrados com ela) */
  versaoPolitica: "2026-11-26",
} as const;

export const navegacao = [
  { href: "/", rotulo: "Início" },
  { href: "/produtos", rotulo: "Produtos" },
  { href: "/suporte-e-garantia", rotulo: "Suporte e garantia" },
  { href: "/orcamento", rotulo: "Orçamento" },
] as const;

/** Link de WhatsApp com mensagem pronta (a mensagem padrão do site atual é "Olá!") */
export function linkWhats(mensagem = "Olá! Vim pelo site da VRX."): string {
  return `https://wa.me/${site.whatsapp}?text=${encodeURIComponent(mensagem)}`;
}
