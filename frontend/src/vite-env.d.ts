/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_UI_USE_MOCKS?: string;
  readonly VITE_UI_BEARER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
