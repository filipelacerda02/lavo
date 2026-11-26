/** Carrega o Cloudflare Turnstile (anti-robô) só nas páginas com formulário, se houver chave configurada. */
declare global {
  interface Window { turnstile?: { render: (el: string | HTMLElement, o: Record<string, unknown>) => string; reset: (id?: string) => void } }
}

export interface Desafio { token: () => string; reiniciar: () => void; ativo: boolean }

export function montarTurnstile(alvo: string, chave: string | undefined): Desafio {
  let token = "";
  let widget: string | undefined;
  if (chave) {
    const desenhar = () => {
      widget = window.turnstile?.render(alvo, { sitekey: chave, language: "pt-br", callback: (t: string) => (token = t), "expired-callback": () => (token = "") });
    };
    if (window.turnstile) desenhar();
    else {
      const s = document.createElement("script");
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      s.async = true;
      s.onload = desenhar;
      document.head.appendChild(s);
    }
  }
  return {
    token: () => token,
    reiniciar: () => {
      token = "";
      if (widget) window.turnstile?.reset(widget);
    },
    ativo: Boolean(chave),
  };
}
