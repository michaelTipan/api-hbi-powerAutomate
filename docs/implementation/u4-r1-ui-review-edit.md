# U4 — R1 edición UI del Excel de revisión

**Rama:** `feat/ui-in-app-review-and-asientos`  
**Alcance:** Guardar parcial + preflight dry-run. Sin Finalize atómico (R2), upload asientos (R3), merge ni deploy.

## Feature flag

`UI_REVIEW_EDIT_ENABLED` — **apagado por defecto** (fail-closed).  
Requiere también `UI_ENABLED` + `UI_WRITE_ENABLED` + sandbox.  
Bootstrap expone `review_edit_allowed`.

## Endpoints

| Método | Ruta | Notas |
|---|---|---|
| `GET` | `/api/ui/v1/processes/{process_key}/review` | R0; `read_only` según flag |
| `PATCH` | `.../review` | Guardado parcial; header **`If-Match`** obligatorio |
| `POST` | `.../review/preflight` | Dry-run reglas Finalize; **no** escribe Excel ni Control |

### PATCH

- Body: `{ "changes": [ { "row_key", "fields" } ] }`
- `row_key` = `{sheet}|{id_pago}|{credito}`
- Whitelist pagos: `aplicar_a_extracto`, `mora_a_aplicar`, `abono_a_capital`, `otros_valores`, `estado_pago`, `validar_pago`, `observacion`
- Whitelist abonos: `validar_abono`
- Montos con `Decimal` (2 decimales)
- Borrador incompleto permitido (no exige cuadre de negocio)
- `409 review_etag_conflict` si el Excel cambió
- `428 missing_if_match` sin `If-Match`
- `403 ui_review_edit_disabled` si flag off

### Preflight

Reutiliza `_collect_distribucion_pago_issues` / `_collect_abono_issues` (+ Errores abiertas, schema).  
Respuesta: `{ ok, issue_count, issues[], requires_regeneration }`.

## UI

Panel «Revisión del lote»: edición cuando `review_edit_allowed`, banner dirty, **Guardar cambios**, **Comprobar antes de finalizar**, mensajes 409/errores claros.

## Archivos

- `app/application/ui/review_write.py`
- `app/application/ui/review_preflight.py`
- `app/application/ui/review_read.py` (API field names en `editable_fields`)
- `app/application/ui/feature_flags.py` / `write_deps.py`
- `app/adapters/primary/http/ui/router_v1.py`
- `frontend/src/components/ReviewReadPanel.tsx`
- `tests/test_ui_review_edit_r1.py`

## Nota de routing

Las rutas `.../review` se registran **antes** de `GET .../processes/{process_key:path}` para que el convertidor `:path` no se coma el sufijo `/review`.
