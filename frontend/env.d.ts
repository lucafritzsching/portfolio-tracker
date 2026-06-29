/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL (incl. /api). Defaults to the local dev backend when unset. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
