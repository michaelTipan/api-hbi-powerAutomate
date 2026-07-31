# Implementación — U3-C2 Merge / Consolidar soportes (UI)

**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Estado:** Implementado **localmente** — Paso 1 ZIP con `UI_MERGE_ENABLED=false`.  
**NO autorizado aún:** deploy Azure, `UI_MERGE_ENABLED=true`, Merge real, Dry-run, Apply, push, merge git.

Plan: `docs/plans/u3c2-merge-from-ui.md`

---

## Runtime conservado (Paso 1)

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true
UI_MERGE_ENABLED=false
UI_AUTH_MODE=local_session
EXTRACT_INDEX_MODE=off
```

Generate / Finalize / Notify permanecen operativos. Merge UI cortado por flag.

---

## Piezas entregadas

| Pieza | Ubicación |
|-------|-----------|
| Flag | `UI_MERGE_ENABLED` → `feature_flags.merge_allowed` / bootstrap `merge_allowed` |
| JobManager | `try_start_merge`, `finish_merge`, `is_merge_active`, `try_claim_merge_for_process`, `has_completed_merge`, `find_successful_merge_by_process_key` |
| Cola | `MergeQueueService` (PA + UI) |
| PA | Mismos POST/GET; store JobManager; `force_rebuild` solo PA |
| UI POST | `POST /api/ui/v1/processes/merge` body `{bank_code, process_key}` |
| Readiness | `assess_merge_readiness` (read-only) |
| Availability | `compute_merge_availability` (puro) |
| Frontend | Botón **Consolidar soportes**; sin Dry-run/Apply |

### Diferencias PA vs UI en `already_merged`

| Canal | Comportamiento |
|-------|----------------|
| UI | **409** `already_merged` — sin job nuevo |
| PA sin `force_rebuild` | **202** reutilizando `job_id` previo (sin merge físico) |
| PA con `force_rebuild` | Reconstruye con mutex libre; concurrente → 409 busy |

### Dry-run / Apply

Fuera de U3-C2: sin botón, sin `available_actions`, sin POST UI. Pueden existir como steps internos traducidos (sin la palabra «Dry-run» en la UI).

---

## Rollback específico

```text
UI_MERGE_ENABLED=false
```

No apaga Generate / Finalize / Notify.

---

## Paso 2 (futuro, requiere autorización)

1. Deploy ZIP Paso 1 (merge off) — validar 403 UI + PA intacto.  
2. ZIP con `UI_MERGE_ENABLED=true` — Merge sandbox controlado.
