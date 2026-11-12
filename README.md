# Lavô: site institucional

Recriação do site [lavo.eco.br](https://lavo.eco.br/) em HTML, CSS e JavaScript puros, sem WordPress, sem build e sem dependências.

## Páginas

| Arquivo | Conteúdo |
| --- | --- |
| `index.html` | Home: busca rápida de loja, como funciona, números, história, produtos, sorteio e franquia |
| `nossa-historia.html` | História, missão, visão e valores, linha do tempo e convenções |
| `vantagens.html` | Vantagens, comparativo de economia, equipamentos e por que investir |
| `noticias.html` | Prêmio Exame, destaques na imprensa e notícias |
| `unidades.html` | **Buscador de unidades** (engine original) e lista por estado |

## Estrutura

```
assets/
  css/styles.css        identidade visual (cores, tipografia, componentes)
  js/main.js            menu mobile, animações, contadores
  js/lavo-locator.js    engine do buscador de unidades
  img/                  fotos e logos otimizados em WebP
```

## Buscador de unidades

A engine é a mesma do site atual, com a mesma lógica, os mesmos IDs e o mesmo formato de dados:

- os dados ficam em TSV dentro de `unidades.html`, no bloco `<script id="lavo-dados-tsv" type="text/plain">`;
- as colunas são `Logradouro | País | Bairro | Cidade | UF | CEP`, separadas por **TAB**, e a primeira linha é o cabeçalho;
- a busca aceita logradouro, bairro, cidade, sigla ou nome do estado e CEP, sem diferenciar acentos;
- a lista mostra 8 unidades por página, com botões "Como chegar" (Google Maps) e "Waze";
- o mapa do Google My Maps é reposicionado com a geocodificação do Nominatim (OpenStreetMap).

**Para adicionar ou remover uma loja**, edite as linhas desse bloco. Você pode colar direto da planilha: copiar as colunas do Excel ou do Google Sheets já gera texto separado por TAB.

Acréscimos desta versão:

- `unidades.html?q=termo` já abre com a busca preenchida (é assim que a busca da home funciona);
- botões e links com o atributo `data-lavo-sugestao="..."` disparam uma busca;
- elementos com `data-lavo-total` mostram o total de unidades.

## Identidade visual

- Roxo `#532458`, lilás `#BE94FF`, lima `#C5D539`, anil `#5E5FA0`
- Montserrat nos títulos e Open Sans no texto (Google Fonts)
- O motivo visual é a porta da máquina de lavar: anéis girando, círculos e bolhas

## Rodar localmente

Abra o `index.html` no navegador ou sirva a pasta:

```bash
python3 -m http.server 8080
```

## Publicar

Basta subir os arquivos para qualquer hospedagem estática, como Netlify, Vercel, GitHub Pages, Cloudflare Pages ou o próprio servidor atual.

## Observações

- Os links "Seja um franqueado" apontam para `https://lavobrasil.com.br/franquia/`, como no site atual.
- O link "Política de Privacidade" e os cards de notícias "boom em SC" e "Lavô Street" apontam para as páginas do WordPress atual. Atualize esses links se o WordPress for desativado.
- A faixa e o banner do sorteio BYD apontam para a landing page atual da campanha. Remova os dois quando a campanha acabar.

---

## Gerador de sites (pasta `gerador/`)

Ferramenta separada: recebe o link de qualquer site, gera uma versão redesenhada com IA, mostra uma prévia protegida e vende o código. Veja `gerador/README.md` e `gerador/CUSTOS.md`.
