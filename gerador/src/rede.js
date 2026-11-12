// Acesso seguro a sites informados pelo usuário.
// Bloqueia endereços internos (SSRF): a checagem acontece no momento da conexão,
// o que também protege contra "DNS rebinding".
import dns from "node:dns";
import net from "node:net";
import { Agent, ProxyAgent, fetch } from "undici";

const bloqueados = new net.BlockList();
for (const [rede, prefixo] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15],
  ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 4], ["240.0.0.0", 4],
]) bloqueados.addSubnet(rede, prefixo, "ipv4");
for (const [rede, prefixo] of [
  ["::", 128], ["::1", 128], ["fc00::", 7], ["fe80::", 10], ["ff00::", 8], ["64:ff9b::", 96], ["2001:db8::", 32],
]) bloqueados.addSubnet(rede, prefixo, "ipv6");

export function ipProibido(ip) {
  const mapeado = ip.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i);
  if (mapeado) return bloqueados.check(mapeado[1], "ipv4");
  return bloqueados.check(ip, net.isIPv6(ip) ? "ipv6" : "ipv4");
}

function lookupSeguro(hostname, opcoes, callback) {
  dns.lookup(hostname, { ...opcoes, all: true }, (erro, enderecos) => {
    if (erro) return callback(erro);
    const ruim = enderecos.find((e) => ipProibido(e.address));
    if (ruim || !enderecos.length) {
      const e = new Error(`Endereço não permitido: ${hostname}`);
      e.code = "ENDERECO_BLOQUEADO";
      return callback(e);
    }
    if (opcoes && opcoes.all) return callback(null, enderecos);
    callback(null, enderecos[0].address, enderecos[0].family);
  });
}

// Em desenvolvimento dentro de um ambiente com proxy obrigatório, defina PROXY_DESENVOLVIMENTO=1.
// NUNCA use isso em produção: o proxy resolve o DNS e a proteção acima deixa de valer.
const usarProxy = process.env.PROXY_DESENVOLVIMENTO === "1" && process.env.HTTPS_PROXY;
const agente = usarProxy
  ? new ProxyAgent(process.env.HTTPS_PROXY)
  : new Agent({ connect: { lookup: lookupSeguro, timeout: 10_000 } });

export function validarUrl(entrada) {
  let texto = String(entrada || "").trim();
  if (!/^https?:\/\//i.test(texto)) texto = "https://" + texto;
  let url;
  try {
    url = new URL(texto);
  } catch {
    throw new ErroUsuario("Endereço inválido. Exemplo: www.seusite.com.br");
  }
  if (!["http:", "https:"].includes(url.protocol)) throw new ErroUsuario("Use um endereço http ou https.");
  if (url.port && !["80", "443"].includes(url.port)) throw new ErroUsuario("Porta não permitida.");
  if (url.username || url.password) throw new ErroUsuario("Endereço inválido.");
  const host = url.hostname.toLowerCase();
  if (net.isIP(host.replace(/^\[|\]$/g, ""))) throw new ErroUsuario("Informe o domínio do site, não um IP.");
  if (!host.includes(".") || host.endsWith(".local") || host.endsWith(".internal") || host === "localhost")
    throw new ErroUsuario("Domínio inválido.");
  url.hash = "";
  return url;
}

export class ErroUsuario extends Error {}

/**
 * Baixa uma URL com limite de tamanho e de tempo, revalidando cada redirecionamento.
 * Retorna { url, status, tipo, corpo: Buffer }.
 */
export async function baixar(endereco, { limiteBytes = 3_000_000, tempo = 15_000, aceitar = "*/*" } = {}) {
  let url = typeof endereco === "string" ? validarUrl(endereco) : endereco;
  for (let saltos = 0; saltos < 5; saltos++) {
    const controle = AbortSignal.timeout(tempo);
    const resp = await fetch(url, {
      dispatcher: agente,
      redirect: "manual",
      signal: controle,
      headers: {
        "user-agent": "Mozilla/5.0 (compatible; GeradorDeSites/1.0)",
        accept: aceitar,
        "accept-language": "pt-BR,pt;q=0.9,en;q=0.6",
      },
    });
    if ([301, 302, 303, 307, 308].includes(resp.status)) {
      const destino = resp.headers.get("location");
      await resp.body?.cancel();
      if (!destino) throw new Error("Redirecionamento sem destino");
      url = validarUrl(new URL(destino, url).toString());
      continue;
    }
    const partes = [];
    let total = 0;
    if (resp.body) {
      for await (const pedaco of resp.body) {
        total += pedaco.length;
        if (total > limiteBytes) {
          await resp.body.cancel().catch(() => {});
          throw new Error("Arquivo grande demais");
        }
        partes.push(pedaco);
      }
    }
    return {
      url,
      status: resp.status,
      tipo: (resp.headers.get("content-type") || "").toLowerCase(),
      corpo: Buffer.concat(partes),
    };
  }
  throw new Error("Redirecionamentos demais");
}
