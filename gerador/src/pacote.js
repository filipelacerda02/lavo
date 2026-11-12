// Monta o .zip entregue após a compra.
import fs from "node:fs";
import path from "node:path";
import JSZip from "jszip";

export async function montarZip(pasta, projeto) {
  const zip = new JSZip();
  const html = fs.readFileSync(path.join(pasta, "index.html"), "utf8");
  zip.file("index.html", html);
  const usadas = new Set([...html.matchAll(/img\/\d+\.(?:jpg|png|webp|gif|svg|avif)/g)].map((m) => m[0]));
  for (const rel of usadas) {
    const arq = path.join(pasta, rel);
    if (fs.existsSync(arq)) zip.file(rel, fs.readFileSync(arq));
  }
  zip.file(
    "LEIA-ME.txt",
    `Seu novo site (${projeto.dominio})

Conteúdo
- index.html: o site completo (HTML, CSS e JavaScript no mesmo arquivo)
- img/: as imagens usadas

Como publicar
1. Envie a pasta inteira para a raiz da sua hospedagem (via painel de arquivos ou FTP),
   ou arraste a pasta em app.netlify.com/drop para publicar grátis em segundos.
2. Para editar textos, abra o index.html em qualquer editor de texto.

As imagens e os textos vieram do site original. Confirme que você tem os direitos de uso.
`,
  );
  return zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
}
