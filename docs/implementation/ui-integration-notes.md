# Notas de integración — Operator Web UI

## Estado por fase

| Fase | Estado | Alcance |
|---|---|---|
| U1 | Aprobada | Contrato, proyección, GET `/api/ui/v1`, SPA mocks, fail-closed |
| U1.5 | Aprobada | `UiSharePointReadPort`, path guard, caché, precedencia |
| U1.5 smoke | Aprobado | `scripts/ui_sharepoint_read_smoke.py` (+ support App Service GET) |
| U2+ | Operativo | SPA `/app`, auth `local_session`, Generate/Finalize/Notify/Merge/Amort |
| Review schema | **v3** | Hoja `Aplicacion_Pagos` (+ `_Meta`); sin `Distribucion_*` / `Casos_Pago` |

## Flags (overlay `*-ui-enabled`)

```
ACTIVE_ENVIRONMENT=sandbox|production
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true
UI_MERGE_ENABLED=true
UI_AMORTIZATION_ENABLED=true
UI_HISTORY_ENABLED=false
UI_AUTH_MODE=local_session
```

Extract-index **no existe** en overlays ni en runtime (sin `EXTRACT_INDEX_*`).
Rutas: sandbox = PRUEBAS; production-ui-enabled = clientes reales + Contabilidad.

## Auth y bootstrap

- Sandbox/prod UI: `UI_AUTH_MODE=local_session` (cookies + CSRF).
- Bootstrap: `GET /api/ui/v1/bootstrap` expone `write`/finalize/notify/merge/amortization
  `allowed` vía `ui_write_environment_allowed` + flags `UI_*_ENABLED` (no AND-gate
  `environment == sandbox`).

## Cableado

1. `include_router` UI + auth cuando `UI_ENABLED`.
2. `UiSharePointReadAdapter(get_graph_client())` tipado como `UiSharePointReadPort`.
3. Jobs PA y UI comparten colas Generate/Finalize/Notify/Merge/Amort.
