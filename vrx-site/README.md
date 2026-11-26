# Site VRX Laundry Supply

Recriação de [vrxequipamentos.com.br](https://vrxequipamentos.com.br/) (antes WordPress + Elementor) como site estático moderno, com funções na borda da Cloudflare.
Textos, produtos, fotos, logo, cores (laranja `#EC6608` e grafite `#797A76`) e fonte (Poppins) vêm do site atual. Nada foi inventado: o que não existe no site atual está marcado como `PREENCHER` em `src/config/site.ts`.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Site | Astro 7 (SSG, `output: "static"`), TypeScript com `tsconfig` *strictest*, `astro check` no build |
| Estilo | Tailwind CSS v4 com os tokens da marca em `@theme` (`src/styles/global.css`) |
| Fontes | Poppins e Roboto pelo `@fontsource`, servidas pelo próprio site (sem Google Fonts) |
| Imagens | `astro:assets`: WebP responsivo com `width`/`height`, `srcset` e `sizes` |
| Animações | GSAP 3 (transição entre páginas) + Lenis (rolagem suave sincronizada ao ScrollTrigger) + motor próprio de entradas (`data-anim`, contadores, paralaxe, cartões 3D, botões magnéticos, títulos palavra a palavra). Tudo empacotado, sem CDN |
| Navegação | `ClientRouter` do Astro com transição do cata-vento VRX (GSAP) |
| Borda | Cloudflare Pages Functions em TypeScript (`functions/api/*`) + KV |
| Observabilidade | `web-vitals` → `/api/metricas`, Sentry opcional, logs estruturados em JSON |

## Páginas

| Rota | Conteúdo |
| --- | --- |
| `/` | Hero, faixa de modelos, produtos, "Porque comprar de nós", garantia em números, FAQ e contato |
| `/produtos` | Catálogo dos 6 modelos com filtro (lavadoras, secadoras, lavadora + secadora) e lista de orçamento |
| `/orcamento` | Formulário de orçamento (Turnstile, limite, criptografia, webhook) e envio da mesma lista pelo WhatsApp |
| `/suporte-e-garantia` | Suporte técnico, garantia (1 ano mão de obra, 3 anos peças), passo a passo da garantia e FAQ |
| `/privacidade`, `/cookies`, `/termos`, `/direitos-do-titular`, `/acessibilidade` | Páginas legais e LGPD |
| `/404` | Página não encontrada |

O que o site atual fazia e como ficou:

| Site atual | Agora |
| --- | --- |
| Botões "Orçamento", "Fale conosco" e "Entre agora em contato" levando ao WhatsApp | Mantidos, com mensagens prontas por contexto, e um formulário de orçamento completo |
| Carrossel "Conheça alguns de nossos produtos" | Catálogo filtrável, com "Adicionar ao orçamento" e JSON-LD de produtos |
| FAQ em sanfona | `<details>` acessível, com JSON-LD `FAQPage`, na home e em Suporte e garantia |
| Ícones de Instagram, e-mail e WhatsApp no rodapé | Mantidos no rodapé, no orçamento e no botão flutuante |

## Estrutura

```
src/config/site.ts        dados da empresa, contatos, DPO ("PREENCHER" onde falta)
src/data/produtos.ts      catálogo (modelo e descrição iguais às artes do site atual)
src/data/faq.ts           perguntas e respostas do site atual
src/components/           Cabecalho, Rodape, Consentimento, Transicao, Catavento, ProdutoCard, Faq, MapaConsentido...
src/scripts/              animacoes, suave (Lenis), transicao (GSAP), consentimento, catalogo, orcamento, observabilidade
functions/api/            _middleware, orcamento, titular, consentimento, metricas
borda/util.ts             JSON, logs, HMAC, AES-256-GCM, limite no KV, Turnstile, webhook assinado
scripts/verificar-build.mjs  gera dist/_headers e valida o HTML
scripts/ler-pedidos.mjs      lê e descriptografa orçamentos e pedidos LGPD
```

## Rodar localmente

```bash
npm install
cp .env.example .env            # opcional: chaves públicas (Turnstile, GA4, Pixel, Sentry)
# .dev.vars (fora do git) já traz CHAVE_CRIPTOGRAFIA/SALT_IP/WEBHOOK_SECRET só para desenvolvimento
npm run build                   # astro check + build + verificação de segurança
npm run preview                 # wrangler pages dev ./dist  (site + funções + KV local)
CHAVE_CRIPTOGRAFIA=... node scripts/ler-pedidos.mjs orcamento --local
```

## Requisitos e como foram atendidos

| Requisito | Como foi atendido | Configurar no painel / não se aplica |
| --- | --- | --- |
| Astro SSG + TS strictest + `astro check` | `astro.config.mjs`, `tsconfig.json`, script `build` | — |
| Tailwind v4 com tokens da marca | `@theme` em `global.css` (laranja, grafite e variações com contraste AA) | — |
| Fontes no próprio site | `@fontsource/poppins` e `@fontsource-variable/roboto` | — |
| Imagens otimizadas | `astro:assets`, WebP, `srcset`/`sizes`, `width`/`height` | — |
| SEO técnico | canonical, Open Graph com imagem própria, JSON-LD `Organization`, `ItemList` de `Product` e `FAQPage`, sitemap, `robots.txt` | Search Console: enviar `/sitemap-index.xml` |
| Animações GSAP + Lenis, desligadas com movimento reduzido | `transicao.ts`, `suave.ts`, `animacoes.ts`; `prefers-reduced-motion` em CSS e JS; conteúdo visível sem JS | — |
| Seção de storytelling com pin e scrub | Foi construída e testada, mas **removida a pedido** ("não precisa fazer animação de etapas nessa página") | Não se aplica |
| Transição entre páginas temática | Cata-vento VRX em GSAP: `astro:before-preparation` cobre, `astro:page-load` revela (inclusive na primeira carga), trava de 3 s em CSS | — |
| CSP estrita sem `unsafe-inline` | `inlineStylesheets: "never"`, `assetsInlineLimit: 0`, nenhum `style=`, `public/js/flag.js`; `verificar-build.mjs` falha o build se houver script/estilo embutido | — |
| Cabeçalhos de segurança | `dist/_headers`: CSP, HSTS com preload, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP, CORP, remove `Access-Control-Allow-Origin` | HSTS preload: inscrever em hstspreload.org depois de estável |
| Validações do build | Falha com script/estilo embutido, imagem sem `alt`, falta de `lang` e link em nova aba sem aviso ou sem `noopener`; avisa sobre `PREENCHER` | — |
| Middleware da API | Só POST e JSON, bloqueio por `Origin` e `Sec-Fetch-Site`, `Content-Length` obrigatório e até 8 KB, erros com log | — |
| Formulário de orçamento | Minimização (só campos previstos), Turnstile, limite de 5/h por IP pseudonimizado (HMAC), AES-256-GCM antes do KV, retenção de 12 meses, webhook assinado (`x-vrx-assinatura: sha256=...`) | Segredos, KV, `WEBHOOK_ORCAMENTO_URL` (CRM ou automação de e-mail) |
| Direitos do titular | Mesmo padrão, protocolo `LGPD-...`, retenção de 5 anos | `WEBHOOK_TITULAR_URL` (opcional) |
| Registro de consentimento | `/api/consentimento` com id anônimo, versão, categorias, IP pseudonimizado | — |
| LGPD: banner granular | 4 categorias; "Aceitar todos" e "Só essenciais" com o mesmo destaque; revogação recarrega e apaga cookies; link "Preferências de cookies" no rodapé | — |
| Bloqueio real de terceiros | GA4 e Meta Pixel só são inseridos após o aceite; mapa como botão "Carregar mapa" (aparece quando o endereço da sede for preenchido) | `PUBLIC_GA_ID`, `PUBLIC_META_PIXEL_ID` (opcionais) |
| Dados da empresa e DPO | `src/config/site.ts` | Preencher razão social, CNPJ, endereço e DPO |
| Acessibilidade WCAG 2.1 AA | Contraste AA, teclado, "Ir para o conteúdo", foco visível, ARIA no menu, filtros (`aria-pressed`), lista e formulários (`aria-live`), avisos de nova aba; axe sem violações | — |
| Observabilidade | `web-vitals` → `/api/metricas` (anônimo); Sentry só com DSN e sem dados pessoais; logs JSON nas funções | `PUBLIC_SENTRY_DSN` (opcional); Workers Logs/Logpush |

## Publicar no Cloudflare Pages

1. **Conta**: ative **MFA** em todos os usuários da conta Cloudflare (Manage Account › Members) e use o papel mínimo necessário.
2. **Projeto**: Workers & Pages › Create › Pages › conecte o repositório. Diretório raiz `vrx-site`, comando `npm run build`, saída `dist`, variável de build `NODE_VERSION=22`.
3. **KV**: `npx wrangler kv namespace create VRX_KV`, copie o `id` para `wrangler.toml` (ou vincule o namespace em Settings › Bindings com o nome `VRX_KV`).
4. **Segredos** (Settings › Variables and Secrets, tipo *Secret*):
   - `CHAVE_CRIPTOGRAFIA`: `openssl rand -base64 32` (guarde em cofre: sem ela os pedidos não podem ser lidos);
   - `SALT_IP`: `openssl rand -hex 32`;
   - `WEBHOOK_SECRET`: `openssl rand -hex 32` (o receptor valida a assinatura HMAC);
   - `TURNSTILE_SECRET`: chave secreta do Turnstile.
5. **Variáveis**: `WEBHOOK_ORCAMENTO_URL` (CRM, RD Station, HubSpot, Pipedrive, Zapier ou Make, que pode mandar e-mail para `comercial@vrxequipamentos.com.br`), `WEBHOOK_TITULAR_URL` e, no build, `PUBLIC_TURNSTILE_SITE_KEY` (e GA4, Pixel e Sentry, se forem usar). Refaça o build depois de mudar variáveis `PUBLIC_*`.
6. **Turnstile**: crie o widget em Turnstile › Add site, para o domínio `vrxequipamentos.com.br`.
7. **Domínio**: Custom domains › `vrxequipamentos.com.br` e `www` (redirecione `www` para o domínio principal com uma Redirect Rule).
8. **TLS**: SSL/TLS em *Full (strict)*, *Always Use HTTPS*, TLS mínimo 1.2 e TLS 1.3 ligado.
9. **WAF**: Security › WAF › Managed rules (Cloudflare Managed Ruleset) ligadas; Bot Fight Mode ligado.
10. **Rate limiting**: regra para `/api/*` (por exemplo, 20 requisições por minuto por IP → bloquear por 10 min). Ela complementa o limite em KV das funções.
11. **Testar** em produção: enviar um orçamento de teste, conferir que chegou ao webhook e ler com `node scripts/ler-pedidos.mjs orcamento`.

## Antes de publicar (checklist)

- [ ] Preencher em `src/config/site.ts`: razão social, CNPJ, endereço da sede e encarregado (DPO). O build avisa enquanto houver `PREENCHER`.
- [ ] Revisar com o jurídico as políticas (privacidade, cookies, termos), principalmente o prazo de 12 meses para guardar orçamentos.
- [ ] Confirmar a descrição do SSG030: no site atual a arte só mostra o modelo, e "Lavadora e secadora sobrepostas" foi deduzido dos ícones e da foto.
- [ ] Confirmar se o material de apoio da infraestrutura pode ser pedido pelo WhatsApp (link em Suporte e garantia).
- [ ] Criar KV, segredos, Turnstile, webhook de orçamento e regras de WAF e rate limiting.
- [ ] MFA ativo em todas as contas com acesso (Cloudflare, GitHub, CRM).
- [ ] Rodar `npm run build` sem erros e testar `/orcamento` e `/direitos-do-titular` com o Turnstile real.
- [ ] Apontar o domínio e enviar o sitemap ao Google Search Console.

## Testes feitos

- `npm run build`: `astro check` com 0 erros, 0 avisos e 0 dicas; verificação de CSP e HTML aprovada.
- `wrangler pages dev ./dist` + Playwright: 10 páginas × 5 perfis (1440×900, celular 390×844, iPhone 13, Pixel 7 e iPhone SE com `isMobile`). Resultado: sem erros de JS, sem violação de CSP, sem rolagem lateral e axe-core (WCAG 2.0/2.1 A e AA) sem violações.
- APIs: envio válido (200 + protocolo), outra origem (403), `Sec-Fetch-Site: cross-site` (403), corpo de 10 KB (413), `text/plain` (415), GET (405), dados inválidos (400) e 6º envio na hora (429). O valor no KV é `v1.<iv>.<cifra>`, sem nenhum dado legível, e `ler-pedidos.mjs` o abre com a chave. Campos extras e produtos inválidos são descartados.
- Fluxo no navegador: banner LGPD, filtro com contagem anunciada, lista de orçamento, pré-seleção no formulário, link do WhatsApp com a lista, validação com foco no campo e protocolo exibido. Nenhum pedido a terceiros antes do consentimento.
- Sem JavaScript e com movimento reduzido: todo o conteúdo visível e a transição desligada.
