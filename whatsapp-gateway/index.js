// Gateway WhatsApp (WhatsApp Web via QR code) para o CRM Lavo.
//
// Usa o Baileys (biblioteca NÃO oficial). Mantém uma sessão do WhatsApp Web,
// expõe o QR code, envia mensagens e repassa tudo que chega para o CRM via webhook.
//
// Variáveis de ambiente:
//   PORTA=3001
//   GATEWAY_TOKEN=...            (o mesmo do CRM; protege as rotas e o webhook)
//   CRM_WEBHOOK_URL=http://localhost:8000/api/whatsapp/webhook
//   PASTA_SESSAO=./sessao         (credenciais do WhatsApp — trate como senha)

import http from 'node:http'
import fs from 'node:fs/promises'
import path from 'node:path'
import QRCode from 'qrcode'
import pino from 'pino'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidBroadcast,
  isJidGroup,
  isJidStatusBroadcast,
  isLidUser,
  isPnUser,
  jidNormalizedUser,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'

const PORTA = Number(process.env.PORTA || 3001)
const TOKEN = process.env.GATEWAY_TOKEN || ''
const WEBHOOK = process.env.CRM_WEBHOOK_URL || 'http://localhost:8000/api/whatsapp/webhook'
const PASTA_SESSAO = path.resolve(process.env.PASTA_SESSAO || './sessao')
const logger = pino({ level: process.env.LOG_LEVEL || 'warn' })

if (!TOKEN) {
  console.error('Defina GATEWAY_TOKEN (o mesmo valor configurado no CRM).')
  process.exit(1)
}

const estado = { estado: 'desconectado', qr: null, numero: null, nome: null, erro: null }
let sock = null
let iniciando = false
const enviadasPeloCrm = new Set() // ids das mensagens enviadas via API (não são "do celular")
const inicioDoProcesso = Math.floor(Date.now() / 1000)

async function avisarCrm(evento) {
  try {
    await fetch(WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Gateway-Token': TOKEN },
      body: JSON.stringify(evento),
    })
  } catch (e) {
    logger.warn({ err: String(e) }, 'falha ao avisar o CRM')
  }
}

async function mudarEstado(parcial) {
  Object.assign(estado, parcial)
  await avisarCrm({ tipo: 'status', ...publico() })
}

function publico() {
  return { estado: estado.estado, qr: estado.qr, numero: estado.numero, nome: estado.nome, erro: estado.erro }
}

function textoDaMensagem(m) {
  const msg = m.message || {}
  const conteudo = msg.ephemeralMessage?.message || msg.viewOnceMessage?.message || msg
  if (conteudo.conversation) return { texto: conteudo.conversation, midia: null }
  if (conteudo.extendedTextMessage?.text) return { texto: conteudo.extendedTextMessage.text, midia: null }
  if (conteudo.imageMessage) return { texto: conteudo.imageMessage.caption || '', midia: 'imagem' }
  if (conteudo.videoMessage) return { texto: conteudo.videoMessage.caption || '', midia: 'video' }
  if (conteudo.documentMessage) return { texto: conteudo.documentMessage.fileName || '', midia: 'documento' }
  if (conteudo.audioMessage) return { texto: '', midia: 'audio' }
  if (conteudo.stickerMessage) return { texto: '', midia: 'figurinha' }
  if (conteudo.locationMessage) return { texto: '', midia: 'localizacao' }
  if (conteudo.contactMessage) return { texto: conteudo.contactMessage.displayName || '', midia: 'contato' }
  return null // reações, protocolos, etc.
}

function telefoneDe(key) {
  // Baileys v7: o chat pode vir por LID; o número real fica em remoteJidAlt.
  const candidatos = [key.remoteJid, key.remoteJidAlt].filter(Boolean)
  const pn = candidatos.find((j) => isPnUser(j))
  return pn ? jidNormalizedUser(pn).split('@')[0] : null
}

async function conectar() {
  if (sock || iniciando) return
  iniciando = true
  try {
    await fs.mkdir(PASTA_SESSAO, { recursive: true })
    const { state, saveCreds } = await useMultiFileAuthState(PASTA_SESSAO)
    let version
    try {
      ;({ version } = await fetchLatestBaileysVersion())
    } catch {
      version = undefined // usa a versão embutida
    }
    await mudarEstado({ estado: 'conectando', erro: null })
    sock = makeWASocket({
      auth: state,
      version,
      logger,
      browser: Browsers.ubuntu('Lavo CRM'),
      markOnlineOnConnect: false, // não "rouba" as notificações do celular
      syncFullHistory: false,
    })

    sock.ev.on('creds.update', saveCreds)

    sock.ev.on('connection.update', async (u) => {
      if (u.qr) {
        await mudarEstado({ estado: 'aguardando_qr', qr: await QRCode.toDataURL(u.qr, { margin: 1, width: 320 }) })
      }
      if (u.connection === 'open') {
        const eu = sock.user || {}
        await mudarEstado({
          estado: 'conectado',
          qr: null,
          numero: eu.id ? jidNormalizedUser(eu.id).split('@')[0] : null,
          nome: eu.name || null,
          erro: null,
        })
      }
      if (u.connection === 'close') {
        const codigo = u.lastDisconnect?.error?.output?.statusCode
        sock = null
        if (codigo === DisconnectReason.loggedOut) {
          await fs.rm(PASTA_SESSAO, { recursive: true, force: true })
          await mudarEstado({ estado: 'desconectado', qr: null, numero: null, nome: null, erro: 'Sessão encerrada no celular.' })
          return
        }
        await mudarEstado({ estado: 'conectando', qr: null, erro: `Conexão caiu (${codigo ?? '?'}), reconectando...` })
        setTimeout(conectar, 3000)
      }
    })

    sock.ev.on('messages.upsert', async ({ messages }) => {
      for (const m of messages) {
        const jid = m.key?.remoteJid
        if (!jid || isJidGroup(jid) || isJidBroadcast(jid) || isJidStatusBroadcast(jid)) continue
        if (!isPnUser(jid) && !isLidUser(jid)) continue
        const ts = Number(m.messageTimestamp || 0)
        if (ts && ts < inicioDoProcesso - 120) continue // ignora histórico antigo
        const conteudo = textoDaMensagem(m)
        if (!conteudo) continue
        const id = m.key.id
        if (m.key.fromMe && enviadasPeloCrm.has(id)) {
          enviadasPeloCrm.delete(id)
          continue // já registrada pelo CRM
        }
        await avisarCrm({
          tipo: 'mensagem',
          id,
          jid,
          telefone: telefoneDe(m.key),
          nome: m.key.fromMe ? null : m.pushName || null,
          de_mim: Boolean(m.key.fromMe), // true = enviada pelo celular da empresa
          texto: conteudo.texto,
          midia: conteudo.midia,
          timestamp: ts || Math.floor(Date.now() / 1000),
        })
      }
    })
  } catch (e) {
    sock = null
    await mudarEstado({ estado: 'desconectado', erro: String(e) })
  } finally {
    iniciando = false
  }
}

async function desconectar() {
  if (sock) {
    try {
      await sock.logout()
    } catch {
      /* já caiu */
    }
  }
  sock = null
  await fs.rm(PASTA_SESSAO, { recursive: true, force: true })
  await mudarEstado({ estado: 'desconectado', qr: null, numero: null, nome: null, erro: null })
}

async function enviar({ jid, texto }) {
  if (!sock || estado.estado !== 'conectado') throw Object.assign(new Error('WhatsApp não conectado'), { status: 409 })
  if (!jid || typeof texto !== 'string' || !texto.trim()) throw Object.assign(new Error('jid e texto obrigatórios'), { status: 400 })
  const r = await sock.sendMessage(jid, { text: texto })
  if (r?.key?.id) {
    enviadasPeloCrm.add(r.key.id)
    setTimeout(() => enviadasPeloCrm.delete(r.key.id), 10 * 60 * 1000)
  }
  return { id: r?.key?.id || null }
}

async function digitando({ jid, ativo }) {
  if (sock && estado.estado === 'conectado' && jid) {
    await sock.sendPresenceUpdate(ativo ? 'composing' : 'paused', jid).catch(() => {})
  }
  return { ok: true }
}

function lerCorpo(req) {
  return new Promise((resolve, reject) => {
    let dados = ''
    req.on('data', (c) => {
      dados += c
      if (dados.length > 1e6) reject(Object.assign(new Error('corpo grande demais'), { status: 413 }))
    })
    req.on('end', () => {
      try {
        resolve(dados ? JSON.parse(dados) : {})
      } catch {
        reject(Object.assign(new Error('JSON inválido'), { status: 400 }))
      }
    })
  })
}

const rotas = {
  'GET /status': async () => publico(),
  'POST /conectar': async () => (conectar(), publico()),
  'POST /desconectar': async () => (await desconectar(), publico()),
  'POST /enviar': async (corpo) => enviar(corpo),
  'POST /digitando': async (corpo) => digitando(corpo),
}

http
  .createServer(async (req, res) => {
    const responder = (status, obj) => {
      res.writeHead(status, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(obj))
    }
    if (req.headers['x-gateway-token'] !== TOKEN) return responder(401, { erro: 'token inválido' })
    const rota = rotas[`${req.method} ${req.url.split('?')[0]}`]
    if (!rota) return responder(404, { erro: 'rota inexistente' })
    try {
      responder(200, await rota(req.method === 'POST' ? await lerCorpo(req) : {}))
    } catch (e) {
      responder(e.status || 500, { erro: e.message })
    }
  })
  .listen(PORTA, () => {
    console.log(`Gateway WhatsApp ouvindo na porta ${PORTA}`)
    // Se já existe sessão salva, reconecta sozinho.
    fs.access(path.join(PASTA_SESSAO, 'creds.json')).then(conectar, () => {})
  })
