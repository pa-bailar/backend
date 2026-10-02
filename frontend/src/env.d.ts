interface ImportMetaEnv {
  /** Set by the deploy workflow: when the daily sweep last checked Instagram (ISO time). */
  readonly PUBLIC_CHECKED_AT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
