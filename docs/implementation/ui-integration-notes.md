# Notas de integración — Operator Web UI

Documento de esta feature branch. **No** sincroniza `PROJECT_CONTEXT.md`
aquí: ese archivo se actualiza solo en `integration/performance-and-ui`.

## Estado por fase

| Fase | Estado | Alcance |
|---|---|---|
| U1 | Aprobada | Contrato, proyección, GET `/api/ui/v1`, SPA mocks, fail-closed |
| U1.5 | Aprobada | `UiSharePointReadPort`, path guard, caché, precedencia, legacy |
| U2+ | Pendiente | POST Generate/Finalize/Notify/Merge/Dry-run/Apply |
| Integración | Pendiente | Montaje en `create_app`, StaticFiles `/app`, Empaquetado SPA |

## Seguridad de lectura (U1.5)

- El navegador **no** envía paths ni URLs Graph. Solo `bank_code`, `process_key`, `job_id`.
- Paths SharePoint se derivan de Control / settings del overlay activo + `path_guard`.
- `UiGraphHttpReadPort` solo acepta endpoints relativos construidos en servidor.
- Caché en memoria: clave `environment|site_id|drive_id|kind|relative_path` + eTag.
  Cambio de ambiente → `clear()`. Sin tokens ni credenciales.
- Tope de descarga: `UI_SHAREPOINT_MAX_DOWNLOAD_BYTES` (default 15 MiB).
- Pytest: fakes. Smoke real: `scripts/ui_sharepoint_read_smoke.py` + flags (no pytest).

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
