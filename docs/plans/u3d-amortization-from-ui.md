# Plan U3-D — Procesar amortización desde la UI

> **Nota v3 (2026-08):** extract-index eliminado del runtime (sin EXTRACT_INDEX_* ni /extract-index/admin). Workbook operador = Aplicacion_Pagos / _Meta (no Distribucion_* / Casos_Pago). Este plan es histórico de la fase UI.


**Fecha:** 2026-07-31  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Precondición:** U3-C2 **cerrado** en sandbox (`UI_MERGE_ENABLED=true`, Bogotá `CONSOLIDADO`).  
**Estado de este documento:** PLAN únicamente.  
**NO autorizado en esta entrega:** código de producto, deploy, Dry-run real, Apply real, escritura de tablas, push, merge git.

---

## 0. Runtime a conservar (sin cambios en el plan)

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true
UI_MERGE_ENABLED=true
UI_AMORTIZATION_ENABLED=false   # NUEVO propuesto — fail-closed hasta Paso 2 futuro
UI_AUTH_MODE=local_session
# EXTRACT_INDEX eliminado
# Contabilidad off · mocks off
```

### Proceso sandbox de referencia (no mutar en el plan)

| Campo | Valor |
|-------|--------|
| Banco | `banco_bogota` |
| ProcessKey | `payment-validation\|banco_bogota\|2026-07-30\|8a5c7ad3-faae-412f-928d-5878442c700d` |
| Estado | `CONSOLIDADO` |
| Dry-run / Apply desde UI hasta hoy | **cero** |

### Decisión UX obligatoria

| Visible al operador | Interno |
|---------------------|---------|
| Una sola acción: **“Procesar amortización”** | Dry-run = validación previa obligatoria |
| `available_actions.amortization` | Reutiliza use cases dry-run + apply |
| Sin botones Dry-run / Apply / Validar dry-run | Sin POST UI `/dry-run` ni `/apply` |
| Sin endpoints Graph ni jerga técnica | Steps/auditoría pueden traducir estados |

**Flujo UX → backend**

1. Operador pulsa “Procesar amortización”.
2. Backend ejecuta validación previa interna (dry-run).
3. Si `can_apply=false` → no Apply, no tablas, errores operativos, reintento tras corrección.
4. Si `can_apply=true` → continúa Apply en el mismo flujo autorizado.

---

## 1. Endpoints Power Automate actuales (shapes exactos)

Router: `app/adapters/primary/http/routers/payment_validation.py`  
Prefijo: `/graph/sharepoint/payment-validation`  
Auth: `X-API-Key` (`api_key_auth.py`) cuando `API_HTTP_KEY` está set.  
**No** están en `sharepoint.py`.

### 1.1 Dry-run

| Ítem | Valor |
|------|--------|
| **URL** | `POST /graph/sharepoint/payment-validation/amortization/dry-run/queue` |
| **HTTP** | **202** |
| **Body model** | `AmortizationDryRunRequest` (definido **en el router**, no en `models.py`) |
| **Poll** | `GET /graph/sharepoint/payment-validation/jobs/{job_id}` |
| **Job type** | `amortization_dry_run` |
| **Store** | `JobManager` (disco `.payment_validation_jobs`) + `BackgroundTasks` |
| **Mutex** | **Ninguno** hoy (no participa en Generate/Finalize/Notify/Merge) |

```python
class AmortizationDryRunRequest(BaseModel):
    report_date_iso: str | None = None
    merge_manifest_path: str | None = None
    historical_file_path: str | None = None
    bank_code: str | None = None
```

Body omitido / `{}` válido. `report_date_iso` inválido → **422**.

**202:**

```json
{ "job_id": "<uuid4>", "status": "queued" }
```

(Sin `message` / `poll_url` / `estimated_processing_seconds` — distinto de Notify/Merge.)

**Job inicial persistido:** `type`, `status=queued`, `queued_at`, `request={…}`.

**Poll:** `enrich_job_for_http_response` → estados `queued`→`running`→`completed`|`failed`; en completed incluye `result` (+ `user_message` / `next_action` / `severity`).

### 1.2 Apply

| Ítem | Valor |
|------|--------|
| **URL** | `POST /graph/sharepoint/payment-validation/amortization/apply/queue` |
| **HTTP** | **202** |
| **Body** | Mismo `AmortizationDryRunRequest` |
| **Poll** | Mismo `GET …/payment-validation/jobs/{job_id}` |
| **Job type** | `amortization_apply` |
| **Store** | JobManager + BackgroundTasks |
| **Mutex** | **Ninguno** hoy |

**202:** idéntico `{ "job_id", "status": "queued" }`.

**Invariante U3-D:** conservar URLs, bodies, 202, poll, X-API-Key y shapes terminales PA. La UI **no** hará HTTP interno a `/graph`.

---

## 2. Use cases actuales

| Rol | Archivo | Función principal |
|-----|---------|-------------------|
| Dry-run | `app/application/use_cases/amortization_fill_dry_run.py` | `run_amortization_fill_dry_run` |
| Apply | `app/application/use_cases/amortization_fill_apply.py` | `run_amortization_fill_apply` |
| Workbook | `services/amortization_workbook.py` | filas, fórmulas, `_AUTOMATION_LOG`, clave idempotencia |
| Orden eventos | `services/amortization_event_order.py` | `amortization_event_order_key` |
| Safety | `services/amortization_apply_safety.py` | warnings gate, PDF hash, verify post-upload |
| ABONO dry-run | `services/abono_dry_run.py` | cuadre híbrido, next free row |
| ABONO gate | `services/abono_apply_gate.py` | `evaluate_abono_apply_block` |
| Merge gate | `services/merge_manifest_gate.py` | `eligible_for_dry_run`, bloqueo incompleto |
| IBR | `services/ibr_workbook.py` | `find_ibr_for_date` |
| PDF | `services/accounting_pdf_parser.py` | extract/parse |
| Move | `services/accounting_pdf_processed_move.py` | → `PROCESADOS/` post-Apply |
| Control | `use_cases/payment_validation_process_control.py` | snapshot / update row2 |

**Cola PA hoy:** runners privados `_run_amortization_dry_run_job` / `_run_amortization_apply_job` en el router (patrón previo a QueueService de Notify/Merge).

**Nota técnica (riesgo):** el runner usa `infer_terminal_status_from_result` en paths de éxito; verificar import en implementación (posible `NameError` latente → job `failed` tras use case OK).

---

## 3. Jobs / stores

| Aspecto | Dry-run / Apply hoy | Generate/Finalize/Notify/Merge |
|---------|---------------------|--------------------------------|
| Persistencia | JobManager disco | JobManager disco |
| Scheduling | `BackgroundTasks` | QueueService + BackgroundTasks |
| Mutex compartido | **No** | Sí (`_any_mutation_active`) |
| Claim por ProcessKey | **No** | Notify/Merge sí |
| Sobrevive restart | Sí (huérfanos → failed/interrupted) | Sí |

**Deuda U3-D:** amortización puede solaparse con Merge u otras etapas.

---

## 4. Estados de control

### Entrada runnable (auto-detect) — `AMORTIZATION_RUNNABLE_STATES`

```text
CONSOLIDADO
MERGE_PARCIAL          # detectable, pero gate de merge suele bloquear
ERROR_APPLY            # reintentable
AMORTIZACION_PARCIAL   # reintentable (híbrido)
APLICANDO_AMORTIZACION # stale / mid-flight reintentable si job terminal
```

Requiere además: `IsActive`, `MergeManifestPath`, `HistoricalFilePath`.

### Gate de manifiesto (bloquea Dry-run/Apply globales)

- `manifest_status=COMPLETE`, `eligible_for_dry_run=true`, `incomplete_groups_count=0`.
- Estados “ok” para el gate: `CONSOLIDADO`, `APLICANDO_AMORTIZACION`, `AMORTIZACION_PARCIAL`, `ERROR_APPLY`.
- **`MERGE_PARCIAL`:** bloqueo `MERGE_INCOMPLETE_NOT_APPLICABLE` hasta re-Merge completo.

### Escritos por Apply

| Estado | Cuándo |
|--------|--------|
| `APLICANDO_AMORTIZACION` | al iniciar Apply |
| `AMORTIZACION_APLICADA` | éxito completo |
| `AMORTIZACION_PARCIAL` | algunas tablas OK |
| `ERROR_APPLY` | fallo / preflight fail / excepción |

Dry-run con `update_process_control=True` (PA) puede actualizar `LastStepStatus` (RUNNING/COMPLETED/WARNINGS/FAILED) **sin** cambiar `EstadoProceso` a aplicado.

---

## 5. Reglas financieras existentes (código manda)

| Regla | Comportamiento |
|-------|----------------|
| **Fecha pago** | Solo **Fecha banco** (histórico → `fecha_banco` del grupo). Sin fallback a fecha asiento / `report_date` para escribir. Diff vs asiento = auditoría en payload, no bloquea. |
| **PAGO** | Asiento + extracto en Merge; dry-run: fecha límite, `due_date_row`, IBR, plan filas desde cuota |
| **ABONO** | Solo asiento; sin extracto/IBR/cuota; cuadre `valor_pagado_cliente` vs `monto_banco` ±0.02; siguiente fila libre |
| **Columnas O:P** | **Nunca** escribe `dia` / `Causac Inter Mes` |
| **Orden eventos** | Fecha asiento ↑ → recaudo antes que ajuste saldos menores → nº asiento ↑ → índice manifiesto |
| **Celdas combinadas** | Unmerge antes de escribir |
| **IBR** | Solo PAGO cuando `actualiza_ibr` y plan `WOULD_WRITE_IBR` |
| **Pagos adelantados** | Búsqueda desde `due_date_row`; no backfill de cuotas anteriores; workbook aparte no consumido por Apply |
| **Grupos parciales** | Merge incompleto → bloqueo global; Apply mixto ABONO bloqueado → fail-closed; parcial de tablas → `AMORTIZACION_PARCIAL` |

Doc `payment-validation-production-flow.md`: alineado en O:P, orden, ABONO; **revisar** frases antiguas sobre “fecha del asiento” vs Fecha banco (código = Fecha banco).

---

## 6. Efectos Dry-run

| Efecto | ¿Sí? |
|--------|------|
| Escritura tablas amortización | **No** (`dry_run_wrote_changes=false`) |
| Move a PROCESADOS | **No** |
| Descarga manifest / histórico / IBR / PDFs / tablas | **Sí** (lectura) |
| Parsers PDF | **Sí** |
| `can_apply` | **Sí** (PAGO statuses + ABONO ready) |
| Errores / items / summary | **Sí** en `result` |
| Control Excel | **Sí** si `update_process_control=True` (LastStepStatus); Apply interno usa `False` |
| `_AUTOMATION_LOG` | Lectura (idempotencia ABONO); no append |

---

## 7. Efectos Apply

1. Idempotencia gruesa: `AMORTIZACION_APLICADA` + `ApplyIdempotencyKey==ProcessKey` → `already_applied=true`, cero escrituras.
2. Gate merge + dry-run interno + ABONO gate + preflight.
3. Por tabla: escribe fecha_pago, intereses, abono_k, mora, retenciones, fórmulas saldo; IBR si aplica; **no** O:P.
4. `append_automation_log` + verify upload; Graph 423 → `EXCEL_LOCKED`.
5. Mueve asientos `APPLIED` verificados a `…/ASIENTOS…/PROCESADOS/`.
6. Control: estado terminal, `ApplyIdempotencyKey`, `ApplyJobId`, paths.
7. Éxito total: elimina Excel de revisión y limpia `ValidationFilePath`.
8. Parcial: `AMORTIZACION_PARCIAL` (sin transacción distribuida SharePoint).

---

## 8. Idempotencia actual

| Capa | Mecanismo |
|------|-----------|
| Proceso | `ApplyIdempotencyKey = ProcessKey` + estado `AMORTIZACION_APLICADA` |
| Evento | `id_pago\|credito\|asiento_path\|comprobante\|pdf_hash` en `_AUTOMATION_LOG` |
| Retry parcial | Cuadre híbrido; solo escribe `WOULD_*`; `ALREADY_APPLIED` no duplica |
| PDF cambiado misma ruta | `PDF_CHANGED_SAME_PATH` |
| Log sí / fila vacía | puede reescribir “huérfano” |

---

## 9. Concurrencia actual (deuda)

- Doble POST Dry-run/Apply → **nuevos jobs** sin 409 busy.
- No exclusión con Merge/Generate/Finalize/Notify.
- Soft: estado `APLICANDO_AMORTIZACION` + Excel lock 423.
- **Riesgo alto** para UI: doble clic / solape con Merge.

---

## 10. Riesgos

1. Sin mutex → escrituras concurrentes / control last-writer-wins.
2. Apply parcial sin TX → retry obligatorio con log híbrido.
3. `MERGE_PARCIAL` runnable pero bloqueado por gate → UX debe decir “falta consolidar”, no “amortizar”.
4. Dry-run PA escribe LastStepStatus → UI debe acotar writes de control en fase validación.
5. Import `infer_terminal_status_from_result` en runner.
6. Doc vs código en Fecha pago (asiento vs banco).
7. Scope creep: no exponer Dry-run/Apply como acciones.
8. Contabilidad off en sandbox: paths Operaciones vs Contabilidad.

---

## 11. Servicio propuesto — `AmortizationQueueService`

Nombre preferido: **`AmortizationQueueService`**  
(archivo: `app/application/services/amortization_queue_service.py`)

Compartido conceptualmente:

- UI: orquestación única “Procesar amortización”.
- PA: adapters thin que conservan POST dry-run y POST apply **separados** (contratos intactos), delegando runners al service sin HTTP interno.

### Orquestación UI (un solo job visible)

```text
POST /api/ui/v1/processes/amortization
        │
        ▼
 AmortizationQueueService.enqueue_process(...)   # ui_mode
        │
        ├─ try_claim_amortization_for_process
        ├─ set_job type=amortization_process (o amortization_apply con fases)
        ├─ fase validate: run_amortization_fill_dry_run(...)
        ├─ persistir validation_result + can_apply
        ├─ si can_apply=false → completed + outcome=requires_correction
        │     (cero Apply, cero tablas)
        └─ si can_apply=true  → run_amortization_fill_apply(...)
              → completed + outcome=applied|partial|failed
        finally: finish_amortization
```

PA dry-run / apply siguen siendo dos entradas HTTP que llaman métodos `enqueue_dry_run` / `enqueue_apply` del mismo service (misma persistencia + **nuevo mutex**).

---

## 12. JobManager / mutex

Proponer (espejo Notify/Merge):

| Método | Rol |
|--------|-----|
| `try_start_amortization` | mutex global |
| `finish_amortization` | finally |
| `is_amortization_active` | proyección |
| `try_claim_amortization_for_process` | `ok` \| `busy` \| `already_applied` |
| `has_completed_amortization` | evidencia completa (`AMORTIZACION_APLICADA` / `already_applied`) |
| `find_successful_amortization_by_process_key` | job persistido |

Incluir `_amortization_active` en `_any_mutation_active` junto a Generate/Finalize/Notify/Merge.

**No deben bloquear reintento:** `AMORTIZACION_PARCIAL`, `ERROR_APPLY`, job failed/interrupted, `requires_correction`, ProcessKey distinto.

**`already_applied`:** solo éxito completo de proceso (control + evidencia job), no parcial.

Persistencia: `.payment_validation_jobs` + reconcile huérfanos.

---

## 13. Flag — `UI_AMORTIZATION_ENABLED`

```text
UI_AMORTIZATION_ENABLED=false
```

| Regla | Detalle |
|-------|---------|
| Ausente/inválido | `false` |
| Independiente | No implica Dry-run/Apply visibles; no altera otros flags |
| Entorno | Solo sandbox; producción fail-closed |
| Corte | Con `false`: **403** antes de lock, job, Graph, PDFs, dry-run, tablas, control |
| Bootstrap | `amortization_allowed` (global), distinto de `available_actions.amortization` |

**No** crear `UI_DRY_RUN_ENABLED` / `UI_APPLY_ENABLED`.

---

## 14. Endpoint UI

```http
POST /api/ui/v1/processes/amortization
```

```json
{
  "bank_code": "banco_bogota",
  "process_key": "payment-validation|..."
}
```

`extra=forbid`. Backend resuelve control, manifiesto, histórico, IBR y paths.

**Prohibido en body:** paths, manifest, dry_run, apply, force, fechas, créditos, eventos, API key.

| HTTP | Caso |
|------|------|
| 202 | Encolado (`accepted`, `action=amortization`, `job_id`, `poll_url`) |
| 401 | Sin sesión |
| 403 | CSRF/Origin/flag/ambiente/write |
| 409 | busy / identidad / no preparado / `already_applied` |
| 422 | Body inválido |

Auth: `local_session` + CSRF + Origin (patrón U3-A…C2).

---

## 15. Readiness — `AmortizationReadinessService`

Read-only. Sin mutex, jobs, Apply ni writes.

DTO:

```json
{
  "status": "ready|incomplete|unknown|already_applied",
  "can_start": true,
  "expected_items": 0,
  "ready_items": 0,
  "missing_items": [],
  "warnings": [],
  "checked_at": "...",
  "user_message": "...",
  "next_action": "..."
}
```

Revisa de forma liviana: estado runnable + gate-friendly, ProcessKey, IsActive, manifiesto COMPLETE / `eligible_for_dry_run`, outputs, existencia PDFs/tablas evidentes, IBR path si aplica, job activo, ya aplicado.

No parsear masivamente todos los PDF si basta listado + metadatos de manifiesto.

---

## 16. `available_actions.amortization`

Única acción nueva. **Prohibido** `dry_run` / `apply` en `available_actions`.

`compute_amortization_availability` (puro): flags + sandbox + snap + locks + evidencia + readiness.

`allowed=true` solo si: sandbox, writes, flag, activo, estado runnable **y** merge listo (no `MERGE_PARCIAL` incompleto), sin job activo, no already_applied, readiness ready.

Visible: **“Procesar amortización”**.

---

## 17. Frontend

| Momento | UX |
|---------|-----|
| Antes | “La información está lista para validar y aplicar.” + créditos/eventos esperados + aviso tablas sandbox |
| Durante | “Validando información.” → “Aplicando pagos.” + poll |
| `requires_correction` | “Se encontraron datos que requieren corrección.” + errores/links; **sin** decir Dry-run; confirmar cero escrituras |
| Éxito | “Amortización procesada correctamente.” + resumen/enlaces |
| Parcial | “La amortización se aplicó parcialmente.” + reintento seguro |
| Ya aplicado | botón off: “Este proceso ya fue aplicado a las tablas.” |

Steps internos pueden mostrar “Preparación amortización” / “Aplicar amortización” **sin** la palabra técnica “Dry-run” en copy de operador (ya parcialmente así en SPA).

Sin llamadas React a endpoints Graph de amortización.

---

## 18. Errores y recuperación

| Outcome job UI | Comportamiento |
|----------------|----------------|
| `requires_correction` | completed; `can_apply=false`; mutex libre; reintento tras corregir archivos |
| `applied` | `AMORTIZACION_APLICADA`; already_applied en reintento |
| `partial` | `AMORTIZACION_PARCIAL`; reintento híbrido |
| `failed` | `ERROR_APPLY` o equivalente; mutex libre; mensaje accionable |

Mensajes vía enrichment existente (mapear códigos a lenguaje operativo, sin jargon Dry-run).

---

## 19. Seguridad — plan de pruebas

Sin sesión → 401; solo API key en UI → 401; CSRF/Origin → 403; flag false → 403 antes de efectos; producción fail-closed; body con paths/dry_run/apply/force → 422; cookie UI ≠ `/graph`; API key ≠ UI.

---

## 20. Pruebas de idempotencia / concurrencia (diseño)

1. Doble clic → 409, un job.  
2. `can_apply=false` → cero Apply / cero filas.  
3. Reintento tras corrección → permitido.  
4. Aplicado completo → 409 `already_applied`.  
5. Cero filas/eventos duplicados; claves estables.  
6. `MERGE_PARCIAL` → no start (readiness/availability).  
7. `AMORTIZACION_PARCIAL` reintentable.  
8. failed/interrupted no bloquean.  
9. ProcessKey distinto no bloqueado.  
10. Restart no duplica escrituras; huérfanos interrupted.  
11. Tablas/log ya actualizados detectados.  
12. PA y UI no escriben en paralelo (mutex).  
13. Generate/Finalize/Notify/Merge bloquean amortización y viceversa.

---

## 21. Compatibilidad Power Automate

| Contrato | Conservar |
|----------|-----------|
| POST dry-run/queue | URL, body, 202 `{job_id,status}` |
| POST apply/queue | idem |
| GET jobs/{id} | enrichment + result shapes (`can_apply`, `already_applied`, …) |
| Auth | X-API-Key |
| Reintentos PA | sin params extra obligatorios |

Implementación: thin adapters → `AmortizationQueueService.enqueue_dry_run` / `enqueue_apply` con mutex nuevo; **sin** cambiar shape HTTP. UI no llama `/graph`.

---

## 22. Deploy futuro (dos pasos)

### Paso 1 — código apagado

```text
UI_AMORTIZATION_ENABLED=false
# Generate / Finalize / Notify / Merge siguen true
```

Validar: POST amortización UI → 403; PA dry-run/apply contratos intactos (**sin** ejecutar Apply real en smoke salvo autorización posterior); cero tablas tocadas por UI.

### Paso 2 — activación sandbox

```text
UI_AMORTIZATION_ENABLED=true
```

Validar: readiness → acción única → validación interna → Apply solo si `can_apply` → doble clic → poll → idempotencia → parcial/retry según proceso Bogotá `CONSOLIDADO`.

---

## 23. Rollback

| Nivel | Acción |
|-------|--------|
| Específico | `UI_AMORTIZATION_ENABLED=false` — **sin** apagar Generate/Finalize/Notify/Merge |
| Completo | Solo regresión global de la app |

---

## 24. Recomendación arquitectónica

### Opción A — Un solo job UI (recomendada)

**Ventajas**

- Alinea UX (una acción) con un `job_id` y un poll.
- Apply **ya** ejecuta dry-run interno; la orquestación UI formaliza fases `validate` → `apply` y un outcome `requires_correction` sin exponer dos botones.
- Un claim/mutex/finally; menos carreras.
- PA conserva dos endpoints históricos sin forzar al operador a conocerlos.

**Desventajas**

- Job más largo; progreso debe distinguir “Validando” vs “Aplicando”.
- Hay que diseñar el shape de `result` UI (`validation` + `apply`) sin romper poll PA de jobs legacy.

### Opción B — Dos jobs internos correlacionados

Útil solo si se necesita reutilizar 1:1 los tipos `amortization_dry_run` / `amortization_apply` en auditoría. Añade correlación, doble persistencia y peor UX de poll. **No recomendada** para U3-D.

### Decisión

Adoptar **Opción A**: `AmortizationQueueService` + job único UI (`amortization_process` o apply con fases) + PA dry-run/apply como facades. Incorporar amortización al mutex global. Flag único `UI_AMORTIZATION_ENABLED`.

---

## 25. Confirmación de esta entrega (plan)

| Ítem | Estado |
|------|--------|
| 0 código de producto | ✅ |
| 0 deploy | ✅ |
| 0 Dry-run real | ✅ |
| 0 Apply real | ✅ |
| 0 tablas modificadas | ✅ |
| 0 push | ✅ |
| 0 merge git | ✅ |
| Runtime Generate/Finalize/Notify/Merge sandbox | **sin cambios** |

---

## Mapa de entregables

| # | Tema | Sección |
|---|------|---------|
| 1 | Endpoints PA | §1 |
| 2 | Use cases | §2 |
| 3 | Jobs/stores | §3 |
| 4 | Estados | §4 |
| 5 | Reglas financieras | §5 |
| 6 | Efectos Dry-run | §6 |
| 7 | Efectos Apply | §7 |
| 8 | Idempotencia | §8 |
| 9 | Concurrencia | §9 |
| 10 | Riesgos | §10 |
| 11 | Servicio | §11 |
| 12 | JobManager/mutex | §12 |
| 13 | Flag | §13 |
| 14 | Endpoint UI | §14 |
| 15 | Readiness | §15 |
| 16 | available_actions | §16 |
| 17 | Frontend | §17 |
| 18 | Errores | §18 |
| 19 | Seguridad | §19 |
| 20 | Pruebas | §20 |
| 21 | Compatibilidad PA | §21 |
| 22 | Deploy dos pasos | §22 |
| 23 | Rollback | §23 |
| 24 | Recomendación | §24 |
| 25 | Confirmación | §25 |

---

## Próximo paso (requiere autorización explícita)

Implementar U3-D en código **solo** tras aprobación de este plan, empezando por:

1. JobManager amortización + mutex.  
2. `AmortizationQueueService` + facades PA (contratos intactos).  
3. Flag `UI_AMORTIZATION_ENABLED=false` + POST UI + readiness + availability.  
4. Frontend “Procesar amortización”.  
5. Tests; ZIP Paso 1 off.
