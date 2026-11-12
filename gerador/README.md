# Reforma: gerador de sites com IA

O cliente cola o link do site atual. A ferramenta lê o conteúdo, as fotos, as cores e as fontes, gera com o Claude um site redesenhado e mostra uma **prévia protegida**. Se o cliente gostar, ele paga **R$ 499,90** pelo Mercado Pago (Pix ou cartão) e baixa o código pronto num .zip.

## Como funciona

```
cliente cola a URL ─▶ extração (textos, imagens, cores, fontes, contatos, até 5 páginas)
                   ─▶ Claude gera um index.html completo (vê miniaturas das fotos para escolher onde usar cada uma)
                   ─▶ Chromium tira prints (computador e celular) com marca d'água
                   ─▶ cliente vê só as imagens da prévia ─▶ paga ─▶ baixa o .zip
```

### Proteção da prévia

- **O código nunca vai para o navegador antes da compra.** A prévia é uma imagem gerada no servidor, com marca d'água, desenhada em `<canvas>`. Mesmo com o "inspecionar elemento" aberto, não há HTML nem CSS para copiar.
- Na página de prévia também estão bloqueados o botão direito, arrastar, selecionar e copiar, e os atalhos F12, Ctrl+U, Ctrl+S, Ctrl+P e Ctrl+Shift+I/J/C.
- Essas barreiras no navegador só atrapalham. Nenhum site consegue impedir de verdade alguém de abrir as ferramentas do desenvolvedor ou tirar um print da tela. Quem realmente protege o código é o primeiro ponto.
- O download só sai com um token secreto, criado depois que o pagamento é **confirmado direto na API do Mercado Pago**. O sistema não confia em parâmetros da URL nem no webhook sozinho.

### Proteções de custo e de segurança

- Limite de prévias por IP por dia (`LIMITE_POR_IP_DIA`) e limite global por dia (`LIMITE_GLOBAL_DIA`).
- Se o mesmo domínio já foi gerado nos últimos `CACHE_DIAS` dias, a prévia é reaproveitada, sem custo de IA.
- Anti-robô opcional com o Cloudflare Turnstile.
- Bloqueio de SSRF: a ferramenta não acessa IPs internos nem redes privadas, e a checagem é feita no momento da conexão.
- Durante a renderização, o HTML gerado não acessa a internet, exceto o Google Fonts.
- O conteúdo extraído é tratado como dado, não como instrução, para evitar prompt injection.

## Rodar localmente

```bash
cd gerador
```

```bash
npm install
```

```bash
npx playwright install --with-deps chromium
```

```bash
cp .env.example .env
```

Preencha o `.env` e depois rode:

```bash
npm start
```

Abra http://localhost:3000. Para testar o fluxo sem gastar com IA, use `MODO_DEMO=1` no `.env`: a página gerada fica simples, mas todo o resto funciona.

## Configuração (`.env`)

| Variável | Para que serve |
| --- | --- |
| `ANTHROPIC_API_KEY` | Chave da API do Claude (console.anthropic.com). A cobrança é por uso, com créditos pré-pagos. |
| `MP_ACCESS_TOKEN` | Access token de produção do Mercado Pago |
| `MP_WEBHOOK_SECRET` | Chave secreta do webhook (valida a assinatura das notificações) |
| `BASE_URL` | Endereço público, por exemplo `https://reforma.com.br` (o retorno do pagamento e o webhook dependem dele) |
| `PRECO` | Preço em reais (padrão 499.90) |
| `MODELO` / `ESFORCO` | Modelo e nível de esforço da IA (padrão `claude-opus-5-5` / `high`) |
| `LIMITE_POR_IP_DIA`, `LIMITE_GLOBAL_DIA`, `CACHE_DIAS` | Controle de gastos |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET` | Anti-robô (opcional, grátis na Cloudflare) |
| `ADMIN_SENHA` | Senha do painel `/admin?senha=...`, que mostra prévias, custo real com IA, vendas e conversão |

## Publicar

A aplicação precisa de um servidor que rode Node.js 20+ e Chromium. Hospedagem estática simples não serve.

- **Docker (recomendado):** o `Dockerfile` usa a imagem oficial do Playwright. Funciona no Railway, Render, Fly.io ou numa VPS (Hostinger, DigitalOcean, Contabo...). Monte um volume em `/app/dados`.
- No Mercado Pago, cadastre o webhook `https://SEU_DOMINIO/api/webhook/mercadopago` com o evento **Pagamentos**.
- Teste com as credenciais de teste do Mercado Pago antes de ativar as de produção.

## Estrutura

```
src/server.js     rotas, fila de geração, pagamento e download
src/extrair.js    leitura do site (textos, imagens, cores, fontes, contatos)
src/rede.js       downloads seguros (bloqueio de SSRF, limites de tamanho e tempo)
src/gerar.js      prompt e chamada ao Claude (+ modo demonstração)
src/render.js     miniaturas e prints da prévia com marca d'água (Playwright)
src/pagamento.js  Mercado Pago Checkout Pro + validação do webhook
src/limites.js    limites diários e anti-robô
src/pacote.js     montagem do .zip
src/store.js      projetos salvos em JSON (troque por banco de dados quando crescer)
public/           página inicial e página de prévia
```

## Limitações conhecidas

- Sites que montam o texto só com JavaScript (alguns Wix e sites em React) podem ter pouco conteúdo extraído. Nesses casos o cliente recebe uma mensagem de erro, sem custo de IA.
- O resultado é uma página única com seções. Funcionalidades sob medida, como o buscador de unidades da Lavô, lojas virtuais e áreas com login, não são recriadas: a IA mantém links para elas.
- A qualidade varia de site para site. Acompanhe as primeiras prévias pelo `/admin` antes de investir em anúncios.
- Os dados ficam em arquivos JSON numa única máquina. Para rodar vários servidores, use um banco de dados e uma fila compartilhada.
- E-mails de acompanhamento para quem não comprou ainda não estão implementados, mas os e-mails já ficam salvos.

## Antes de vender

- **Termos de uso e política de privacidade (LGPD):** o sistema coleta e-mail e conteúdo de sites.
- **Direitos:** qualquer pessoa pode colar o link de um site que não é dela. O formulário exige a declaração de que a pessoa é responsável pelo site, mas deixe isso claro também nos termos. As fotos e os textos continuam sendo do dono do site original.
- **Tributação:** confirme o enquadramento com um contador (veja `CUSTOS.md`).
