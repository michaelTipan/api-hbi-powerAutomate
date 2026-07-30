# U3-B implementado — Finalize desde UI (código local, sin deploy)

**Fecha:** 2026-07-30  
**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD:** `1b1154041ba89b72b15bf4990319a010fc5c779a`  
**Estado:** código + tests + frontend + docs + ZIP Paso 1 off. **Sin deploy, sin push, sin merge.**  
**Runtime objetivo del ZIP:** `UI_WRITE_ENABLED=true`, `UI_FINALIZE_ENABLED=false`, sandbox.

## Qué quedó

- `FinalizeQueueService` — única orquestación de cola para PA y UI (lock → job → background → use case → `infer_terminal_status_from_result` → finish).
- Bug preexistente: el runner PA llamaba `infer_terminal_status_from_result` sin import; corregido al centralizar en el servicio (y `already_finalized` → `SKIPPED_IDEMPOTENT` en el helper).
- Gate `UI_FINALIZE_ENABLED` (default false, parseo estricto fail-closed) encima del write gate.
- `POST /api/ui/v1/processes/finalize` body `{ bank_code, process_key }` (`extra=forbid`).
- Resolución barata de identidad desde Excel de control (`ValidationFilePath`); 409 si ProcessKey/banco/estado incompatibles.
- `available_actions.finalize` + checklist operativo desde constantes de `review_schema`.
- SPA (detalle): Finalizar validación, Abrir Excel, Actualizar estado, checklist, modal, poll vía `GET /jobs/{id}`.

## Fixes de develop incorporados

| develop | En esta rama | Equivalencia |
|---|---|---|
| `d68987a` deploy preproduccion | `c717eb7` | cancel use case + tests: mismo patch-id |
| `adb126d` Extracto + Notify | `d8af1a5` | notify template: mismo patch-id |
| (adaptación) | `1b11540` | paridad extract-index V2 + guards UI/cancel |

`origin/develop` tip = `adb126d` — **no** hay commits posteriores pendientes en develop.

## Verificación local

- Suite: **1160 passed**, 1 skipped.
- Colas UI/PA: Generate/Finalize vía servicios compartidos; cancel PA conservado.

## Contrato PA preservado

`POST /graph/sharepoint/payment-validation/finalize/queue` — mismos campos opcionales, 202 `{job_id, status}`, auth X-API-Key, mismo JobManager.

## No autorizado / no hecho

- Deploy U3-B; `UI_FINALIZE_ENABLED=true`; Finalize real; editar Excel de revisión.
- Notify / Merge / Dry-run / Apply desde UI; producción; push; merge a develop.
- Migración control → listas.

## ZIP Paso 1 (no desplegar)

- **Vigente:** `D:\CMC\HBI_Capital\azure-deploy-u3b-finalize-off-with-develop-fixes.zip`  
  - Código base: `1b11540` (tip docs `21857ff`, sin cambios en `app/`).  
  - SHA-256: `2EB7F2BA55CCCFB2FDB90B8D24394A1ABDA92FB4488D27612118E4BDC68D4A54`  
  - Flags: sandbox · `UI_WRITE_ENABLED=true` · `UI_FINALIZE_ENABLED=false` · índice off · mocks off.
- **Obsoleto:** `azure-deploy-u3b-finalize-off.OBSOLETE.zip` (pre-fixes develop).

## Deploy futuro Paso 1 (no ejecutar aún)

Desplegar el ZIP vigente con Finalize off; validar Generate + Finalize UI 403 + PA + cancel; solo después autorizar Paso 2 con `UI_FINALIZE_ENABLED=true`.
