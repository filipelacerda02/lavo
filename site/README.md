# Site Lavô (v2): Astro + TypeScript + Tailwind na borda

Site institucional da Lavô com geração estática (SSG), funções na borda (Cloudflare Pages Functions), CSP estrita, LGPD e acessibilidade WCAG 2.1 AA.

```
site/
├─ src/
│  ├─ pages/           páginas (.astro) → HTML estático
│  ├─ components/      cabeçalho, rodapé, consentimento, títulos animados…
│  ├─ layouts/         layout base (SEO, View Transitions) e layout de textos legais
│  ├─ scripts/         animações, consentimento (CMP), localizador de unidades, observabilidade
│  ├─ styles/          Tailwind v4 + tokens da marca + sistema de animações
│  ├─ data/unidades.tsv  base das 676 unidades (engine original)
│  └─ config/site.ts   dados da empresa, encarregado (DPO), promoções
├─ functions/api/      backend na borda: consentimento, titular (LGPD), métricas
├─ borda/util.ts       criptografia AES-256-GCM, HMAC, limites, Turnstile, logs estruturados
├─ scripts/            pós-build (CSP + validações) e leitura dos pedidos LGPD
└─ wrangler.toml       configuração do Cloudflare Pages
```

## Comandos

```bash
npm install
```

```bash
npm run dev
```

```bash
npm run build
```

```bash
npm run preview
```

`npm run build` roda `astro check` (TypeScript), gera o site e executa `scripts/verificar-build.mjs`. O build **falha** se houver script ou estilo embutido (que quebraria a CSP) ou imagem sem `alt`, e **avisa** se ainda existirem campos "PREENCHER".

`npm run preview` sobe o ambiente da Cloudflare localmente, com funções, KV e cabeçalhos.

---

## Como cada requisito foi atendido

Legenda: ✅ implementado no código · ⚙️ configuração no painel (passo a passo abaixo) · ➖ não se aplica a este site

### Camadas de construção

| Requisito | Como | |
| --- | --- | --- |
| Framework moderno com SSG | **Astro 7** gerando HTML estático, com JavaScript só onde há interação | ✅ |
| TypeScript | Todo o código cliente e servidor em TS, `astro check` no modo `strictest` | ✅ |
| Tailwind CSS | Tailwind v4 com tokens da marca (`@theme` em `global.css`) | ✅ |
| SEO técnico | `canonical`, Open Graph, JSON-LD (Organization), `sitemap-index.xml`, URLs limpas, `lang="pt-BR"`, imagens com `width`/`height` | ✅ |
| Arquitetura desacoplada / APIs REST | Funções na borda em `/api/*`, com JSON validado no servidor | ✅ |
| Autenticação por tokens (JWT/OAuth) | O site é público e não tem login de usuários. A comunicação com o CRM é assinada com **HMAC-SHA256**. O acesso administrativo usa o SSO da Cloudflare com MFA. JWT/OAuth entram se um dia houver área do cliente ou do franqueado. | ➖ |
| Integração com CRM | Pedidos LGPD enviados por webhook assinado (`WEBHOOK_TITULAR_URL`) para RD Station, HubSpot, Pipedrive ou Zapier/Make | ✅ |
| ERP contábil / assinatura digital | Não há fluxo financeiro nem contratos no site. O formulário de franquia fica em lavobrasil.com.br. | ➖ |
| Gateway de pagamento | Não há venda no site | ➖ |

### Infraestrutura, cloud e edge (Cloudflare Pages)

| Requisito | Como | |
| --- | --- | --- |
| CDN global / edge computing | Cloudflare Pages: HTML e arquivos servidos de mais de 300 cidades, funções rodando na borda | ⚙️ |
| Balanceamento e escala automática | Inerentes ao Pages/Workers, sem servidor para gerenciar | ⚙️ |
| Cache | `/_astro/*` com hash no nome, `immutable` por 1 ano. HTML revalidado a cada deploy. | ✅ |
| Backups diários com redundância geográfica | O código e as unidades ficam versionados no Git, e cada deploy é imutável e pode voltar com um clique. Os dados do KV (consentimentos e pedidos) são replicados globalmente pela Cloudflare. Para cópia externa, agende a exportação do KV (abaixo). | ⚙️ |

### Observabilidade e performance

| Requisito | Como | |
| --- | --- | --- |
| Core Web Vitals monitorados | `web-vitals` mede LCP, INP, CLS, FCP e TTFB de visitantes reais e envia para `/api/metricas` (anônimo, sem cookies) | ✅ |
| LCP < 2,5 s, INP < 200 ms, CLS ≈ 0 | HTML estático na CDN, imagem principal com `fetchpriority="high"`, AVIF/WebP responsivos, fontes próprias, dimensões reservadas, JS mínimo e sem framework no cliente | ✅ |
| Logs estruturados | Todas as funções gravam JSON (`nivel`, `evento`, `ts`…) no Workers Logs. Ative o Logpush para enviar a um SIEM. | ✅ ⚙️ |
| Sentry | Carregado só se `PUBLIC_SENTRY_DSN` existir, com coleta de dados pessoais desligada | ✅ ⚙️ |
| Análise de comportamento com privacidade | GA4 com IP anonimizado, carregado **somente após consentimento** | ✅ |

### Segurança

| Requisito | Como | |
| --- | --- | --- |
| TLS 1.3, HTTPS forçado | SSL/TLS → "Full (strict)", "Always Use HTTPS" e "Minimum TLS Version 1.2" com TLS 1.3 ativo | ⚙️ |
| HSTS | `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` em `dist/_headers` | ✅ |
| CSP estrita | Sem `unsafe-inline` nem `unsafe-eval`. O build garante que não existe script ou estilo embutido. Domínios de terceiros só entram se a ferramenta estiver configurada. | ✅ |
| X-Frame-Options / X-Content-Type-Options | `DENY` / `nosniff`, mais `frame-ancestors 'none'`, `Referrer-Policy`, `Permissions-Policy`, `COOP` e `CORP` | ✅ |
| WAF (OWASP Top 10) | Security → WAF → Managed rules: **Cloudflare Managed Ruleset + OWASP Core Ruleset** | ⚙️ |
| DDoS | Mitigação automática da Cloudflare (camadas 3, 4 e 7) | ⚙️ |
| XSS / SQL injection no código | Sem banco SQL. Toda entrada é validada no servidor. O HTML dinâmico do buscador escapa os dados. A CSP bloqueia a execução de scripts injetados. | ✅ |
| CSRF | O middleware `/api` recusa outras origens (`Origin` e `Sec-Fetch-Site`) e exige JSON | ✅ |
| Rate limiting | Limite por IP pseudonimizado no KV, mais regra de Rate Limiting no WAF (abaixo) | ✅ ⚙️ |
| Anti-robô | Cloudflare Turnstile no formulário LGPD | ✅ ⚙️ |
| Criptografia em repouso AES-256 | Pedidos de titular cifrados com **AES-256-GCM** (WebCrypto) antes de ir ao KV. O KV também é cifrado pela Cloudflare. | ✅ |
| MFA no administrativo | O site não tem painel próprio. Exija MFA na conta Cloudflare e no GitHub e use Cloudflare Access para qualquer área administrativa futura. | ⚙️ |

### LGPD

| Requisito | Como | |
| --- | --- | --- |
| Banner granular (CMP) | Essenciais, Funcionais, Analíticos e Marketing. "Aceitar todos" e "Somente essenciais" com o mesmo destaque. | ✅ |
| Bloqueio real antes do aceite | Nenhum script de terceiro está no HTML. GA4 e Meta Pixel só são inseridos após o aceite. O mapa do Google é um botão até haver consentimento. Ao revogar, os cookies são apagados e a página é recarregada. | ✅ |
| Log de consentimento | `/api/consentimento` grava id aleatório, categorias, versão da política, data, página e IP pseudonimizado (HMAC), por 5 anos | ✅ |
| Política de privacidade clara | `/privacidade`, com tabela de dados × finalidade × base legal | ✅ (revisão jurídica) |
| Termos de uso | `/termos` | ✅ (revisão jurídica) |
| Encarregado (DPO) identificado | Nome e e-mail em `src/config/site.ts`, exibidos na política e no formulário | ⚠️ preencher |
| Pedido de exclusão/portabilidade | `/direitos-do-titular`: formulário com protocolo na hora, Turnstile, limite de envios, criptografia e envio ao CRM | ✅ |
| Minimização | O formulário pede só nome, e-mail e tipo (mensagem opcional). O site não tem formulário comercial. Fontes hospedadas no próprio domínio (sem Google Fonts). | ✅ |

### Acessibilidade (WCAG 2.1 AA / LBI)

Contraste AA, navegação completa por teclado, link "Ir para o conteúdo", foco visível, `aria-current`, `aria-expanded`, `aria-live` nos resultados, rótulos em todos os campos, `alt` em todas as imagens (o build falha se faltar), avisos de "abre em nova aba", `prefers-reduced-motion` desligando as animações e declaração em `/acessibilidade`. As páginas foram auditadas com axe-core (WCAG 2.0/2.1 A e AA).

---

## Animações

Sem bibliotecas: `src/scripts/animacoes.ts` (~3 KB) + CSS. Use nos elementos:

| Atributo | Efeito |
| --- | --- |
| `data-anim="sobe\|desce\|esquerda\|direita\|zoom\|desfoque\|cortina\|cortina-lado\|giro"` | entrada ao rolar |
| `data-cascata="90"` no pai | filhos entram em sequência |
| `data-contar="700" data-prefixo="+"` | contador animado |
| `data-barra="31%"` | barra que cresce |
| `data-paralaxe="0.15"` | paralaxe |
| `data-desenho` (em `<svg>`) | linha que se desenha conforme a rolagem |
| `data-ima` | botão magnético |
| `data-inclinar` | cartão com inclinação 3D |
| `<TituloAnimado texto="… *destaque*">` | palavras entrando uma a uma |

### Bibliotecas de animação (gratuitas)

| Ferramenta | Licença | Uso no site |
| --- | --- | --- |
| [GSAP](https://gsap.com) 3.15 + ScrollTrigger, SplitText, DrawSVG, MotionPath, ScrollTo | Gratuita, inclusive para uso comercial (Webflow tornou todos os plugins gratuitos) | Seção "Como funciona" e transições entre páginas |
| [Lenis](https://lenis.darkroom.engineering) | MIT | Rolagem suave sincronizada ao ScrollTrigger (`src/scripts/suave.ts`) |

Outras ferramentas gratuitas avaliadas, que podem ser usadas no futuro:
- **Lottie / LottieFiles:** animações vetoriais prontas em JSON (`@lottiefiles/dotlottie-web`, MIT).
- **Motion:** animações declarativas (motion.dev, MIT).
- **Anime.js v4:** biblioteca leve (MIT).
- **Haikei e Get Waves:** geradores gratuitos de ondas e blobs em SVG.

Tudo é empacotado no próprio site (sem CDN externo), o que mantém a CSP estrita.

### "Como funciona": duas metades guiadas pela rolagem

`src/components/ComoFunciona.astro`, `src/components/MaquinaRealista.astro` e `src/scripts/ciclo.ts`.

A seção fica presa na tela por cerca de 7 telas de rolagem (GSAP ScrollTrigger com `scrub`):
- **À esquerda:** o texto de cada etapa entra palavra por palavra (SplitText), com a trilha 01 → 05 → Lavando → Secando e as pílulas de tempo.
- **À direita:** a ilustração executa a etapa.
- **No celular:** o texto fica na parte de cima e a máquina na de baixo.

| Etapa | Animação |
| --- | --- |
| 01 Meça | peças caem no cesto medidor com quique |
| 02 Pague | cartão com chip encosta no leitor por aproximação, LEDs verde-lima, tela "OK ✓" |
| 03 Coloque | peças voam em arco para o tambor (MotionPath), a porta cromada fecha e trava |
| 04 Escolha | visor LCD alterna os programas |
| 05 INICIAR | sabão e amaciante desenham o caminho até o tambor (DrawSVG) |
| Lavagem | água com ondas e bolhas sobe, espuma, tambor acelera até centrifugar, cronômetro de 35 min |
| Secagem | água escoa, brilho quente e vapor, cronômetro de 45 min, porta destrava, aparece o botão "Encontrar uma unidade" |

A ilustração é um SVG feito à mão com técnicas de acabamento realista: aço escovado (`feTurbulence`), aro cromado com reflexos, borracha de vedação, tambor côncavo perfurado com pás, vidro com reflexos, tecidos com volume e dobras, espuma em bolhas, sombras e brilho no visor.

O botão de play do Passo 05 rola sozinho até o fim em cerca de 7 segundos. Qualquer rolagem do usuário interrompe. Com movimento reduzido ou sem JavaScript, a seção vira uma lista com a máquina fixa ao lado.

Ritmo: ajuste `T` (início de cada etapa) em `ciclo.ts` e o `end` do ScrollTrigger (`innerHeight * 7`).

### Transição entre páginas

`src/components/Transicao.astro` e `src/scripts/transicao.ts`:
- **Ao sair de uma página:** a água sobe cobrindo a tela, as bolhas sobem e a "porta da máquina" aparece com água girando e o logo.
- **Ao entrar** (inclusive no primeiro carregamento): as bolhas estouram de baixo para cima e a água sai pelo topo.

A transição está integrada ao ClientRouter do Astro (`astro:before-preparation` e `astro:page-load`). Tem uma trava de segurança em CSS que esconde a cobertura se o JavaScript falhar, e é desligada com movimento reduzido.

Também há ondas de água animadas, a "porta da máquina" que segue o cursor, bolhas nos botões, a barra de progresso de leitura e o cabeçalho que se esconde ao rolar. O conteúdo nunca fica invisível sem JavaScript, e tudo desliga com movimento reduzido.

## Buscador de unidades

A engine original está em `src/scripts/localizador.ts`, com a mesma lógica de busca, a mesma paginação, o mesmo mapa e os mesmos links do Google Maps e do Waze. Para incluir ou remover lojas, edite `src/data/unidades.tsv` (dá para colar direto de uma planilha) e faça deploy. Por causa da LGPD, o mapa do Google e a geocodificação no OpenStreetMap só são acionados com consentimento "Funcionais".

---

## Publicação (Cloudflare Pages)

1. **Projeto:** Workers & Pages → Create → Pages → conecte o GitHub. Configure "Root directory" como `site`, o comando de build como `npm run build` e o diretório de saída como `dist`.
2. **KV:**

   ```bash
   npx wrangler kv namespace create LAVO_KV
   ```

   Coloque o id em `wrangler.toml`, ou vincule o namespace em Settings → Bindings.
3. **Segredos** (Settings → Variables and Secrets, tipo *Secret*):
   - `CHAVE_CRIPTOGRAFIA`: gere com `openssl rand -base64 32` e guarde num cofre de senhas. **Sem ela os pedidos não podem ser lidos.**
   - `SALT_IP`: gere com `openssl rand -hex 16`
   - `TURNSTILE_SECRET` (com `PUBLIC_TURNSTILE_SITE_KEY` como variável de build)
   - `WEBHOOK_TITULAR_URL` e `WEBHOOK_SECRET` (opcionais, para o CRM)
   - Opcionais de build: `PUBLIC_GA_ID`, `PUBLIC_META_PIXEL_ID`, `PUBLIC_SENTRY_DSN`. A CSP se ajusta sozinha.
4. **Domínio:** Custom domains → `lavo.eco.br` e `www`. Depois redirecione `www` para o domínio principal em Rules → Redirect Rules.
5. **SSL/TLS:** Full (strict), Always Use HTTPS, TLS 1.3 ligado, versão mínima TLS 1.2. Depois de verificar o HSTS, inscreva o domínio em hstspreload.org.
6. **WAF:** Security → WAF → Managed rules → ative o *Cloudflare Managed Ruleset* e o *OWASP Core Ruleset*.
7. **Rate limiting:** Security → WAF → Rate limiting rules, com a expressão `http.request.uri.path wildcard "/api/*"`, limite de 20 requisições a cada 10 segundos por IP e ação Block.
8. **Bots:** Security → Bots → Bot Fight Mode.
9. **Logs:** Workers Logs ligado. Opcionalmente, Logpush para um SIEM ou armazenamento.
10. **Acesso:** MFA obrigatório na Cloudflare (Manage Account → Members → exigir 2FA) e no GitHub. Para qualquer área restrita futura, use o Zero Trust → Access.
11. **Backup do KV** (exemplo de rotina diária num CI):

    ```bash
    npx wrangler kv key list --binding LAVO_KV --remote > backup-chaves.json
    ```

### Ler os pedidos LGPD (encarregado)

```bash
CHAVE_CRIPTOGRAFIA=... node scripts/ler-pedidos.mjs
```

Para um único protocolo:

```bash
CHAVE_CRIPTOGRAFIA=... node scripts/ler-pedidos.mjs LGPD-20261125-ABC123
```

## Antes de publicar

- [ ] Preencher o endereço da sede e o encarregado (DPO) em `src/config/site.ts` (o build avisa enquanto faltar).
- [ ] Revisão jurídica da Política de privacidade, da Política de cookies e dos Termos de uso, incluindo os prazos de retenção (5 anos).
- [ ] Configurar segredos, KV, WAF, rate limiting e Turnstile.
- [ ] Desativar a promoção em `site.promo.ativa` quando o sorteio acabar.
- [ ] Atualizar os links das notícias que ainda apontam para o WordPress antigo.
