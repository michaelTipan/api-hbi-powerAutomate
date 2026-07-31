# U3-D — Procesar amortización desde la UI (implementación local Paso 1)

**Fecha:** 2026-07-31  
**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD inicial:** `a221c36e3dacb64b8a4ec5c017f5b933f10cd900`  
**Estado:** código + tests + ZIP off locales. **Sin deploy. Sin Dry-run/Apply reales.**

---

## Runtime conservado (ZIP Paso 1)

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true
UI_MERGE_ENABLED=true
UI_AMORTIZATION_ENABLED=false
UI_AUTH_MODE=local_session
EXTRACT_INDEX_MODE=off
```

Generate / Finalize / Notify / Merge permanecen habilitados. Amortización UI fail-closed.

---

## Arquitectura

### Prepare / execute (sin doble validación)

1. `prepare_amortization_application(...)` en `amortization_application_plan.py`
   - Una sola preparación financiera (`run_amortization_fill_dry_run` con `update_process_control=False` vía binding de apply).
   - Produce `AmortizationPreparedPlan` con `can_apply`, items, fingerprints (ProcessKey, hashes de manifiesto/histórico, PDFs, tablas, eventos).
   - **No** escribe tablas, IBR, PROCESADOS ni `EstadoProceso`.

2. Si `can_apply=false` → outcome `requires_correction`, job `completed`, cero escrituras.

3. Si `can_apply=true` → `execute_amortization_from_prepared`:
   - `verify_amortization_plan_freshness` (anti-stale).
   - Si insumos cambiaron → `input_changed_requires_retry`.
   - Si OK → escribe con el plan preparado (**sin** re-dry-run completo).

4. `run_amortization_fill_apply(..., prevalidated_plan=, update_control_on_reject=)` orquesta prepare+execute para PA (un solo prepare interno).

### AmortizationQueueService

| Método | Job type | Uso |
|--------|----------|-----|
| `enqueue_process_ui` | `amortization_process` | UI acción única |
| `enqueue_dry_run_pa` | `amortization_dry_run` | PA contrato intacto |
| `enqueue_apply_pa` | `amortization_apply` | PA contrato intacto |

Mutex compartido JobManager con Generate/Finalize/Notify/Merge/Amortización. Persistencia `.payment_validation_jobs`.

### JobManager

- `try_start_amortization` / `finish_amortization` / `is_amortization_active`
- `try_claim_amortization_for_process` → `ok|busy|already_applied`
- `has_completed_amortization` / `find_successful_amortization_by_process_key`
- Éxito solo: `amortization_apply` | `amortization_process` + applied/already_applied / `AMORTIZACION_APLICADA`
- Dry-run / requires_correction / partial **no** cuentan como applied

### Flag / UI

- `UI_AMORTIZATION_ENABLED` fail-closed → bootstrap `amortization_allowed`
- `POST /api/ui/v1/processes/amortization` body `{bank_code, process_key}` `extra=forbid`
- `AmortizationReadinessService` (función `assess_amortization_readiness`) read-only
- `available_actions.amortization` únicamente (sin dry_run/apply)
- SPA: “Procesar amortización” + modal + poll; sin palabra “Dry-run”

### Compatibilidad PA

- URLs dry-run/apply/queue y GET jobs intactas
- Body opcional intacto; 202 `{job_id,status}`
- Nuevo seguro: **409 busy** con mutex
- `infer_terminal_status_from_result` corregido vía QueueService (runners del router eliminados)

---

## ZIP Paso 1

| Archivo | Notas |
|---------|-------|
| `azure-deploy-u3d-amortization-off.zip` | `UI_AMORTIZATION_ENABLED=false`; Merge/Notify/Finalize/Write true |
| SHA-256 | `A89EC695249EA16285504603E88CE9403028FB8F04E24A8E3B432FBBF9870B64` |

---

## Pruebas

- Suite completa: **1247 passed**, 1 skipped
- Enfocados: JobManager amortización, queue service, UI amortization action, reglas financieras apply
- npm ci + npm run build OK
- Bundle: `POST /api/ui/v1/processes/amortization`; sin llamadas Graph dry-run/apply

---

## Confirmaciones

| Ítem | Estado |
|------|--------|
| Dry-run real SharePoint | **0** |
| Apply real | **0** |
| Tablas modificadas | **0** |
| Deploy | **0** |
| Producción | **0** |
| Push / merge git | **0** |
| Código + commits locales | sí |
| ZIP off | sí |

### Proceso referencia (no mutado)

`payment-validation|banco_bogota|2026-07-30|8a5c7ad3-faae-412f-928d-5878442c700d` — `CONSOLIDADO`
