# U4 — R2 Finalize atómico desde la revisión UI

**Rama:** `feat/ui-in-app-review-and-asientos`  
**Alcance:** un solo `POST` que aplica cambios opcionales, valida negocio, marca `Procesar=SI` y encola Finalize. Sin R3 (asientos), sin deploy.

## Flags

Requiere **ambos**:
- `UI_REVIEW_EDIT_ENABLED` (R1)
- `UI_FINALIZE_ENABLED`

Gate: `require_review_finalize_access`. Ambos apagados por defecto.

## Endpoint

`POST /api/ui/v1/processes/{process_key}/review/finalize` → **202**

Cadena atómica:

```text
If-Match (ETag)
→ aplicar changes[] (opcional; misma whitelist que PATCH)
→ preflight (colectores Finalize; sin escritura si falla)
→ Control.Procesar = SI (+ Estado EN_REVISION si hace falta)
→ put Excel SharePoint
→ enqueue FinalizeQueueService (igual que POST /processes/finalize)
```

| Caso | HTTP |
|---|---|
| OK | 202 + `job_id` / `poll_url` |
| Preflight fallido | 422 `review_preflight_blocked` + `issues[]` (**sin** put ni enqueue) |
| ETag viejo | 409 `review_etag_conflict` |
| Sin If-Match | 428 `missing_if_match` |
| Flag off | 403 |

Body: `{ "changes": [ { "row_key", "fields" } ] }` (puede ir vacío si ya guardó con PATCH).

El endpoint clásico `POST /api/ui/v1/processes/finalize` **sigue** para flujo Excel Online cuando `UI_REVIEW_EDIT_ENABLED=false`.

## UI

Con `review_edit_allowed` + `finalize_allowed`, «Finalizar revisión» usa el endpoint atómico (incluye cambios dirty del panel). Confirmación sin pedir cerrar Excel Online.

## Archivos

- `app/application/ui/review_finalize.py`
- `app/adapters/primary/http/ui/router_v1.py` / `write_deps.py`
- `frontend/src/pages/ProcessDetailPage.tsx` + `client.ts`
- `tests/test_ui_review_finalize_r2.py`
