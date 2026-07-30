# Implementación — Operator Web UI

**Rama:** `feature/operator-web-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-operator-web-ui`  
**Fase autorizada:** **U1 read-only** (2026-07-29)

`DECISIONES_TECNICAS_CERRADAS.md` = solo lectura. No modificar.

---

## Hotfix de cierre U1 (2026-07-29)

### Clasificación de `INCOMPLETO`

| Clasificación | **C — RETIRADO** del flujo operativo vigente |
|---|---|
| Evidencia `review_schema.EstadoPago` | No está en `ALLOWED` ni `OPTIONS_ORDERED` (solo NORMAL/ATRASADO/ADELANTADO/REVISION_MANUAL). |
| Generate | Dropdowns/validación no incluyen INCOMPLETO (`test_verify_remove_incompleto_production`). |
| Finalize | Si aparece en Excel → `INCOMPLETO_NOT_SUPPORTED` (fail-fast, sin escrituras). |
| Follow-up | `pagos_incompletos.xlsx` deprecado; setup no lo toca. |
| Allowlist del test `test_app_source_has_no_unjustified_incompleto_references` | Solo: `payment_validation_finalize.py`, `job_status_enrichment.py`, `setup_payment_followup_workbooks.py`, `operational_message_policy.py` (mensajes residuales / rechazo). |
| Lectura histórica | Un histórico viejo puede aún *contener* el texto; Notify/Merge no lo rechazan solo por eso. No es estado a emitir como canónico UI. |

**Discrepancia documental:** `DECISIONES_TECNICAS_CERRADAS.md` (§ ramificaciones) aún
enumera `INCOMPLETO` como ejemplo de diseño pre-implementación. **No se edita en
esta rama** (solo lectura). La verdad de producto en código es el retiro.
Integración / doc maestro externo deben sincronizar esa lista en un cambio
explícito fuera de `feature/operator-web-ui`.

**Solución U1:** eliminado de `schemas.py`, contrato UI v1 y mocks. La UI solo
expone canónicos de `EstadoPago` + estados operativos propios
(`ESPERANDO_*`, `COMPLETADO`, `ERROR_CORREGIBLE`, `DESCONOCIDO`).

### Fail-closed producción + mock

Si `ACTIVE_ENVIRONMENT=production` y `UI_AUTH_MODE=mock`:

1. `get_ui_feature_flags().ui_enabled` queda **False** aunque `UI_ENABLED=true`.
2. Se registra **un** `logger.critical` (fail-closed).
3. Middleware/router UI responden `404` `ui_misconfigured_fail_closed`.
4. `authenticate_mock` rechaza siempre en producción.
5. **No** se lanza excepción al importar la app; `/graph/*` y PA siguen normales.

---

## Condiciones obligatorias (aprobadas)

1. **No modificar `app_factory.py`** bajo ninguna circunstancia en esta feature.
   - Sin “gancho mínimo local”.
   - Tests: app FastAPI **aislada** en `tests/`.
   - Cableado real de routers/static → solo `integration/performance-and-ui`.

2. **Sin endpoints mutantes** en U1.
   - `UI_WRITE_ENABLED` y contratos de mutación: solo documentación.
   - POST Generate / Finalize / Notify / Merge / Dry-run / Apply → autorización posterior.

3. **`trigger_source` / `requested_by`**
   - Metadata **opcional** en DTOs UI.
   - No columnas obligatorias en Control, no `review_schema`, no bodies/responses PA, no migraciones.
   - Legacy sin esos campos = compatible.
   - Persistencia compartida futura → documentar para integración (abajo).

4. **`frontend/dist` no se versiona.**
   - Build local/CI genera `dist/`.
   - Empaquetado Azure desde rama de integración.
   - Pipeline actual (`build-azure-package.ps1`) aún no incluye SPA; anotado para integración.

5. **Notify / Merge en proyección**
   - Fuente principal: Control, histórico, manifest, artefactos persistentes.
   - Job en memoria = progreso técnico **opcional** si el `job_id` sigue vivo.
   - Nunca tomar el dict in-memory de `sharepoint.py` como verdad del proceso.

---

## Mapa exacto de archivos — Fase U1

### Crear

| Ruta | Rol |
|---|---|
| `docs/implementation/operator-web-ui.md` | Este documento |
| `docs/ui-api-contract-v1.md` | Contrato HTTP/DTOs UI v1 |
| `app/application/ui/__init__.py` | Paquete UI application |
| `app/application/ui/feature_flags.py` | `UI_ENABLED`, `UI_WRITE_ENABLED`, `UI_AUTH_MODE` |
| `app/application/ui/environment.py` | Ambiente activo desde backend |
| `app/application/ui/schemas.py` | DTOs Pydantic (read-only + stubs mutación documentados) |
| `app/application/ui/job_read.py` | Lectura opcional de jobs (JobManager + puerto Notify/Merge) |
| `app/application/ui/process_projection.py` | `PaymentProcessProjectionService` read-only |
| `app/adapters/primary/http/ui/__init__.py` | Paquete adapters UI |
| `app/adapters/primary/http/ui/auth.py` | Abstracción mock/entra (aplicable a app aislada) |
| `app/adapters/primary/http/ui/router_v1.py` | **Solo GET** `/api/ui/v1/*` |
| `app/adapters/primary/http/ui/deps.py` | Dependencias UI |
| `frontend/` | SPA React + Vite + TypeScript |
| `frontend/.gitignore` | Ignora `dist/` y `node_modules/` |
| `frontend/src/**` | Dashboard, detalle, polling, mocks |
| `tests/ui_test_app.py` | Factory FastAPI aislada para tests |
| `tests/test_ui_feature_flags.py` | Flags |
| `tests/test_ui_environment.py` | Ambiente |
| `tests/test_ui_auth.py` | Auth mock/entra aislada |
| `tests/test_ui_projection.py` | Proyección (Control-first Notify/Merge) |
| `tests/test_ui_contract_routes.py` | GET contrato + flags |
| `tests/test_ui_pa_regression_smoke.py` | Smoke: `create_app()` sin UI y sin tocar factory |

### No tocar en U1

- `app_factory.py`, `application.py`, `requirements.txt`, `startup.sh`
- `build-azure-package.ps1`, `config/environments/*.env`
- `payment_validation_generate.py`, índice, amortización financiera
- `job_manager.py` (sin cambios de comportamiento)
- `sharepoint.py` job store Notify/Merge
- Control Excel / `review_schema.py`
- Montaje real `/app`, deploy

---

## Arquitectura U1

```text
tests/ui_test_app.py ──include──► ui.router_v1 (GET)
                                 + ui.auth middleware

create_app() (producción actual) ──► SIN router UI  (cable = integración)

SPA (Vite) ──mocks──► contrato v1  (dev)
SPA (futuro) ──/api/ui/v1/*──► backend  (tras integración)
```

### Proyección

`PaymentProcessProjectionService.project(bank_code | process_key)`:

1. Lee Control (`ProcessControlSnapshot`).
2. Deriva estado por etapa desde `EstadoProceso` + paths/idempotency keys.
3. Adjunta links (paths relativos; `webUrl` si el puerto Graph lo aporta).
4. Si hay `active_job_id` conocido y el store lo tiene vivo → `active_job` técnico.
5. Notify/Merge: **no** inferir completed solo porque hubo un job en memoria.

### Auth

- `UI_AUTH_MODE=mock|entra`
- Middleware instalable vía `install_ui_auth(app)` — usado por tests, **no** por `create_app()`.
- Prohibido `api_key` para UI.

### Feature flags

| Flags | Efecto en router UI (cuando esté montado) |
|---|---|
| `UI_ENABLED=false` | Router responde 404 / no montado en integración |
| `UI_ENABLED=true`, write false | Solo GET |
| write true | Documentado; **no implementado** en U1 |

En U1 el router existe en código pero **no** se monta en `create_app()`. Los tests montan la app aislada con flags.

---

## Notas para `integration/performance-and-ui`

1. `app.include_router(ui_router)` detrás de `UI_ENABLED`.
2. Ajustar `ApiKeyAuthMiddleware` / paths públicos: `/app`, assets SPA; `/api/ui/*` → Bearer (no X-API-Key del browser).
3. `StaticFiles` → `/app` desde artefacto build (no versionar `frontend/dist`).
4. Extender `build-azure-package.ps1`: `npm ci && npm run build` + copiar `frontend/dist` al zip.
5. Persistencia opcional futura de `trigger_source`/`requested_by`: preferir job JSON en disco o bitácora execution-run-log; **no** columnas obligatorias Control en U1–U2.
6. Entra: app registration, audience, scopes, roles.

---

## Plan Fase U1.5 (actualizado — sin código aún)

Objetivo: adaptador Graph **read-only** inyectable (Control, histórico, manifest,
webUrl), testeable con fakes; **sin** montar en `create_app()`.

También candidato a absorber (si no se hizo en hotfix U1): nada pendiente de
fail-closed / INCOMPLETO tras el hotfix de cierre.

### Archivos previstos U1.5

| Ruta | Rol |
|---|---|
| `app/application/ui/ports.py` | Protocolos read-only |
| `app/adapters/secondary/ui_sharepoint_read.py` | Graph read-only |
| `app/adapters/primary/http/ui/graph_deps.py` | Wiring inyectable (tests/integración) |
| `tests/fakes/ui_sharepoint_fake.py` | Fake |
| `tests/test_ui_sharepoint_read.py` | Cobertura lectura |

### Integración sigue limitada a

`include_router` · middleware auth · StaticFiles `/app` · config · build/empaquetado ·
inyectar el adaptador ya escrito aquí.

---

## Orden de commits U1

1. `docs: contrato UI v1 + plan operator-web-ui (Fase U1)`
2. `feat(ui): flags, schemas, proyección read-only, GET /api/ui/v1`
3. `test(ui): app aislada, auth, proyección, contrato`
4. `feat(ui): SPA React+Vite con mocks del contrato v1`
5. `fix(ui): fail-closed production y alineación de estados`

---

## Rollback U1

- No hay cable en producción → rollback = no merge / revert commits de la rama.
- Tras integración: `UI_ENABLED=false`.
