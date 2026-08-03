# U4 — R3 upload de asientos desde la SPA

**Rama:** `feat/ui-in-app-review-and-asientos`  
**Alcance:** carga de PDF de asientos por `id_pago` + `credito` (+ tipo). Path y nombre **solo server-side**. Sin deploy.

## Feature flag

`UI_ASIENTOS_UPLOAD_ENABLED` — **apagado por defecto** (fail-closed).  
Requiere también `UI_ENABLED` + `UI_WRITE_ENABLED` + sandbox.  
Bootstrap expone `asientos_upload_allowed`.  
Gate: `require_asientos_upload_access` (write gate + flag).

Límite opcional: `UI_ASIENTOS_MAX_UPLOAD_BYTES` (default 10 MiB, acotado por download UI).

## Endpoint

`POST /api/ui/v1/processes/{process_key}/asientos` → **201**

Body JSON (`extra=forbid`; **sin** path SharePoint):

```json
{
  "id_pago": "…",
  "credito": "265",
  "tipo_aplicacion": "PAGO CUOTA",
  "content_base64": "<pdf base64 o data URL>",
  "source_filename": "opcional.pdf"
}
```

Cadena:

```text
Control (PENDIENTE_ASIENTOS | MERGE_PARCIAL | ERROR_MERGE)
→ histórico Validar=SI
→ RutaAsientosContables (server)
→ nombre con CRED {dígitos} aislados
→ put_bytes PDF
```

| Caso | HTTP |
|---|---|
| OK | 201 + filename / folder_path / web_url |
| Flag off | 403 `ui_asientos_upload_disabled` |
| Query `path`/`web_url` | 400 `client_path_forbidden` |
| Estado Control inválido | 409 `control_not_ready_for_asientos` |
| PDF inválido / fila / ruta | 422 |

## UI

Panel «Cargar asientos» en detalle cuando `asientos_upload_allowed` y el proceso espera soportes. Lista desde `merge_readiness.missing_items`; el operador elige PDF por fila.

## Archivos

- `app/application/ui/asientos_upload.py`
- `app/application/ui/feature_flags.py` / `write_deps.py` / `schemas.py`
- `app/adapters/primary/http/ui/router_v1.py` (ruta **antes** del catch-all `GET .../{process_key:path}`)
- `frontend/src/components/AsientosUploadPanel.tsx`
- `tests/test_ui_asientos_upload_r3.py`
