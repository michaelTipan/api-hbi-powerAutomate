# Notas de integración — Operator Web UI

## Estado por fase

| Fase | Estado | Alcance |
|---|---|---|
| U1 | Aprobada | Contrato, proyección, GET `/api/ui/v1`, SPA mocks, fail-closed |
| U1.5 | Aprobada | `UiSharePointReadPort`, path guard, caché, precedencia, legacy |
| U1.5 smoke | Aprobado | `scripts/ui_sharepoint_read_smoke.py` (+ support App Service GET) |
| U2 | En integración | Montaje `create_app`, Entra JWKS, bootstrap, SPA `/app`, empaque |
| U2+ | Pendiente | POST Generate/Finalize/Notify/Merge/Dry-run/Apply |

## Flags (overlay sandbox)

```
ACTIVE_ENVIRONMENT=sandbox
EXTRACT_INDEX_MODE=off
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false
EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED=false
UI_ENABLED=false
UI_WRITE_ENABLED=false
UI_AUTH_MODE=entra
```

Rutas canónicas sandbox intactas. No habilitar `UI_ENABLED=true` en Azure hasta
JWT Entra configurado y validado.

## Auth y bootstrap (U2)

- **API:** `UI_ENTRA_TENANT_ID`, `UI_ENTRA_ISSUER`, `UI_ENTRA_JWKS_URI`,
  `UI_ENTRA_AUDIENCE`, `UI_ENTRA_REQUIRED_ROLES` / `UI_ENTRA_REQUIRED_SCOPES`.
- **SPA (público):** `UI_ENTRA_AUTHORITY`, `UI_ENTRA_SPA_CLIENT_ID`,
  `UI_ENTRA_API_SCOPE` vía `GET /api/ui/v1/bootstrap`.
- No usar `UI_ENTRA_CLIENT_ID` ambiguo.
- Tests Entra: JWKS local (`tests/ui_entra_jwt_helpers.py`); sin red.

## Cableado

1. `include_router` UI + `install_ui_auth` cuando `UI_ENABLED`.
2. `UiSharePointReadAdapter(get_graph_client())` tipado como `UiSharePointReadPort`.
3. SPA: `app/static/operator-ui` (paquete) o `UI_STATIC_DIR`.
4. Sin acoplar estado mutable privado de payment_validation en U2.
