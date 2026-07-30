# U3-A implementado — Generate desde UI

**Fecha cierre formal:** 2026-07-30
**Rama:** `integration/performance-and-ui`
**Estado:** **CERRADO.** Código + deploys Paso 1/2 en sandbox autorizados previamente. Generate operativo con `UI_WRITE_ENABLED=true`. Finalize **no** forma parte de U3-A (ver U3-B).

## Qué quedó

- CSRF: `GET /api/ui/v1/auth/csrf`; POST UI exige `X-CSRF-Token`.
- Write gate: sesión + Origin + JSON + CSRF + `UI_WRITE_ENABLED` + sandbox.
- `GenerateQueueService` compartido por `/graph/.../generate/queue` y `POST /api/ui/v1/processes/generate`.
- `GET /api/ui/v1/banks` → `available_actions.generate`.
- SPA: botones Bogotá/Bancolombia, modal, banner SANDBOX, poll job.

## Deploy ejecutado (histórico)

- Paso 1: `azure-deploy-u3a-writes-off.zip` (`UI_WRITE_ENABLED=false`).
- Paso 2: `azure-deploy-u3a-generate-enabled.zip` (`UI_WRITE_ENABLED=true`, Generate controlado Bogotá).

## Fuera de alcance U3-A

- Finalize / Notify / Merge / Dry-run / Apply → U3-B y siguientes.
- Migración `control_proceso_*` → lista (aplazada).
