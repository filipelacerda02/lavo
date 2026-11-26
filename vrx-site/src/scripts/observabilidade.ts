/**
 * Observabilidade sem comprometer a privacidade:
 * - Core Web Vitals (LCP, INP, CLS, FCP, TTFB) enviados para /api/metricas, sem cookies,
 *   sem identificadores e sem IP armazenado (só página, métrica e valor).
 * - Erros de JavaScript no Sentry, somente se PUBLIC_SENTRY_DSN estiver configurado,
 *   com coleta de dados pessoais desligada e sem gravação de sessão.
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from "web-vitals";

let enviado = false;
if (!enviado) {
  enviado = true;
  const fila: Array<Record<string, string | number>> = [];
  const registrar = (m: Metric) => {
    fila.push({ nome: m.name, valor: Math.round(m.name === "CLS" ? m.value * 1000 : m.value), nota: m.rating, pagina: location.pathname, nav: m.navigationType });
  };
  const despachar = () => {
    if (!fila.length) return;
    const corpo = JSON.stringify(fila.splice(0));
    if (!navigator.sendBeacon?.("/api/metricas", new Blob([corpo], { type: "application/json" }))) {
      void fetch("/api/metricas", { method: "POST", body: corpo, keepalive: true, headers: { "content-type": "application/json" } }).catch(() => {});
    }
  };
  onLCP(registrar);
  onINP(registrar);
  onCLS(registrar);
  onFCP(registrar);
  onTTFB(registrar);
  addEventListener("visibilitychange", () => document.visibilityState === "hidden" && despachar());
  addEventListener("pagehide", despachar);

  const dsn = import.meta.env.PUBLIC_SENTRY_DSN as string | undefined;
  if (dsn) {
    void import("@sentry/browser").then((Sentry) =>
      Sentry.init({
        dsn,
        // não coleta dados do usuário, cookies, cabeçalhos nem parâmetros de URL
        dataCollection: { userInfo: false, cookies: false, httpHeaders: false, urlQueryParams: false },
        tracesSampleRate: 0,
        environment: import.meta.env.MODE,
        beforeSend(evento) {
          // remove dados que poderiam identificar a pessoa
          delete evento.user;
          if (evento.request) delete evento.request.cookies;
          return evento;
        },
      }),
    );
  }
}
