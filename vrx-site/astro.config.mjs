// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: process.env.SITE_URL || "https://vrxequipamentos.com.br",
  output: "static", // SSG: HTML pronto na borda da CDN
  trailingSlash: "never",
  build: {
    format: "file",
    // Nada de CSS/JS embutido no HTML: permite uma CSP estrita (sem 'unsafe-inline')
    inlineStylesheets: "never",
  },
  prefetch: { prefetchAll: true, defaultStrategy: "viewport" },
  integrations: [
    sitemap({
      filter: (page) => !page.includes("/404"),
    }),
  ],
  image: {
    layout: "constrained",
    responsiveStyles: false,
  },
  vite: {
    plugins: [tailwindcss()],
    build: { assetsInlineLimit: 0 },
  },
});
