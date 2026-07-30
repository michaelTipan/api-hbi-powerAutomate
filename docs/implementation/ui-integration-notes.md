# Notas de integración — Operator Web UI

Documento de esta feature branch. **No** sincroniza `PROJECT_CONTEXT.md`
aquí: ese archivo se actualiza solo en `integration/performance-and-ui`.

## Estado por fase

| Fase | Estado | Alcance |
|---|---|---|
| U1 | Aprobada | Contrato, proyección, GET `/api/ui/v1`, SPA mocks, fail-closed |
| U1.5 | Aprobada | `UiSharePointReadPort`, path guard, caché, precedencia, legacy |
| U1.5 smoke | Aprobado | `scripts/ui_sharepoint_read_smoke.py` (+ support App Service GET) |
| U2+ | Pendiente | POST Generate/Finalize/Notify/Merge/Dry-run/Apply |
| Integración | Pendiente | Montaje en `create_app`, StaticFiles `/app`, Empaquetado SPA |

## Flags recomendados en despliegue UI (aún sin montar)

Hasta integrar la SPA/router en la app principal, el despliegue “normal” de la API
debe conservar:

```
EXTRACT_INDEX_MODE=off
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false
EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED=false
UI_ENABLED=false
UI_WRITE_ENABLED=false
```

## Seguridad de lectura (U1.5)

- El navegador **no** envía paths ni URLs Graph. Solo `bank_code`, `process_key`, `job_id`.
- Paths SharePoint se derivan de Control / settings del overlay activo + `path_guard`.
- `UiGraphHttpReadPort` solo acepta endpoints relativos construidos en servidor.
- Caché en memoria: clave `environment|site_id|drive_id|kind|relative_path` + eTag.
  Cambio de ambiente → `clear()`. Sin tokens ni credenciales.
- Tope de descarga: `UI_SHAREPOINT_MAX_DOWNLOAD_BYTES` (default 15 MiB).
- Pytest: fakes. Smoke real: `scripts/ui_sharepoint_read_smoke.py` + flags (no pytest).

## Smoke App Service (herramienta, no producto)

- `scripts/support/ui_appservice_graph_http.py` es **exclusivo de smoke**.
- Requiere `UI_SHAREPOINT_SMOKE=1`. Solo GET. No se registra en `app_factory.py`.
- No debe importarse desde módulos bajo `app/`.
- Las métricas del smoke (latencias, cache hits, conteo GET) son del **proxy App Service**
  (X-API-Key → `/graph/*` ya desplegado) y **no** representan el rendimiento final de la
  UI integrada con `UiSharePointReadAdapter` + Graph directo en el mismo proceso.

## Auditoría rutas legacy en Control (read-only, 2026-07-29)

Controles observados en smoke sandbox:

| Banco | process_key (fecha) | Árbol en paths de artefactos |
|---|---|---|
| banco_bogota | `…\|2026-07-29\|a3acb59c-…` | `02 COMWARE AUTOMATIZACION - …` (legacy) |
| banco_bancolombia | `…\|2026-07-29\|d2763d59-…` | `02 COMWARE AUTOMATIZACION - …` (legacy) |

- Overlay / Control técnico actuales: bajo `03 COMWARE PRUEBAS- …` (canónico sandbox).
- Clasificación: **legacy persistido** en columnas Validation/Historical/Email/Manifest
  de procesos del mismo día del rename; no se reescriben Excel desde esta rama.
- Productor actual: Generate/Finalize/Merge construyen paths con
  `PAYMENT_VALIDATION_BASE_FOLDER` / `get_payment_validation_paths()` /
  `resolve_logs_folder_path()` → overlay activo (`03 COMWARE PRUEBAS`).
  **No** se observó hardcode de `02 COMWARE AUTOMATIZACION` en el productor.
- UI: proyección emite `errors[]` con `error_code=legacy_sandbox_path`
  (severity=warning) sin romper el detalle.

## Cableado previsto (sin ejecutar en esta rama)

1. `include_router` del UI + middleware auth (Entra) en fábrica de app.
2. Inyectar `UiSharePointReadAdapter` tipado **solo** como `UiSharePointReadPort`
   (nunca `GraphApiPort` mutante visible a la proyección).
3. `StaticFiles` en `/app` con `frontend/dist`.
4. Incluir SPA en `build-azure-package` (cambio de empaquetado en integración).
5. Sincronizar `PROJECT_CONTEXT.md` y `DECISIONES_TECNICAS_CERRADAS.md` (estado
   retirado) en la rama de integración — **no** en `feature/operator-web-ui`.

## Archivos reservados (intactos en esta feature)

`application.py`, `app_factory.py`, `requirements.txt`, `startup.sh`,
`build-azure-package.ps1`, `config/environments/*`, `DECISIONES_TECNICAS_CERRADAS.md`,
`PROJECT_CONTEXT.md`.
