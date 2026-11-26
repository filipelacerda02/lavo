/** Perguntas e respostas do site atual (seção "FAQ - Principais dúvidas"), com o texto revisado só na pontuação. */
import { site } from "@/config/site";

export const faq = [
  {
    pergunta: "Vocês fornecem suporte técnico para os equipamentos?",
    resposta: "Sim. A VRX, em conjunto com a Alliance do Brasil, possui uma relação de técnicos autorizados em todas as regiões do país.",
  },
  {
    pergunta: "Quanto à infraestrutura da loja, como fazer as adaptações necessárias para a instalação correta dos equipamentos?",
    resposta: "A infraestrutura é de responsabilidade do proprietário da loja, porém temos um material de apoio criado por uma empresa de engenharia especializada em lavanderias que certamente irá auxiliar na preparação do seu ponto comercial para a instalação dos nossos equipamentos.",
  },
  {
    pergunta: "Como funciona a garantia dos equipamentos?",
    resposta: `Os equipamentos possuem garantia de fábrica de 1 ano para mão de obra e 3 anos para peças. Neste período, caso haja algum problema que esteja dentro das regras descritas na política de garantias, basta encaminhar um laudo de técnico homologado para ${site.emailGarantia}, que já será providenciada a reposição e manutenção da peça.`,
    email: site.emailGarantia,
  },
] as const;

/** JSON-LD FAQPage */
export const faqJsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: faq.map((f) => ({ "@type": "Question", name: f.pergunta, acceptedAnswer: { "@type": "Answer", text: f.resposta } })),
};
