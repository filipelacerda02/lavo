/**
 * Dados institucionais e de privacidade.
 * Campos com "PREENCHER" precisam ser completados antes de publicar:
 * o build avisa enquanto existirem (scripts/verificar-build.mjs).
 */
export const site = {
  nome: "Lavô",
  razaoSocial: "Lavô Franchising Ltda",
  cnpj: "35.310.040/0001-14",
  endereco: "PREENCHER: endereço da sede",
  url: "https://lavo.eco.br",
  descricao: "A maior rede de lavanderias self-service do Brasil. Lave e seque suas roupas em até 1 hora.",
  whatsapp: "5511939034803",
  instagram: "https://www.instagram.com/lavo.franchising/",
  facebook: "https://www.facebook.com/lavofranchising/",
  franquia: "https://lavobrasil.com.br/franquia/",
  promo: {
    ativa: true,
    texto: "Sorteio final: concorra a um BYD Mini 0 km e a vouchers de R$ 500.",
    url: "https://lp-byd-lavo.kexj38.easypanel.host/",
  },
  /** Encarregado pelo tratamento de dados pessoais (DPO), art. 41 da LGPD */
  encarregado: {
    nome: "PREENCHER: nome do encarregado (DPO)",
    email: "PREENCHER: e-mail do encarregado",
  },
  /** Versão da política: mude quando o texto mudar (os consentimentos são registrados com ela) */
  versaoPolitica: "2026-11-25",
} as const;

export const navegacao = [
  { href: "/", rotulo: "Início" },
  { href: "/nossa-historia", rotulo: "Nossa história" },
  { href: "/vantagens", rotulo: "Vantagens" },
  { href: "/noticias", rotulo: "Notícias" },
  { href: "/unidades", rotulo: "Unidades" },
] as const;

export const linkWhats = `https://wa.me/${site.whatsapp}?text=${encodeURIComponent("Olá! Vim pelo site da Lavô.")}`;
