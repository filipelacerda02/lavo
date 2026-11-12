// Armazenamento simples em arquivos JSON (um diretório por projeto).
// Para volume alto, troque por um banco de dados (Postgres, SQLite...).
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { config } from "./config.js";

const raiz = path.join(config.pastaDados, "projetos");

export const novoId = () => crypto.randomBytes(12).toString("base64url");
export const novoToken = () => crypto.randomBytes(24).toString("base64url");

const idValido = (id) => typeof id === "string" && /^[A-Za-z0-9_-]{16}$/.test(id);

export function pastaProjeto(id) {
  if (!idValido(id)) throw new Error("id inválido");
  return path.join(raiz, id);
}

export function criarProjeto(dados) {
  const id = novoId();
  const projeto = {
    id,
    status: "fila",
    etapa: "Na fila",
    criadoEm: new Date().toISOString(),
    pago: false,
    ...dados,
  };
  fs.mkdirSync(pastaProjeto(id), { recursive: true });
  salvar(projeto);
  return projeto;
}

export function obter(id) {
  if (!idValido(id)) return null;
  try {
    return JSON.parse(fs.readFileSync(path.join(pastaProjeto(id), "projeto.json"), "utf8"));
  } catch {
    return null;
  }
}

export function salvar(projeto) {
  const arq = path.join(pastaProjeto(projeto.id), "projeto.json");
  fs.writeFileSync(arq + ".tmp", JSON.stringify(projeto, null, 2));
  fs.renameSync(arq + ".tmp", arq);
}

export function atualizar(id, mudancas) {
  const p = obter(id);
  if (!p) return null;
  Object.assign(p, mudancas);
  salvar(p);
  return p;
}

export function listar() {
  if (!fs.existsSync(raiz)) return [];
  return fs
    .readdirSync(raiz)
    .map((id) => obter(id))
    .filter(Boolean)
    .sort((a, b) => b.criadoEm.localeCompare(a.criadoEm));
}

// Prévia já gerada para o mesmo domínio nos últimos N dias
export function buscarPorDominio(dominio, dias) {
  const limite = Date.now() - dias * 864e5;
  return listar().find(
    (p) => p.dominio === dominio && p.status !== "erro" && new Date(p.criadoEm).getTime() > limite,
  );
}
