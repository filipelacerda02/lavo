# Imagem oficial do Playwright: já vem com o Chromium e as bibliotecas do sistema
FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /app
ENV NODE_ENV=production PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
# Os projetos gerados ficam em /app/dados: monte um volume aqui para não perdê-los
VOLUME ["/app/dados"]
EXPOSE 3000
CMD ["node", "src/server.js"]
