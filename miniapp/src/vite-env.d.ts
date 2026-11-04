/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev only: signed init data used when Telegram provides none. */
  readonly VITE_DEV_INIT_DATA?: string;
}
