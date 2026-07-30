# Operator Web UI (Fase U1)

SPA React + Vite + TypeScript. Contrato: `../docs/ui-api-contract-v1.md`.

## Desarrollo local (mocks)

```bash
cd frontend
npm install
npm run dev
```

Por defecto `VITE_UI_USE_MOCKS` no es `false` → usa mocks del contrato.

Para apuntar a API (app de test / futuro cableado):

```bash
set VITE_UI_USE_MOCKS=false
set VITE_UI_BEARER=mock-user
npm run dev
```

## Build

```bash
npm run build
```

Salida en `frontend/dist/` (**no versionar**). El empaquetado Azure lo hará
`integration/performance-and-ui` vía `build-azure-package.ps1`.

## Base path

`base: /app/` — listo para StaticFiles cuando se cablee en integración.
