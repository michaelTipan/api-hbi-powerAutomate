# U4-RC Release Manifest

## Congelación

| Campo | Valor |
|-------|-------|
| HEAD | `001f2a9` |
| Rama | `integration/performance-and-ui` |
| SPA | `index-DyDwMASQ.js` |
| Fecha | 2026-07-31 |

## Paquetes

| Paquete | SHA-256 | Desplegado |
|---------|---------|------------|
| `azure-deploy-u4-rc-sandbox-final.zip` | `0010D0265D052F56FBAC3C03625DC75366749693B017948E723260C029B95342` | Sí (sandbox) |
| `azure-deploy-u4-rc-production-candidate.zip` | `B833FA113EE7679CFD6AF3F2171C361A9B0412072C482B878E4E4C32559899E6` | **No** |

## Diff ZIP

- Única diferencia de contenido: `.env` (overlay sandbox vs production).
- Código `app/`, SPA, requirements, startup: idénticos.
- Evidencia: `D:\CMC\HBI_Capital\_work\u4_rc\zip_diff_manifest.json`

## Incidentes

1. **Overlay `.env` stale** — Kudu no borraba `.env` → App Service quedó en production ~minutos; UI fail-closed; 0 escrituras detectadas; fix `a992588` + doble deploy sandbox.
2. **Claves Notify/Merge/Apply heredadas** — Generate/Finalize no limpiaban idempotency del ProcessKey anterior; fix `001f2a9`.

## Decisión

**NO LISTO PARA PRODUCCIÓN** — falta paths-probe productivo read-only en runtime aislado (bloqueante de infraestructura formal).
