# U4-RC Release Manifest

## Congelación

| Campo | Valor |
|-------|-------|
| HEAD código | `001f2a9` |
| HEAD docs (tip al cierre) | ver `git log` en rama |
| Rama | `integration/performance-and-ui` |
| SPA | `index-DyDwMASQ.js` |
| Fecha congelación E2E | 2026-07-31 / 2026-08-01 |

## Paquetes

| Paquete | SHA-256 | Desplegado |
|---------|---------|------------|
| `azure-deploy-u4-rc-sandbox-final.zip` | `0010D0265D052F56FBAC3C03625DC75366749693B017948E723260C029B95342` | Sí (sandbox; re-despliegues VFS/ZipDeploy async según incidente) |
| `azure-deploy-u4-rc-production-candidate.zip` | `B833FA113EE7679CFD6AF3F2171C361A9B0412072C482B878E4E4C32559899E6` | **No** |

## Diff ZIP (sandbox vs production-candidate)

- Única diferencia de contenido: `.env` (overlay sandbox vs production).
- Código `app/`, SPA, requirements, startup: idénticos.
- Evidencia: `D:\CMC\HBI_Capital\_work\u4_rc\zip_diff_manifest.json`

## Suites / E2E (resumen)

| Control | Resultado |
|---------|-----------|
| pytest | 1301 passed / 1 skipped |
| frontend | 56 passed + tsc + build |
| E2E Bogotá | Generate→Amortización OK + idempotencia |
| Bancolombia | Notify + `already_notified` |
| Errores | 9/9 live + fixtures |
| Responsive | 61/61 |
| A11y axe | verde (suite previa U4-RC) |
| Deploy rm `.env` | verificado (2 deploys) |
| Overlay prod estático | OK |
| Paths-probe prod RO aislado | **NO ejecutado** (infra) |

## Incidentes

1. **Overlay `.env` stale (VFS)** — Kudu no borraba `.env` → App Service en
   production ~minutos; UI fail-closed; 0 escrituras detectadas; fix `a992588`.
2. **Claves Notify/Merge/Apply heredadas** — fix `001f2a9`.
3. **OneDeploy static restart** — resucita env/paquete stale; disco puede ser
   sandbox mientras worker sigue en production; UI 404; paths-probe RO prod
   hasta recycle real. **Prohibido** como restart post-VFS.

## Decisión

**NO LISTO PARA PRODUCCIÓN**

Bloqueantes exactos:

1. Paths-probe productivo read-only en runtime **aislado** no ejecutado
   (sin staging slot / App Service temporal / runtime local autorizado).
2. Recycle fiable del App Service tras overlay stale: `/api/app/restart` 403;
   riesgo de worker production con `.env` sandbox en disco hasta Portal/`az`
   o ZipDeploy async verificado en verde (bootstrap sandbox).
