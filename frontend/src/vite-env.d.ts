/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Django API base URL. Defaults to http://127.0.0.1:8000 in development. */
  readonly VITE_API_BASE_URL?: string
  /** MapLibre style URL replacing the default (Streets) basemap. */
  readonly VITE_MAP_STYLE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
