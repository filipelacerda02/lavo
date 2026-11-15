// Utilidades compartilhadas por todas as telas do CRM.

window.api = async function api(caminho, opcoes = {}) {
  const cfg = { method: opcoes.method || 'GET', headers: { 'X-Requested-With': 'lavo' }, credentials: 'same-origin' }
  if (opcoes.corpo instanceof FormData) cfg.body = opcoes.corpo
  else if (opcoes.corpo !== undefined) {
    cfg.headers['Content-Type'] = 'application/json'
    cfg.body = JSON.stringify(opcoes.corpo)
  }
  const r = await fetch(caminho, cfg)
  if (r.status === 401 && !caminho.startsWith('/api/login')) {
    location.href = '/login'
    throw new Error('Sessão expirada')
  }
  const tipo = r.headers.get('content-type') || ''
  const dados = tipo.includes('application/json') ? await r.json() : await r.text()
  if (!r.ok) {
    let msg = dados && dados.detail ? dados.detail : `Erro ${r.status}`
    if (Array.isArray(msg)) msg = msg.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join('; ')
    throw new Error(msg)
  }
  return dados
}

window.avisar = function avisar(texto, erro = false) {
  let caixa = document.querySelector('.avisos')
  if (!caixa) {
    caixa = document.createElement('div')
    caixa.className = 'avisos'
    document.body.appendChild(caixa)
  }
  const el = document.createElement('div')
  el.className = 'aviso' + (erro ? ' erro' : '')
  el.textContent = texto
  caixa.appendChild(el)
  setTimeout(() => el.remove(), erro ? 6000 : 3500)
}

// Executa uma ação e mostra o erro, se houver.
window.tentar = async function tentar(fn, sucesso) {
  try {
    const r = await fn()
    if (sucesso) avisar(sucesso)
    return r
  } catch (e) {
    avisar(e.message, true)
    throw e
  }
}

// ---------- eventos em tempo real (SSE) -> window 'lavo:<tipo>'
;(function conectarEventos() {
  if (location.pathname === '/login' || location.pathname === '/setup') return
  let fonte
  const abrir = () => {
    fonte = new EventSource('/api/eventos')
    for (const tipo of ['conversa', 'mensagem', 'contato', 'tarefa', 'funil', 'agente_status', 'whatsapp', 'notificacao', 'equipe', 'recibo', 'modelo', 'campanha']) {
      fonte.addEventListener(tipo, (e) => {
        window.dispatchEvent(new CustomEvent('lavo:' + tipo, { detail: JSON.parse(e.data || 'null') }))
      })
    }
    fonte.onerror = () => {
      fonte.close()
      setTimeout(abrir, 4000)
    }
  }
  abrir()
})()

// ---------- formatação
window.fmt = {
  hora(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    const hoje = new Date()
    if (d.toDateString() === hoje.toDateString()) return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' +
      d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  },
  data(iso) {
    return iso ? new Date(iso).toLocaleDateString('pt-BR') : ''
  },
  dataHora(iso) {
    return iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : ''
  },
  relativo(iso) {
    if (!iso) return ''
    const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
    if (s < 60) return 'agora'
    if (s < 3600) return `${Math.floor(s / 60)} min`
    if (s < 86400) return `${Math.floor(s / 3600)} h`
    return `${Math.floor(s / 86400)} d`
  },
  dinheiro(v) {
    return (v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
  },
  telefone(t) {
    if (!t) return ''
    const d = t.replace(/\D/g, '')
    if (d.length === 13) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`
    if (d.length === 12) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`
    return t
  },
  iniciais(nome) {
    return (nome || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('')
  },
  duracao(s) {
    if (s == null) return '—'
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.round(s / 60)} min`
    return `${(s / 3600).toFixed(1)} h`
  },
}

// Estado global da barra superior: agente e WhatsApp.
window.barraTopo = function barraTopo() {
  return {
    agente: null,
    wpp: null,
    async iniciar() {
      await Promise.all([this.carregarAgente(), this.carregarWpp()])
      window.addEventListener('lavo:agente_status', () => this.carregarAgente())
      window.addEventListener('lavo:whatsapp', (e) => (this.wpp = e.detail))
      setInterval(() => this.carregarAgente(), 60000)
    },
    async carregarAgente() {
      try { this.agente = await api('/api/agente/status') } catch (e) { /* offline */ }
    },
    async carregarWpp() {
      try { this.wpp = await api('/api/whatsapp/status') } catch (e) { /* offline */ }
    },
    get wppTexto() {
      if (!this.wpp) return 'WhatsApp…'
      return { conectado: 'WhatsApp oficial conectado', nao_configurado: 'WhatsApp não configurado',
        erro: 'Erro na Cloud API', desconhecido: 'WhatsApp…' }[this.wpp.estado] || this.wpp.estado
    },
  }
}

window.sair = async function sair() {
  await api('/api/logout', { method: 'POST' })
  location.href = '/login'
}

// ---------- notificações (navegador + som), como nos CRMs de atendimento
window.notificacoes = {
  ativas() { return 'Notification' in window && Notification.permission === 'granted' },
  async ativar() {
    if (!('Notification' in window)) return avisar('Este navegador não suporta notificações.', true)
    const r = await Notification.requestPermission()
    avisar(r === 'granted' ? 'Notificações ativadas' : 'Notificações bloqueadas no navegador', r !== 'granted')
  },
  bip() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      const o = ctx.createOscillator(); const g = ctx.createGain()
      o.frequency.value = 880; g.gain.value = 0.06
      o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.15)
    } catch (e) { /* sem áudio */ }
  },
}
window.addEventListener('lavo:notificacao', (e) => {
  const n = e.detail || {}
  if (!window.USUARIO) return
  if (n.usuario_id && n.usuario_id !== USUARIO.id) return
  // "fila" vai para quem está disponível; o resto é direcionado
  if (n.tipo === 'fila' && window.MEU_STATUS && window.MEU_STATUS !== 'online') return
  const abrir = () => { if (n.conversa_id) location.href = '/conversas?c=' + n.conversa_id }
  notificacoes.bip()
  if (notificacoes.ativas() && document.hidden) {
    const notif = new Notification('Lavo CRM', { body: n.texto, tag: 'conv-' + (n.conversa_id || '') })
    notif.onclick = () => { window.focus(); abrir() }
  } else if (!(location.pathname === '/conversas' && n.tipo === 'mensagem')) {
    avisar('🔔 ' + n.texto)
  }
})

window.fmt.prazo = function prazo(iso) {
  if (!iso) return ''
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  const abs = Math.abs(s)
  const t = abs < 3600 ? `${Math.max(1, Math.round(abs / 60))} min` : abs < 86400 ? `${Math.round(abs / 3600)} h` : `${Math.round(abs / 86400)} d`
  return s >= 0 ? `vence em ${t}` : `estourou há ${t}`
}
window.ROTULO_PRIORIDADE = { baixa: 'Baixa', media: 'Média', alta: 'Alta', urgente: 'Urgente' }

// Componente reutilizável: escolher um modelo aprovado e preencher as variáveis.
window.seletorModelo = function seletorModelo() {
  return {
    modelos: [], modeloId: '', vars: [], varsCab: [],
    async carregarModelos() { this.modelos = (await api('/api/modelos')).filter((m) => m.status === 'APPROVED') },
    get modelo() { return this.modelos.find((m) => m.id === Number(this.modeloId)) },
    escolher() {
      const m = this.modelo
      this.vars = m ? Array(m.variaveis.corpo).fill('') : []
      this.varsCab = m ? Array(m.variaveis.cabecalho).fill('') : []
    },
    get previaModelo() {
      if (!this.modelo) return ''
      let t = this.modelo.previa
      this.varsCab.forEach((v, i) => { t = t.replace(`{{${i + 1}}}`, v || `{{${i + 1}}}`) })
      this.vars.forEach((v, i) => { t = t.replace(`{{${i + 1}}}`, v || `{{${i + 1}}}`) })
      return t
    },
  }
}
window.ROTULO_CATEGORIA = { MARKETING: 'Marketing', UTILITY: 'Utilidade', AUTHENTICATION: 'Autenticação' }

window.fmt.variavel = (i) => '{' + '{' + (i + 1) + '}' + '}'  // sem chaves duplas literais: os templates usam Jinja
