# Análise de custos e preço (R$ 499,90)

Todos os valores são estimativas. Os números reais aparecem no painel `/admin` depois das primeiras prévias. Meça com 20 a 30 prévias antes de investir pesado em anúncios.

## 1. Custo da IA por prévia

Cada prévia faz **uma** chamada ao Claude Opus 5.5 (US$ 4 por milhão de tokens de entrada e US$ 20 por milhão de saída).

| Item | Tokens estimados | Custo |
| --- | --- | --- |
| Entrada: instruções + conteúdo do site + ~24 miniaturas de fotos | ~14 mil | US$ 0,06 |
| Saída: o site em HTML/CSS/JS + raciocínio da IA | 20 a 45 mil | US$ 0,40 a 0,90 |
| **Total por prévia** | | **≈ US$ 0,45 a 0,95 (R$ 2,50 a 5,30)** |

As contas usam o dólar a R$ 5,60. Por segurança, considere **R$ 5 por prévia**, já incluindo erros e repetições. Servidor e Chromium custam pouco por prévia; a hospedagem é um custo fixo de R$ 60 a 150 por mês.

> **Resposta curta:** sim, R$ 499,90 cobre com folga o custo com a IA. Uma prévia custa cerca de 1% do preço. O que decide o lucro é **quantas prévias grátis você paga até sair uma venda**, somando o custo da IA e o dos anúncios.

## 2. Quanto sobra de cada venda

| | Valor |
| --- | --- |
| Preço | R$ 499,90 |
| Mercado Pago, cartão à vista (~5%; no Pix ~1%) | − R$ 25 |
| Impostos (Simples Nacional, a partir de ~6%; pode chegar a 15,5% conforme o enquadramento) | − R$ 30 |
| **Líquido antes de IA e anúncios** | **≈ R$ 445** |

Confirme as taxas atuais do Mercado Pago e o seu enquadramento tributário com um contador. MEI normalmente não cobre desenvolvimento de software.

## 3. Lucro por venda conforme a conversão e o custo do anúncio

Fórmula: **lucro por venda = 445 − (custo da IA por prévia + custo do anúncio por prévia) ÷ taxa de conversão**

A taxa de conversão é a porcentagem de prévias que viram compra. O custo do anúncio por prévia é o custo por lead: quanto você paga em anúncio para alguém gerar uma prévia.

| Conversão | Lead a R$ 5 | Lead a R$ 10 | Lead a R$ 20 |
| --- | --- | --- | --- |
| 2% (1 venda a cada 50 prévias) | − R$ 55 | − R$ 305 | − R$ 805 |
| 4% (1 a cada 25) | R$ 195 | R$ 70 | − R$ 180 |
| 6% (1 a cada 17) | R$ 278 | R$ 195 | R$ 28 |
| 10% (1 a cada 10) | R$ 345 | R$ 295 | R$ 195 |

**Conversão mínima para empatar:** 2,2% com lead a R$ 5, 3,4% com lead a R$ 10 e 5,6% com lead a R$ 20.

## 4. Conclusão

- **O preço cobre a IA tranquilamente.** O risco está no funil: prévias grátis que não viram venda custam anúncio e IA.
- R$ 499,90 está **abaixo** do que freelancers costumam cobrar por um site institucional no Brasil. Isso ajuda a converter, mas deixa pouca margem para anúncios caros. Se a conversão real ficar abaixo de ~4%, considere:
  1. **Aumentar o preço** (R$ 697 a R$ 997) ou criar planos: só o código / código + publicação / código + domínio e hospedagem.
  2. **Receita recorrente:** hospedagem e manutenção por R$ 39 a R$ 79 por mês aumentam muito o valor de cada cliente.
  3. **Recuperar quem não comprou:** os e-mails já ficam salvos. Uma sequência de 2 ou 3 e-mails com a prévia costuma ser a venda mais barata que existe.
  4. **Baixar o custo da IA,** se precisar: `ESFORCO=medium` ou `MODELO=claude-sonnet-5-5` (cerca de metade do preço). Teste a qualidade antes, porque a qualidade da prévia é o que vende.
- **Plano de teste sugerido:** invista R$ 1.000 a 2.000 em anúncios, gere 100 a 200 prévias e acompanhe no `/admin` o custo real por prévia e a conversão. Com esses dois números, a tabela acima diz se vale escalar.

## 5. Custos fixos mensais (estimativa)

| Item | Valor |
| --- | --- |
| Servidor com Docker (2 GB de RAM ou mais) | R$ 60 a 150 |
| Domínio .com.br | ~R$ 40 por ano |
| Créditos da API da Anthropic | pré-pagos, conforme o uso (100 prévias ≈ R$ 500) |
| Cloudflare Turnstile | grátis |
