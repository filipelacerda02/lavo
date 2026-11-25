# Lavô

Este repositório tem dois projetos:

| Pasta | O que é |
| --- | --- |
| [`site/`](site/README.md) | **Site institucional da Lavô (v2):** Astro + TypeScript + Tailwind, gerado de forma estática e publicado na borda (Cloudflare Pages). Inclui animações, CSP estrita, gestão de consentimento (LGPD), formulário de direitos do titular com criptografia AES-256, monitoramento de Core Web Vitals e acessibilidade WCAG 2.1 AA. Mantém a engine original de busca de unidades. |
| [`gerador/`](gerador/README.md) | Ferramenta separada que gera versões redesenhadas de sites com IA e vende o código (veja também `gerador/CUSTOS.md`). |

## Site: começo rápido

```bash
cd site
```

```bash
npm install
```

```bash
npm run dev
```

O passo a passo de publicação e a tabela de como cada requisito técnico, de segurança e de LGPD foi atendido estão em [`site/README.md`](site/README.md).
