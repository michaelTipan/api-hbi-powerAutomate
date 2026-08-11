# Plan U3-A — Seguridad de escritura UI + Generate desde la UI (sandbox)

> **Nota v3 (2026-08):** extract-index eliminado del runtime (sin EXTRACT_INDEX_* ni /extract-index/admin). Workbook operador = Aplicacion_Pagos / _Meta (no Distribucion_* / Casos_Pago). Este plan es histórico de la fase UI.


**Fecha:** 2026-07-30  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Estado:** IMPLEMENTADO en Git local (sin deploy). Ver `docs/implementation/u3a-generate-from-ui.md`.  
**Precondición:** D2-LS2 aceptada (login confirmado en `/app/`)

---

## 0. Cierre D2-LS2 (estado al momento del plan)

| Ítem | Estado |
|------|--------|
| HEAD | `4e03951` — `docs: alinear Auth UI a local_session y registrar suite 1086` |
| Branch | `integration/performance-and-ui` (sin tracking remoto en este informe) |
| Fix mocks en Git | **NO** — cambios sin commit en working tree |
| Archivos del fix | `frontend/src/api/client.ts` (opt-in `=== "true"`), `scripts/build-azure-package.ps1` (`VITE_UI_USE_MOCKS=false`) |
| Desplegado | Sí — SPA `index-DBYWZoDn.js` con `/api/ui/v1/bootstrap` real |
| ZIP rollback D2-LS2 | Conservar `D:\CMC\HBI_Capital\azure-deploy-d2-ls2.zip` y `azure-deploy-d2-ls2-fix-mocks.zip` |
| Portapapeles | **Limpiado** tras confirmación de login (sin mostrar contraseña) |
| Migración control→lista | **Aplazada** — Excel `control_proceso_*` sigue siendo fuente oficial |

**Acción pendiente al autorizar (commit 1, no U3-A feature):**

1. Commit aislado del fix mocks.  
2. Test que falle si el build Azure no fuerza `VITE_UI_USE_MOCKS=false` / si el bundle no contiene `/api/ui/v1/bootstrap`.  
3. Confirmar en ZIP post-build: sin `auth_mode:"mock"` hardcodeado como bootstrap efectivo.

---

## 1. HEAD y git status (entrega)

```
HEAD: 4e03951 docs: alinear Auth UI a local_session y registrar suite 1086
M  frontend/src/api/client.ts
M  scripts/build-azure-package.ps1
?? docs/plans/
```

Sin push. Sin merge a `develop`.

---

## 2. Corrección de mocks en Git

**Confirmación:** la corrección **está en disco y en Azure**, pero **aún no en un commit**.

Será el commit propuesto:

`fix(ui): cerrar mocks fail-closed para build Azure`

---

## 3. Archivos que se modificarán (U3-A + cierre mocks)

### Cierre mocks (commit 1)

- `frontend/src/api/client.ts`
- `scripts/build-azure-package.ps1`
- `tests/` — nuevo test de empaquetado / guardrail mocks (p. ej. parse del script o build fixture)

### Auth / CSRF / write gate (commit 2)

- `app/application/ui/local_auth.py` — exponer CSRF de sesión; validación Origin vía `UI_ALLOWED_ORIGINS`
- `app/application/ui/session_repository.py` — ya tiene `csrf_token` / `mint_csrf_token` (reutilizar)
- `app/application/ui/local_session_config.py` / feature flags — `UI_ALLOWED_ORIGINS`, gates write
- `app/adapters/primary/http/ui/router_v1.py` — `GET /auth/csrf`; deps CSRF en POST
- `app/adapters/primary/http/ui/deps.py` o nuevo `write_deps.py` — sesión + CSRF + Origin + Content-Type + `UI_WRITE_ENABLED` + sandbox
- `app/application/ui/schemas.py` — `UiCsrfResponse`, request Generate, `available_actions`

### Generate UI API (commit 3)

- `app/adapters/primary/http/ui/router_v1.py` — `POST /api/ui/v1/processes/generate`
- Nuevo módulo fino p. ej. `app/application/ui/generate_action.py` — orquesta cola sin HTTP a `/graph`
- **Reutiliza** (no copia lógica):  
  - `generate_payment_validation` en `app/application/use_cases/payment_validation_generate.py`  
  - patrón de cola de `queue_generate` / `_run_generate_job` en `app/adapters/primary/http/routers/payment_validation.py`  
  - `JobManager.try_start_generate` / `finish_generate` / `set_job`  
  - `GraphClientDep` / reader ya montado en UI  
  - control Excel vía `payment_validation_process_control.py` (sin listas)
- `app/application/ui/process_projection.py` — `available_actions.generate`
- `app/application/ui/job_read.py` — reutilizar GET job UI si existe; ampliar solo si hace falta

### Frontend (commit 4)

- `frontend/src/pages/DashboardPage.tsx` (o shell) — botones Generate Bogotá/Bancolombia
- `frontend/src/api/client.ts` — CSRF en memoria, POST Generate, poll job
- `frontend/src/components/*` — modal confirmación, progreso
- `frontend/src/types/contract.ts` — tipos `available_actions`, generate response
- `frontend/src/styles.css` — mínimo necesario

### Tests (commit 5)

- `tests/test_ui_csrf_write_gate.py` (nuevo)
- `tests/test_ui_generate_action.py` (nuevo)
- Extender `tests/test_ui_local_session.py` / proyección
- Guardrail mocks Azure (si no quedó en commit 1)

### Docs (commit 6)

- `docs/implementation/operator-web-ui.md` o `docs/plans/u3a-generate-from-ui.md` (este archivo)
- `PROJECT_CONTEXT.md` — U3-A + control-lista aplazada
- Marcar `docs/plans/process-control-sharepoint-list.md` sigue PAUSADO

### Runtime (no Git)

- `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env` — `UI_ALLOWED_ORIGINS=...`; `UI_WRITE_ENABLED=false` en paso 1, `true` solo en paso 2 sandbox

### Explicitamente NO tocar

- Rutas `/graph/*`, bodies/respuestas PA, `API_HTTP_KEY`
- Excel `control_proceso_*` (sin columnas nuevas obligatorias)
- process-control-list / dual-write / seed
- Finalize / Notify / Merge / Dry-run / Apply UI
- Extract-index flags (siguen off/false)

---

## 4. Endpoint exacto propuesto

```http
POST /api/ui/v1/processes/generate
Content-Type: application/json
Origin: https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net
Cookie: __Host-hbi_session=...
X-CSRF-Token: <token>

{ "bank_code": "banco_bogota" | "banco_bancolombia" }
```

```http
GET /api/ui/v1/auth/csrf
→ { "csrf_token": "..." }
```

Respuesta Generate (UI, distinta de `/graph`):

```http
HTTP 202
{
  "accepted": true,
  "action": "generate",
  "bank_code": "banco_bogota",
  "job_id": "...",
  "process_key": "...",   // si ya conocido / best-effort
  "status": "queued",
  "poll_url": "/api/ui/v1/jobs/{job_id}"
}
```

Errores de negocio (lock, already_generated, review_folder_not_empty, etc.): status HTTP alineado al contrato UI (409/422/4xx) con `error_code`, `user_message`, `next_action`, `severity`, `retryable` — **sin** inventar nueva idempotency key en React.

También:

```http
GET /api/ui/v1/jobs/{job_id}   # read-only, JobManager existente (reutilizar/adaptar)
```

---

## 5. Caso de uso existente reutilizado

| Capa | Símbolo | Archivo |
|------|---------|---------|
| Use case | `generate_payment_validation(...)` | `app/application/use_cases/payment_validation_generate.py` |
| Referencia de cola PA | `queue_generate` → `_run_generate_job` | `app/adapters/primary/http/routers/payment_validation.py` |

La UI **no** hace HTTP a `/graph/sharepoint/payment-validation/generate/queue`.  
Extrae la orquestación de encolado a un helper compartido (idealmente) o duplica **solo** el cableado JobManager+background task llamando al **mismo** `generate_payment_validation`, sin pasar por el router Graph.

---

## 6. JobManager y locks reutilizados

| Mecanismo | API | Archivo |
|-----------|-----|---------|
| Singleton jobs | `JobManager()` | `app/application/job_manager.py` |
| Lock Generate/Finalize | `try_start_generate()` / `finish_generate()` | mismo |
| Persistencia | disco `.payment_validation_jobs` (ya existente) | mismo |
| Idempotencia negocio | `GenerateIdempotencyKey` / control Excel / lógica en use case | `payment_validation_generate.py` + control Excel |
| Credit locks extract-index | sin cambios; Generate sigue con su prioridad lógica | `domain/ports/credit_lock.py` |

**No** crear store de jobs paralelo para UI.

---

## 7. Diseño CSRF

1. Login (`POST /auth/login`) ya crea `SessionRecord.csrf_token` vía `mint_csrf_token()`.
2. `GET /api/ui/v1/auth/csrf` (sesión requerida) devuelve ese token (o lo renueva si se decide; **mínimo:** devolver el de la sesión; rotar en login).
3. Logout / expiry → sesión borrada → CSRF inválido.
4. SPA: token **solo en memoria** (variable módulo / state React). Nunca `localStorage` / `sessionStorage`.
5. Todo POST UI: header `X-CSRF-Token` + `hmac.compare_digest` contra el de la sesión.
6. También: cookie sesión válida, `role=operator`, `Origin` ∈ `UI_ALLOWED_ORIGINS` (exact match), `Content-Type: application/json`, `UI_WRITE_ENABLED=true`, `ACTIVE_ENVIRONMENT=sandbox` en U3-A.
7. Azure: **rechazar POST sin Origin**.
8. `UI_ALLOWED_ORIGINS=https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net`  
   Sin CORS amplio.

---

## 8. Diseño `available_actions`

Backend authority en proyección (detalle y/o list summary + bootstrap/environment si aplica):

```json
"available_actions": {
  "generate": {
    "allowed": true,
    "reason": null
  }
}
```

o

```json
"generate": {
  "allowed": false,
  "reason": "Existe un proceso generate o finalize activo…"
}
```

Reglas sugeridas (todas server-side):

- `UI_WRITE_ENABLED` y sandbox y `local_session` y rol operator.
- No hay lock Generate/Finalize activo (`JobManager`).
- Estado de control / carpeta revisión: si el use case ya sabe que fallaría de inmediato, reflejar `allowed:false` cuando sea barato; si es caro, permitir botón y dejar que el POST devuelva el error real (API sigue siendo autoridad final).

Frontend: botón “Iniciar validación” **solo** si `available_actions.generate.allowed === true`.  
No Finalize/Notify/Merge/Dry-run/Apply.

---

## 9. Estrategia PA/UI anti-duplicado

Misma puerta que PA:

1. `JobManager.try_start_generate()` — un solo Generate/Finalize global a la vez.  
2. Idempotencia / `already_generated` / review folder checks **dentro** de `generate_payment_validation`.  
3. UI doble clic: botón disabled + un solo POST; segundo POST → 409 lock o reused.  
4. PA activo + UI → UI recibe 409 / mensaje existente.  
5. UI activa + PA → PA recibe el mismo 409 de `try_start_generate`.  
6. Auditoría aditiva best-effort: `trigger_source=web_ui`, `requested_by=<username>`, `ui_request_id=<uuid>` en log/job metadata — **sin** columnas obligatorias nuevas en Excel control; fallo de audit no rompe negocio.

No coordinador paralelo exclusivo UI.

---

## 10. Tests (obligatorios — mapa)

### Auth / CSRF

1. POST sin sesión → 401  
2. POST con X-API-Key sin sesión → 401  
3. Sesión sin CSRF → 403  
4. CSRF incorrecto → 403  
5. Origin incorrecto → 403  
6. Sesión + CSRF + Origin OK + write + sandbox → permitido  
7. Logout invalida CSRF  
8. Sesión expirada invalida CSRF  
9. `UI_WRITE_ENABLED=false` → Generate rechazado  
10. `ACTIVE_ENVIRONMENT=production` → U3-A rechazado aunque write=true  

### Generate

11–12. Bogotá / Bancolombia vía use case compartido  
13. Spy: **cero** HTTP interno a `/graph`  
14. No usa `API_HTTP_KEY`  
15–17. Mismo Graph client wiring / JobManager / locks  
18. Doble clic → un job  
19–20. PA↔UI cruzado sin duplicar  
21–22. `already_generated` / `review_folder_not_empty`  
23. Job completed refresca proyección  
24. Fallo con `user_message` + `next_action`  

### Regresión

25–28. `/graph/*` X-API-Key; cookie/CSRF no autentican graph; contratos PA  
29. Excel control = fuente oficial  
30. Cero writes a `CONTROL_PROCESOS_VALIDACION`  
31–34. Mocks off en Azure build; suite; npm build; ZIP SPA real  
35. UI read-only previa OK  

---

## 11. Commits propuestos

1. `fix(ui): cerrar mocks fail-closed para build Azure` (+ test guardrail)  
2. `feat(ui-auth): agregar CSRF y gate de escrituras`  
3. `feat(ui-api): exponer Generate mediante caso de uso compartido`  
4. `feat(ui): agregar acción Generate y polling`  
5. `test(ui): cubrir CSRF, idempotencia cruzada y regresión PA`  
6. `docs: documentar U3-A y mantener migración de control aplazada`  

No squash único. No push. No merge a `develop`.

---

## 12. Deploy en dos pasos

### Paso 1 — Código con writes OFF

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=false
UI_AUTH_MODE=local_session
UI_ALLOWED_ORIGINS=https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net
# EXTRACT_INDEX eliminado
```

Build → Kudu VFS → restart → `/health` → login → UI read-only → PA `/graph/*` →  
`POST .../processes/generate` **rechazado** → **cero mutaciones**.

### Paso 2 — Activación sandbox

Solo si Paso 1 OK: `UI_WRITE_ENABLED=true` → rebuild/redeploy/restart según práctica actual.

Smoke Generate controlado:

- Un banco (preferir **Bogotá** si no hay proceso activo)
- Excel banco de prueba
- Carpeta `01 REVISION` vacía
- Sin flujo productivo paralelo
- Confirmar sandbox

Luego: job, Excel revisión, control Excel, UI, segundo clic idempotente, PA intacto.

**No** Finalize/Notify/Merge/Dry-run/Apply desde UI.

---

## 13. Rollback

Inmediato si: `/graph` roto, contrato PA cambia, SPA envía API key, CSRF omitible, Origin malo aceptado, doble proceso/Excel, escritura prod, índice on, lista control, botón no autorizado, mocks de vuelta, auth rota.

Pasos:

1. `UI_WRITE_ENABLED=false` + restart  
2. Confirmar UI read-only + PA  
3. Si no basta → redeploy `azure-deploy-d2-ls2.zip` / `azure-deploy-d2-ls2-fix-mocks.zip`  
4. Documentar causa  
5. No continuar a U3-B  

---

## 14. Excel de control intactos

Confirmado en alcance:

- Siguen como **única fuente oficial** de estado de proceso.  
- Sin migración a `CONTROL_PROCESOS_VALIDACION`.  
- Sin dual-write, seed, repo lista, unlock endpoint, columnas obligatorias nuevas.  
- `MergeManifestPath` y paths siguen resolviéndose como hoy.  
- Plan aplazado: `docs/plans/process-control-sharepoint-list.md` (PAUSADO).

---

## 15. Confirmación de espera

| Acción | Estado |
|--------|--------|
| Código U3-A | **0** — no iniciado |
| Push | **0** |
| Deploy U3-A | **0** |
| Merge `develop` | **0** |
| Portapapeles | limpiado |
| Siguiente paso | **Esperar autorización explícita** para: (a) commit mocks + test, (b) implementar U3-A según este plan |

---

## Frontend U3-A (resumen UX)

- Botones “Iniciar validación” Bogotá / Bancolombia (si `available_actions.generate.allowed`)
- Modal confirmación + label permanente **SANDBOX / PRUEBAS**
- Advertencia: se leerá el Excel de carga del banco
- Disabled + anti doble clic mientras request/job activo
- Mostrar `job_id`, progreso, completed/failed, `user_message`, `next_action`
- Enlace al Excel de revisión cuando exista `web_url` / path proyectado
- Polling vía JobManager persistente (sobrevive reload)

---

## Flags durante implementación / primer deploy código

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=false          # hasta Paso 2
UI_AUTH_MODE=local_session
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
```
