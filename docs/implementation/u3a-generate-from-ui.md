# U3-A implementado — Generate desde UI (código local, sin deploy)

**Fecha:** 2026-07-30  
**Rama:** `integration/performance-and-ui`  
**Estado:** código + tests + commits locales. **Sin deploy, sin push, sin merge, `UI_WRITE_ENABLED` sigue false en Azure.**

## Qué quedó

- CSRF: `GET /api/ui/v1/auth/csrf`; POST UI (incl. logout) exige `X-CSRF-Token`.
- Write gate: sesión + Origin (`UI_ALLOWED_ORIGINS`) + JSON + CSRF + `UI_WRITE_ENABLED` + sandbox.
- `GenerateQueueService` compartido por `/graph/.../generate/queue` y `POST /api/ui/v1/processes/generate`.
- `GET /api/ui/v1/banks` → `available_actions.generate` (puro, sin adquirir locks).
- SPA: botones Bogotá/Bancolombia, modal, banner SANDBOX, poll job, CSRF en memoria.

## No incluido / aplazado

- Deploy U3-A y `UI_WRITE_ENABLED=true` en Azure.
- Finalize / Notify / Merge / Dry-run / Apply desde UI.
- Migración `control_proceso_*` → lista (`docs/plans/process-control-sharepoint-list.md` PAUSADO).

## Deploy Paso 1 (pendiente de autorización)

Mantener `UI_WRITE_ENABLED=false`, empaquetar, Kudu VFS, restart, validar login + read-only + PA; Generate UI debe responder 403 por write gate.
