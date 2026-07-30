# U3-B implementado — Finalize desde UI (código local, sin deploy)

**Fecha:** 2026-07-30  
**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Estado:** código + tests + frontend + docs + ZIP local. **Sin deploy, sin push, sin merge.**  
**Runtime:** `UI_FINALIZE_ENABLED` ausente/false; Generate permanece habilitado.

## Qué quedó

- `FinalizeQueueService` — única orquestación de cola para PA y UI (lock → job → background → use case → `infer_terminal_status_from_result` → finish).
- Bug preexistente: el runner PA llamaba `infer_terminal_status_from_result` sin import; corregido al centralizar en el servicio (y `already_finalized` → `SKIPPED_IDEMPOTENT` en el helper).
- Gate `UI_FINALIZE_ENABLED` (default false, parseo estricto fail-closed) encima del write gate.
- `POST /api/ui/v1/processes/finalize` body `{ bank_code, process_key }` (`extra=forbid`).
- Resolución barata de identidad desde Excel de control (`ValidationFilePath`); 409 si ProcessKey/banco/estado incompatibles.
- `available_actions.finalize` + checklist operativo desde constantes de `review_schema`.
- SPA (detalle): Finalizar validación, Abrir Excel, Actualizar estado, checklist, modal, poll vía `GET /jobs/{id}`.

## Contrato PA preservado

`POST /graph/sharepoint/payment-validation/finalize/queue` — mismos campos opcionales, 202 `{job_id, status}`, auth X-API-Key, mismo JobManager.

## No autorizado / no hecho

- Deploy U3-B; `UI_FINALIZE_ENABLED=true`; Finalize real; editar Excel de revisión.
- Notify / Merge / Dry-run / Apply; producción; push; merge a develop.
- Migración control → listas.

## ZIP local (no desplegar)

`azure-deploy-u3b-finalize-off.zip` con sandbox, UI on, write on, **finalize off**, mocks off, índice off.

## Deploy futuro Paso 1 (no ejecutar)

Empaquetar/deploy con `UI_FINALIZE_ENABLED=false`, validar Generate + Finalize UI 403 + PA intacto; solo después autorizar Paso 2 con flag true y Finalize controlado.
