# Plan U3-B — Finalize desde la UI (sandbox)

> **Nota v3 (2026-08):** extract-index eliminado del runtime (sin EXTRACT_INDEX_* ni /extract-index/admin). Workbook operador = Aplicacion_Pagos / _Meta (no Distribucion_* / Casos_Pago). Este plan es histórico de la fase UI.


**Fecha:** 2026-07-30  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD base:** `4e10c3939372b661d1ad1b7e04f5137fc37e0001`  
**Estado:** PLAN ONLY — sin código, sin deploy, sin modificar Excel, sin push/merge.  
**Precondición:** U3-A aprobado (Generate UI en sandbox con `UI_WRITE_ENABLED=true`).

---

## 0. Cierre documental U3-A (después de autorizar, no en esta entrega)

Tras aprobación del plan U3-B (o en commit documental aislado), actualizar:

| Artefacto | Contenido a reflejar |
|-----------|----------------------|
| `PROJECT_CONTEXT.md` | U3-A cerrado; Generate UI operativo en sandbox; `UI_WRITE_ENABLED=true`; job real `d6283042…` + reintento idempotente; U3-B planificado / deshabilitado |
| `docs/implementation/u3a-generate-from-ui.md` | Smoke Paso 1/2; SHA ZIPs; evidencia locks/idempotencia |
| Suite vigente | Contador pytest actual + tests U3-A de seguridad/locks/PA |
| Flags | `UI_FINALIZE_ENABLED` aún no existe; Finalize UI no expuesto |

**No hacer ese commit durante la entrega de este plan.**

### Estado runtime a conservar

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_AUTH_MODE=local_session
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# Contabilidad desactivada
# Generate permanece operativo en todo U3-B
```

### Proceso candidato (solo lectura hasta smoke futuro)

| Campo | Valor |
|-------|--------|
| Banco | `banco_bogota` |
| ProcessKey | `payment-validation\|banco_bogota\|2026-07-30\|bb40fcea-358a-424e-8270-18497db2253e` |
| Excel revisión | `validacion_pagos_banco_bogota_2026-07-30_bb40fcea-358a-424e-8270-18497db2253e.xlsx` |
| Control | `REVISION_CREADA`, `IsActive=true`, Generate completed, Review in_progress |

---

## 1. HEAD y status (entrega del plan)

```text
HEAD:   4e10c3939372b661d1ad1b7e04f5137fc37e0001
BRANCH: integration/performance-and-ui
STATUS: limpio al inicio de la auditoría
```

Este plan añade `docs/plans/u3b-finalize-from-ui.md` (sin commit obligatorio en esta fase).

---

## 2. Auditoría del Finalize actual (código verificado)

### 2.1 Endpoint Power Automate

| Ítem | Evidencia |
|------|-----------|
| Path | `POST /graph/sharepoint/payment-validation/finalize/queue` |
| Router | `app/adapters/primary/http/routers/payment_validation.py` (`prefix=/graph/sharepoint/payment-validation`, `@router.post("/finalize/queue", status_code=202)`) |
| Handler | `queue_finalize` |

### 2.2 Request model PA

```python
class FinalizeRequest(BaseModel):
    validation_file: str | None = None
    validation_file_path: str | None = None
    process_date: str | None = None
    bank_code: str | None = None
```

- Body opcional (`body or FinalizeRequest()`); `{}` aceptado.
- `process_date` default: `today_colombia_iso()`.
- Overrides de path permiten saltar el gate `REVISION_CREADA` del control (PA legacy).

### 2.3 Campos que recibe PA

`validation_file`, `validation_file_path`, `process_date`, `bank_code` — todos opcionales.

### 2.4–2.5 Cola y background runner

| Pieza | Ubicación |
|-------|-----------|
| Cola | `queue_finalize` — lock → uuid → `set_job(type=finalize, queued)` → `BackgroundTasks.add_task(_run_finalize_job)` |
| Runner | `_run_finalize_job` (mismo archivo) |
| Respuesta 202 | `{"job_id": "...", "status": "queued"}` |

**No existe `FinalizeQueueService` hoy** (Generate sí tiene `GenerateQueueService`).

### 2.6 Use case

`finalize_payment_validation` en  
`app/application/use_cases/payment_validation_finalize.py` (~L1775+).

### 2.7 JobManager

Singleton `JobManager` / `get_job_manager()` (`app/application/job_manager.py`).  
El router Finalize usa `JobManager()` directo (= misma instancia).

### 2.8 Locks

```text
try_start_generate / finish_generate
try_start_finalize / finish_finalize
```

Mutex mutuo: Generate activo bloquea Finalize y viceversa (`_generate_active` / `_finalize_active`).  
Locks **en memoria** (se pierden en recycle).

### 2.9 Persistencia

`{PAYMENT_VALIDATION_JOBS_DIR|wwwroot/.payment_validation_jobs}/{job_id}.json` — write atómico.

### 2.10 Polling

| Consumidor | Endpoint |
|------------|----------|
| PA | `GET /graph/sharepoint/payment-validation/jobs/{job_id}` |
| UI | `GET /api/ui/v1/jobs/{job_id}` (ya existe; enricher compartido) |

### 2.11 Estados para iniciar / reintentar

**Sin override de path (flujo control):**

- `EstadoProceso == REVISION_CREADA`
- `IsActive == true`
- `ValidationFilePath` no vacío

**Idempotente (ya finalizado):**

- mismo `ProcessKey`
- `EstadoProceso == FINALIZADO`
- `HistoricalFilePath` y `SecretaryFilePath` presentes  
→ `already_finalized=True`, sin mutaciones SharePoint

**Review workbook (hoja Control):**

- `Procesar == SI`
- `Estado == EN_REVISION`

### 2.12 Idempotency key

`FinalizeIdempotencyKey = process_key` (escrito en control al éxito).

### 2.13 Control Excel — lectura / escritura

**Lee (process control):** `EstadoProceso`, `IsActive`, `ProcessKey`, `ProcessId`, `ValidationFilePath`, `HistoricalFilePath`, `SecretaryFilePath`, banco, etc.

**Escribe al éxito:** `FINALIZADO`, paths hist/sec, `FinalizeIdempotencyKey`, `FinalizeJobId`, `LastCompletedStep=FINALIZE`, etc.  
**No** limpia `ValidationFilePath`.

**Review Excel:** solo lectura (`get_bytes`); **no se mueve ni elimina**.

### 2.14–2.15 Efectos secundarios confirmados

| Efecto | ¿Ocurre? | Nota |
|--------|----------|------|
| Histórico `cartera_validada_…xlsx` | Sí | upload nuevo |
| Soporte secretaría `soporte_asientos_contables_…xlsx` | Sí | hoja `Asientos_Pendientes` |
| Update process control → `FINALIZADO` | Sí | |
| Carpetas `ASIENTOS CONTABLES CRED {n}` / `EXTRACTOS` | Sí | ensure bajo unidad crédito |
| Enriquecimiento filas histórico (Ruta, etc.) | Sí | en copia histórica |
| `pagos_adelantados` (Pendientes) | Sí | followups post-finalize |
| Excel de revisión | **Conservado** | sin delete/move |
| Contabilidad Graph site | No (sandbox hostname vacío) | |
| Notify / email | **No** | etapa separada |
| Merge / Dry-run / Apply | **No** | |
| Listas `CONTROL_PROCESOS_VALIDACION` | **No** | |

### 2.16 Recycle

Jobs `queued`/`running` en disco → `failed` (`JobInterruptedByProcessRestart`). Locks resetean. Jobs `completed` permanecen pollables.

### 2.17 HTTP + terminal

- Aceptación: **202** `{job_id, status: queued}`
- Terminal: `completed` + `result` use-case, o `failed` + `error{type,message}` + enricher (`user_message`, `next_action`, `severity`, `error_code`)

### 2.18 Mensajes / códigos

Mapa `_FINALIZE_MESSAGES` en `job_status_enrichment.py` (p. ej. `process_not_approved`, `invalid_control_state`, `review_has_open_errors`, `estado_pago_no_finalizable`, `amount_mismatch`, `control_not_ready_for_finalize`, …).

### 2.19 Reintento tras Finalize exitoso

Nuevo `job_id` técnico; use case short-circuit `already_finalized=True`; **no** re-sube hist/sec; **no** reescribe control.

### 2.20 Si Notify falla después de Finalize

`record_notify_failure_on_control` **mantiene** `EstadoProceso=FINALIZADO`.  
Retry Notify permitido; retry Finalize → idempotente (sin re-ejecutar side effects).  
**UI no debe ofrecer “repetir Finalize”** cuando control está `FINALIZADO` con paths hist/sec.

### Hallazgo crítico (riesgo preexistente PA)

`_run_finalize_job` llama `infer_terminal_status_from_result` **sin importarlo**  
(`payment_validation.py` L121; mismo patrón dry-run/apply L194/L333).  
`GenerateQueueService` sí lo importa correctamente.

**Acción en implementación U3-B:** al extraer `FinalizeQueueService`, importar y usar el helper como Generate (arreglo indispensable del runner compartido, no hotfix en caliente fuera de U3-B).  
Documentar riesgo: en éxito, un `NameError` en el hook de execution-log podría marcar el job `failed` **después** de mutaciones SharePoint.

---

## 3. Matriz Etapa | store | POST | poll | JobManager | lock | persistencia | idempotencia | side effects

| Etapa | store | POST | poll | JobManager | lock | persistencia | idempotencia | side effects |
|-------|-------|------|------|------------|------|--------------|--------------|--------------|
| **Generate** | JobManager disk | PA `/generate/queue` + UI `/api/ui/v1/processes/generate` | PA + UI `/jobs/{id}` | singleton | `try_start_generate` (mutex c/ Finalize) | `.payment_validation_jobs` | ProcessKey / already_generated | review Excel + control `REVISION_CREADA` |
| **Finalize** | JobManager disk | PA `/finalize/queue` **solo** (UI futuro) | PA + UI `/jobs/{id}` | singleton | `try_start_finalize` (mutex c/ Generate) | mismo dir | ProcessKey + FINALIZADO + hist/sec paths | hist + sec + control FINALIZADO + folders + followups; **review kept** |
| **Notify** | store propio (no JobManager) | `/notify/…` | jobs notify | no | distinto | distinto | NotifyIdempotencyKey | mail / control NOTIFY |
| **Merge** | propio | `/merge/…` | jobs merge | no | distinto | distinto | MergeIdempotencyKey | consolidado |
| **Dry-run / Apply** | JobManager (amort) | dry-run/apply queue | jobs | singleton | flags amort propios | mismo dir | Apply keys | amort tables |

---

## 4. Request / response PA actuales

**Request:** ver §2.2 (campos opcionales).  
**Response 202:** `{"job_id","status":"queued"}`.  
**Poll:** job enrichido; éxito incluye paths hist/sec, counters, `already_finalized`, `finalize_idempotency_key`.

Contrato PA debe permanecer **idéntico** tras `FinalizeQueueService`.

---

## 5. Use case y side effects

Ver §2.6 y §2.14–2.15. Fuente única: `finalize_payment_validation`.  
UI y PA deben llamarla **solo** vía `FinalizeQueueService` (sin HTTP interno a `/graph`).

---

## 6. Diseño `FinalizeQueueService`

Espejo de `GenerateQueueService`:

```text
app/application/services/finalize_queue_service.py
  FinalizeQueueBusyError
  FinalizeQueueValidationError
  FinalizeQueueAccepted { job_id, bank_code, process_key, status }
  FinalizeQueueService.enqueue(...)
  get_finalize_queue_service()
```

**Reutilizar exactamente:**

- `get_job_manager()` / `try_start_finalize` / `finish_finalize`
- `set_job` + persistencia actual
- `background_tasks` + runner interno (con import correcto de `infer_terminal_status_from_result`)
- `finalize_payment_validation`
- `try_record_step_event` (+ bootstrap/heartbeat solo si se alinea con Generate sin cambiar semántica PA)
- enricher existente en poll

**Adapters:**

| Entrada | Adaptación |
|---------|------------|
| PA `queue_finalize` | body opcional → service (mismo HTTP out) |
| UI `POST …/finalize` | sesión + CSRF + flags → service con `validation_file_path` resuelto desde control |

**Prohibido:** duplicar cableado; importar privados del router; HTTP loopback a `/graph`.

---

## 7. Endpoint UI final (contrato viable)

```http
POST /api/ui/v1/processes/finalize
Content-Type: application/json
Origin: <UI_ALLOWED_ORIGINS>
X-CSRF-Token: <csrf>
Cookie: __Host-hbi_session
```

```json
{
  "bank_code": "banco_bogota",
  "process_key": "payment-validation|banco_bogota|2026-07-30|…"
}
```

**Viabilidad:** sí, con el código actual.

1. Cargar snapshot control del `bank_code`.
2. Exigir `snap.process_key == body.process_key` (mismatch → **409**).
3. Exigir estado compatible (`REVISION_CREADA` + active + `ValidationFilePath`) o dejar que el use case falle de forma terminal si se prefiere un solo camino (recomendación: precheck barato síncrono + use case definitivo).
4. Llamar service con `validation_file_path=snap.validation_file_path`, `bank_code`, `process_date` desde control (no del browser).
5. **No** aceptar del browser: paths, force, API key, idempotency key, process_date arbitraria.

**ProcessKey en URL:** el POST usa body JSON (evita encoding de `|`). El detalle GET existente ya usa `quote(process_key)` — no cambiar a path segment para Finalize.

**202 conceptual:**

```json
{
  "accepted": true,
  "action": "finalize",
  "bank_code": "banco_bogota",
  "process_key": "…",
  "job_id": "…",
  "status": "queued",
  "poll_url": "/api/ui/v1/jobs/{job_id}"
}
```

Errores síncronos: 401 / 403 / 409 / 422 según autorización.  
Errores de Excel/negocio: terminal del job (salvo prechecks puros compartidos).

---

## 8. Flag `UI_FINALIZE_ENABLED`

| Propiedad | Valor |
|-----------|--------|
| Default | `false` |
| Fail-closed | sí |
| Deploy Paso 1 U3-B | `false` (código presente; Finalize 403) |
| Deploy Paso 2 U3-B | `true` solo tras aprobar Paso 1 |
| Alcance | **solo Finalize** |

Gate Finalize (todas simultáneas):

```text
UI_ENABLED
UI_WRITE_ENABLED
UI_FINALIZE_ENABLED
ACTIVE_ENVIRONMENT=sandbox
sesión + role=operator
Origin + CSRF
```

Con `UI_WRITE_ENABLED=true` y `UI_FINALIZE_ENABLED=false`:

- Generate **sigue** permitido
- Finalize UI → **403**
- `available_actions.finalize.allowed=false`

**No** reutilizar solo el gate global de write (activaría Finalize al desplegar código).

---

## 9. `available_actions.finalize`

Extender proyección (detalle de proceso; opcionalmente banks si aplica):

Evaluar (puro, **sin** adquirir locks):

- flags write + finalize + sandbox
- proceso activo / ProcessKey
- `EstadoProceso` compatible (`REVISION_CREADA`)
- `ValidationFilePath` presente
- `is_generate_or_finalize_active()` lectura → si true, `allowed=false` con reason

Frontend **nunca** decide solo. POST **siempre** revalida.

---

## 10. Estrategia de readiness — **Opción B**

Las validaciones de review están **mezcladas** con mutaciones dentro de `finalize_payment_validation` (no hay validador puro extraíble sin refactor grande).

| Capa | Qué valida |
|------|------------|
| `available_actions` + UI checklist | condiciones baratas (flags, estado control, path, lock lectura) |
| Job Finalize | validación definitiva (Procesar, Errores, Distribución, montos, abonos, Graph) |

**Prohibido** copiar `review_schema` al frontend.  
UI v1: “Abrir Excel”, instrucciones, “Actualizar estado”, preparado/no preparado (desde actions), sin edición del Excel.

---

## 11. Checklist exacto del operador (schema actual)

Antes del smoke Finalize, en el Excel de revisión:

### Hoja `Control`

1. `Procesar` = **`SI`** (no `NO`).
2. `Estado` = **`EN_REVISION`**.
3. `ReviewSchemaVersion` = **2** (si v1 → `review_schema_version_1_requires_regenerate`).

### Hoja `Errores`

4. **Sin filas abiertas** (`review_has_open_errors`).

### Hoja `Distribucion_Pagos` (cada fila con datos)

5. `Estado Pago` ∈ `{NORMAL, ATRASADO, ADELANTADO, REVISION_MANUAL}` — lista desplegable.  
   - `REVISION_MANUAL` **bloquea** Finalize (`estado_pago_no_finalizable`).  
   - `INCOMPLETO` **prohibido**.
6. `Validar Pago` ∈ `{SI, NO}`.
7. Si `Estado Pago=NORMAL` y `Validar Pago=NO` → **`Observación` obligatoria**.
8. Si `Validar Pago=SI` y estado ∈ `{NORMAL, ATRASADO, ADELANTADO}`:
   - completar `Aplicar a extracto`, `Mora a aplicar`, `Abono a capital`, `Otros valores`;
   - `Total aplicado` > 0;
   - suma de totales por `ID Pago` = `Monto banco` (±0.01) — **cuadratura** (`amount_mismatch`);
   - subtipo cuota+capital: reglas adicionales de parte cuota / capital / saldo 0.
9. Resolver todos los `REVISION_MANUAL` antes de cerrar.

### Hoja `Distribucion_Abonos` (si existe)

10. Cumplir validaciones de grupos/selección del use case (`_validate_abono_groups`).

### Operativa Excel Online

11. **Guardar** el libro.  
12. Esperar sincronización SharePoint.  
13. **Cerrar** Excel Online antes de Finalize (evitar bloqueo / HTTP 423 en uploads).

---

## 12. Matriz de errores (mínimo)

| Caso | error_code | user_message (fuente) | next_action | severity | retryable | link |
|------|------------|----------------------|-------------|----------|-----------|------|
| Review missing | `missing_validation_file_path` / ItemNotFound | enricher / Graph | Regenerar o restaurar path | fatal | cond. | revisión |
| Excel locked | mapped `upload`/`423`/`locked` | enricher | Cerrar Excel Online | fatal | sí | revisión |
| Procesar ≠ SI | `process_not_approved` | `_FINALIZE_MESSAGES` | Poner Procesar=SI | fatal | sí | Control |
| Estado ≠ EN_REVISION | `invalid_control_state` | idem | Estado=EN_REVISION | fatal | sí | Control |
| Hoja/columna faltante | `missing_control_sheet` / `missing_distribucion_sheet` / `missing_sheet_headers` | idem | Regenerar | fatal | no | — |
| Errores abiertos | `review_has_open_errors` | idem | Limpiar hoja Errores | fatal | sí | Errores |
| REVISION_MANUAL | `estado_pago_no_finalizable` | idem | Resolver filas | fatal | sí | Distribución |
| Estado Pago inválido | `invalid_estado_pago` / `empty_estado_pago` | idem | Usar lista | fatal | sí | Distribución |
| Validar Pago inválido | vía política / empty | | Corregir SI/NO | fatal | sí | Distribución |
| Obs. ausente | `no_validar_requires_observation` | idem | Escribir observación | fatal | sí | Distribución |
| Montos | `amount_mismatch` | idem | Rebalancear totales | fatal | sí | Distribución |
| ProcessKey mismatch | UI `process_key_mismatch` (nuevo síncrono) | | Refrescar proceso | fatal | sí | detalle |
| Proceso no activo | `control_not_ready_for_finalize` | idem | Volver a Generate | fatal | no | — |
| Lock ocupado | 409 busy | mensaje JobManager | Esperar / poll | fatal | sí | jobs |
| Ya finalizado | job `already_finalized` | mensaje éxito reused | Continuar a Notify (futuro) | success | no | hist/sec |
| Graph | Graph/HTTP errors | enricher | Reintentar / soporte | fatal | cond. | — |
| Sin sesión | 401 | | Login | fatal | sí | /app |
| CSRF/Origin/flags | 403 | | Corregir cliente / flags | fatal | sí | — |

---

## 13. Anti-duplicado PA/UI

1. Generate activo → Finalize UI 409.  
2. Finalize PA activo → Finalize UI 409.  
3. Finalize UI activo → Generate PA 409.  
4. Doble clic Finalize UI → un job (`try_start_finalize`).  
5. UI + PA simultáneos → uno solo (mismo mutex).  
6. Reintento post-éxito → `already_finalized`; mismo ProcessKey; sin hist/sec/carpetas/auditoría duplicados.  
7. Finalize completed + Notify failed → Finalize sigue completed; UI **no** ofrece re-Finalize; Notify etapa independiente.

---

## 14. Frontend

- Botón **“Finalizar validación”** solo si `available_actions.finalize.allowed`.
- Link **“Abrir Excel de revisión”**.
- Modal: banco, ProcessKey, nombre archivo; advertencia guardar/cerrar Excel Online; confirmación.
- Bloqueo doble clic; mostrar `job_id`, progreso, resultado, `user_message`, `next_action`.
- Links a histórico / soporte si el job los devuelve.
- **Sin** botones Notify / Merge / Dry-run / Apply.
- Tras éxito: steps `generate=completed`, `review=completed`, `finalize=completed`, `notify=not_started`, resto `not_started`.  
  **No** inferir Notify completed.

Auditoría best-effort en job: `trigger_source=web_ui`, `requested_by=<username>`, `ui_request_id=<uuid>` (sin columnas nuevas obligatorias en control).

---

## 15. Tests propuestos

Seguridad 1–10; integración 11–25; Excel 26–37; UI 38–44 — según autorización del usuario (lista completa en la query).  
Prioridad: flag `UI_FINALIZE_ENABLED`, shared service, locks cruzados, idempotencia, contrato PA intacto, cero Notify.

---

## 16. Commits propuestos (futuros)

1. `feat(finalize): extraer FinalizeQueueService compartido PA/UI` (+ fix import `infer_terminal_status_from_result` en runner).  
2. `feat(ui-auth): flag UI_FINALIZE_ENABLED + gate Finalize`.  
3. `feat(ui-api): POST /processes/finalize + available_actions.finalize`.  
4. `feat(ui): SPA Finalize/poll/modal`.  
5. `test(ui): seguridad, locks, idempotencia Finalize`.  
6. `docs: U3-B implementation + cierre documental U3-A`.

Conventional Commits en español. Sin push/merge hasta autorización.

---

## 17. Deploy futuro en dos pasos

### Paso 1 — código + flag off

```text
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=false
```

- Generate sigue OK.  
- Finalize UI → 403.  
- Cero mutaciones Finalize.  
- PA intacto.

### Paso 2 — flag on + un Finalize controlado

```text
UI_FINALIZE_ENABLED=true
```

- Un solo Finalize del proceso Bogotá (si sigue válido y Excel preparado).  
- Sin Notify.  
- Verificar side effects + idempotencia.  
- Rollback inmediato: `UI_FINALIZE_ENABLED=false`.

**No ejecutar estos pasos en esta entrega.**

---

## 18. Rollback específico

1. **Primera respuesta:** `UI_FINALIZE_ENABLED=false` (Generate permanece).  
2. Solo si regresión global: redeploy `azure-deploy-u3a-generate-enabled.zip`; validar Generate, login, PA.  
3. **No** bajar `UI_WRITE_ENABLED` primero si el defecto es solo Finalize.

---

## 19. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| `infer_terminal_status_from_result` sin import en runner PA | Corregir al extraer service (obligatorio) |
| Excel Online lock (423) | Checklist cerrar Excel; mensaje accionable |
| Operador deja `REVISION_MANUAL` | Checklist + `estado_pago_no_finalizable` |
| ProcessKey stale en UI | POST revalida vs control; 409 mismatch |
| Activar Finalize con solo `UI_WRITE` | Flag dedicado `UI_FINALIZE_ENABLED` |
| Confundir Notify fallido con Finalize fallido | Etapas independientes; no re-Finalize |
| Duplicar hist/sec | Idempotencia ProcessKey + tests |
| Refactor grande de readiness puro | Opción B (no duplicar schema en FE) |

---

## 20. Confirmaciones de esta entrega

| Acción | Estado |
|--------|--------|
| Código U3-B | **0** |
| Modificación Excel revisión/control | **0** |
| Deploy | **0** |
| Push | **0** |
| Merge | **0** |
| Finalize ejecutado | **0** |

**Esperar autorización** antes de implementar o desplegar U3-B.
