interface ImportMetaEnv {
  readonly PUBLIC_TURNSTILE_SITE_KEY?: string;
  readonly PUBLIC_GA_ID?: string;
  readonly PUBLIC_META_PIXEL_ID?: string;
  readonly PUBLIC_SENTRY_DSN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
