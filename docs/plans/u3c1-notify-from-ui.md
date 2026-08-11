# Plan U3-C1 — Notify desde la UI (sandbox)

> **Nota v3 (2026-08):** extract-index eliminado del runtime (sin EXTRACT_INDEX_* ni /extract-index/admin). Workbook operador = Aplicacion_Pagos / _Meta (no Distribucion_* / Casos_Pago). Este plan es histórico de la fase UI.


**Fecha:** 2026-07-30  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD base:** `4eaf23e9848d16bd42a95530f23b5703611d4d4b`  
**Estado:** IMPLEMENTADO localmente (Paso 1 Notify **off**).  
**NO autorizado:** deploy U3-C1, `UI_NOTIFY_ENABLED=true`, correo real, push, merge.  
**Precondición:** U3-B cerrado (Finalize UI operativo en sandbox con `UI_FINALIZE_ENABLED=true`).
**Ajuste obligatorio:** destinatarios sandbox `UI_NOTIFY_SANDBOX_TO/CC` fail-closed (ver implementación).

---

## 0. Estado runtime a conservar

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true          # Generate + Finalize siguen en sandbox
UI_AUTH_MODE=local_session
UI_NOTIFY_ENABLED=false           # NUEVO — default fail-closed hasta Paso 2
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# EXTRACT_INDEX eliminado
# Contabilidad off · mocks off
# Merge / Dry-run / Apply: fuera de U3-C1
```

### Proceso sandbox de referencia (post U3-B)

| Campo | Valor |
|-------|--------|
| Banco | `banco_bogota` |
| ProcessKey | `payment-validation\|banco_bogota\|2026-07-30\|8a5c7ad3-faae-412f-928d-5878442c700d` |
| Estado | `FINALIZADO`, `IsActive=true` |
| Histórico / soporte | presentes (Finalize job `22f8a8b9-…`) |
| Notify | **no ejecutado** (`NotifyIdempotencyKey` / `EmailPdfPath` vacíos al cierre U3-B) |

---

## 1. Endpoint PA, request, response y polling

| Ítem | Evidencia |
|------|-----------|
| **Enqueue** | `POST /graph/sharepoint/notify-validar-extractos-email` → **202** |
| **Poll** | `GET /graph/sharepoint/notify-validar-extractos-email/jobs/{job_id}` |
| **Router** | `app/adapters/primary/http/routers/sharepoint.py` |
| **Auth** | `X-API-Key` (Graph); sesión UI **no** autentica este path |
| **Body model** | `NotifyValidarExtractosRequest` en `app/models.py` |

### Request PA

```python
class NotifyValidarExtractosRequest(BaseModel):
    historical_file_path: str | None = None  # override manual opcional
    bank_code: str | None = None             # banco_bogota | banco_bancolombia
    to: str | None = None                    # override destinatarios
    cc: str | None = None                    # override CC
```

Si `historical_file_path` está vacío, el use case auto-detecta el único banco con  
`EstadoProceso=FINALIZADO` + `IsActive=true` + `HistoricalFilePath` no vacío.

### Response 202 (enqueue)

```json
{
  "status": "queued",
  "job_id": "<uuid>",
  "estimated_processing_seconds": 180,
  "message": "Trabajo en cola. Consulta /graph/sharepoint/notify-validar-extractos-email/jobs/{job_id}"
}
```

### Polling

- Job en memoria del módulo sharepoint (`_validation_jobs` + `asyncio.Lock`), **no** el `JobManager` de Generate/Finalize.
- Estados: `queued` → `running` → `completed` | `failed`.
- Respuesta enriquecida vía `enrich_job_for_http_response`.
- **Limitación:** jobs Notify se pierden si el worker recicla (a diferencia de Generate/Finalize persistidos en disco por `JobManager`).

---

## 2. Use case y “JobManager” utilizados

| Capa | Pieza |
|------|--------|
| Use case | `send_validar_extractos_notification_email` en `app/application/use_cases/send_validar_extractos_notification.py` |
| Fallo en control | `record_notify_failure_on_control` (deja `FINALIZADO`; marca `LastStepStatus=FAILED`) |
| Cola PA actual | `_run_notify_validar_extractos_job` + dict `_validation_jobs` (sharepoint router) |
| **No usa** | `JobManager.try_start_generate/finalize` — Notify **no** comparte el mutex Generate/Finalize hoy |

**Implicación U3-C1:** hay que introducir `NotifyQueueService` (como Generate/Finalize) y decidir migración del store de jobs Notify al `JobManager` singleton para paridad PA/UI, persistencia y doble clic.

---

## 3. Locks e idempotencia (hoy)

### Locks actuales

- **Notify:** sin mutex de negocio; solo lock de dict para escribir el job. Dos POST PA concurrentes pueden encolar dos jobs.
- **Generate/Finalize:** mutex cruzado en `JobManager` (`try_start_generate` / `try_start_finalize`).

### Idempotencia de negocio (use case)

Si el control ya está en:

- `EstadoProceso=PENDIENTE_ASIENTOS`
- + `ProcessKey` presente
- + `EmailPdfPath` no vacío
- + `NotifyIdempotencyKey` no vacío  

→ retorna éxito corto con `merge_control_warning/error_code=already_notified` **sin** reenviar correo ni regenerar PDF.

`NotifyIdempotencyKey` se escribe como el `process_key` al completar Notify con PDF.

---

## 4. Estados permitidos

| Condición | Resultado |
|-----------|-----------|
| Auto-detect / path desde control: `FINALIZADO` + `IsActive` + `HistoricalFilePath` | Entra al flujo real |
| Ya `PENDIENTE_ASIENTOS` + evidencia Notify | `already_notified` (skip envío) |
| Otro estado / inactivo | `control_not_ready_for_notify` |
| Sin histórico | `missing_historical_file_path` / `NO_READY_PROCESS` |
| Dos bancos listos | `MULTIPLE_READY_PROCESSES\|…` |
| Fallo mid-flight | Control **sigue** `FINALIZADO`; solo metadatos de error (`LastCompletedStep=NOTIFY`, `LastStepStatus=FAILED`) |

Notify **no** exige `REVISION_CREADA` (eso es Finalize).

---

## 5. Efectos secundarios (crítico)

Notify es **mutante y envía correo real**:

1. **Graph `sendMail`** con `saveToSentItems=true` — correo real a destinatarios de `CORREOS.xlsx` (o overrides `to`/`cc`).
2. **PDF del correo** (si `GRAPH_VALIDAR_NOTIFY_EXPORT_EMAIL_PDF=true`, default on) subido a la carpeta EMAIL del árbol de validación (`resolve_email_export_folder_path()`; default lógico `05 EMAIL` / override env; en sandbox operativo suele mapear a **CORREOS ENVIADOS**).
3. **Control (éxito con PDF):**
   - `EstadoProceso` → **`PENDIENTE_ASIENTOS`**
   - `EmailPdfPath`, `NotifyIdempotencyKey=process_key`, `NotifyJobId`
   - limpia errores; `LastCompletedStep=NOTIFY` / `COMPLETED`
   - **conserva** `ProcessKey`, `HistoricalFilePath`, `IsActive=true`
4. **Adjuntos del correo:** extractos PDF según reglas del histórico (grupos pago/abono).
5. **No ejecuta** Finalize, Merge, Dry-run ni Apply.

**Riesgo U3-C1:** un smoke Notify en sandbox envía correo real a los RECEPTORES de `CORREOS.xlsx`. El plan de deploy Paso 2 debe usar destinatarios de prueba o override explícito autorizado (solo si se aprueba; el endpoint UI propuesto **no** expone `to`/`cc` por defecto — ver §8).

---

## 6. Qué sucede al reintentar

| Escenario | Comportamiento |
|-----------|----------------|
| Éxito previo → `PENDIENTE_ASIENTOS` + keys | Skip: `already_notified`, sin segundo correo/PDF |
| Fallo previo → sigue `FINALIZADO` | Reintento completo permitido (nuevo sendMail + PDF) |
| POST concurrente hoy | Puede crear 2 jobs (deuda a corregir en QueueService) |

---

## 7. Diseño propuesto: `NotifyQueueService` compartido PA/UI

Espejo de `GenerateQueueService` / `FinalizeQueueService`:

```text
NotifyQueueService.enqueue(...)
  → lock try_start_notify()   # nuevo en JobManager
  → validación bank_code
  → create job type=notify_validar_extractos (JobManager + disco)
  → BackgroundTasks / create_task → use case existente
  → finish_notify() en finally
```

### Extensión `JobManager` (propuesta)

```text
try_start_notify()  → False si generate|finalize|notify activos
finish_notify()
is_notify_active() / is_generate_or_finalize_or_notify_active()
```

- **Doble clic UI/PA:** 409 `notify_busy`.
- **No bloquea** lecturas UI.
- **PA:** thin adapter en `sharepoint.py` que llama al mismo servicio; poll URL **sin cambio de contrato** (`…/notify-validar-extractos-email/jobs/{id}`), implementado leyendo `JobManager.get_job` (migración desde dict in-memory).
- **UI poll:** `GET /api/ui/v1/jobs/{job_id}` (ya enruta tipos notify vía `job_read.py`).

### Use case

**No reimplementar** el envío: reutilizar `send_validar_extractos_notification_email`.  
La UI resuelve `historical_file_path` desde control tras validar `process_key` (no lo envía el cliente como path libre).

---

## 8. Endpoint UI propuesto

```http
POST /api/ui/v1/processes/notify
Content-Type: application/json
Origin: <UI_ALLOWED_ORIGINS>
X-CSRF-Token: <csrf>
Cookie: sesión local_session

{ "bank_code": "banco_bogota", "process_key": "<ProcessKey completo>" }
```

- Body: **solo** `bank_code` + `process_key` (`extra=forbid`).
- **No** aceptar `historical_file_path`, `to`, `cc` desde UI (evita path injection y override de destinatarios).
- Gates (orden, fail-closed): sesión → rol operator → Origin → JSON → CSRF → `UI_WRITE_ENABLED` → sandbox → **`UI_NOTIFY_ENABLED`** → identidad control → enqueue.
- Resolución: leer snapshot del banco; exigir `process_key` coincidente, `FINALIZADO`, `IsActive`, `HistoricalFilePath`; pasar ese path al use case.
- Response 202 alineada a Generate/Finalize UI:

```json
{
  "accepted": true,
  "action": "notify",
  "bank_code": "banco_bogota",
  "process_key": "...",
  "job_id": "...",
  "status": "queued",
  "poll_url": "/api/ui/v1/jobs/..."
}
```

Errores: 401 sesión; 403 CSRF/Origin/write/notify-disabled/not-sandbox; 409 identity/busy/not-ready; 422 bank inválido.

---

## 9. Flag `UI_NOTIFY_ENABLED`

| Propiedad | Valor |
|-----------|--------|
| Env | `UI_NOTIFY_ENABLED` |
| Default | **false** (ausente/inválido → false) |
| Parseo | estricto, igual que `UI_FINALIZE_ENABLED` |
| Bootstrap | `notify_allowed = writes && notify_enabled && sandbox` |
| Independiente | no implica Merge; apagar Notify no apaga Generate/Finalize |

---

## 10. `available_actions.notify`

Cálculo puro `compute_notify_availability` (espejo finalize_capabilities):

Permitido solo si:

1. writes + sandbox + `UI_NOTIFY_ENABLED`
2. lock notify/generate/finalize libre
3. snapshot activo, `EstadoProceso=FINALIZADO`
4. `HistoricalFilePath` presente
5. `process_key` coincide
6. **no** ya notificado (`NotifyIdempotencyKey`/`EmailPdfPath`/estado `PENDIENTE_ASIENTOS` → `allowed=false` con razón accionable)

Exponer en detalle de proceso (y opcionalmente banks). SPA: botón Notify deshabilitado/oculto con razón cuando flag off.

---

## 11. Confirmar que Finalize no se repite

| Garantía | Cómo |
|----------|------|
| Notify no llama Finalize | Solo `send_validar_extractos_notification_email` |
| UI Notify no reencola Finalize | Endpoint distinto; body sin paths de revisión |
| `available_actions.finalize` | Sigue false fuera de `REVISION_CREADA` (FINALIZADO → no Finalize) |
| Estado post-Notify | `PENDIENTE_ASIENTOS` — Finalize UI permanece bloqueado por estado |
| Smoke U3-C1 | Assert: 0 jobs `type=finalize` nuevos; `FinalizeJobId` sin cambio |

---

## 12. Pruebas (plan de suites)

### Seguridad

- sin sesión → 401  
- solo API key → 401  
- sin CSRF / CSRF malo → 403  
- Origin malo/ausente → 403  
- `UI_NOTIFY_ENABLED=false` → 403 `ui_notify_disabled` (antes de Graph)  
- cookie UI ≠ auth `/graph`  
- body con campos extra / path → 422  

### Doble clic / locks

- 202 + segundo POST → 409 `notify_busy`  
- cero segundo envío de correo (mock Graph en unit; en smoke: un solo `NotifyJobId`)  

### PA / UI compartidos

- PA `POST …/notify-validar-extractos-email` sin cambio de contrato  
- mismo use case / misma cola  
- poll PA y UI leen el mismo job  

### Idempotencia

- tras éxito: reintento → `already_notified` / UI `allowed=false`  
- sin segundo PDF ni segundo correo  

### Proyección

- steps: Notify `completed` tras éxito; Finalize no vuelve a `in_progress`  
- links: `email_pdf` / histórico; **sin** Merge/Dry-run/Apply actions  

---

## 13. Deploy futuro en dos pasos

### Paso 1 — Notify off (obligatorio primero)

- Paquete mismo HEAD de implementación U3-C1  
- Flags: sandbox, write=true, finalize=true, **`UI_NOTIFY_ENABLED=false`**  
- Validar: bootstrap `notify_allowed=false`; POST Notify → 403; Generate/Finalize intactos; PA Notify contrato intacto (**sin ejecutar** Notify PA); cancel protegido  

### Paso 2 — Notify on + smoke controlado

- Solo tras OK Paso 1 y autorización explícita  
- `UI_NOTIFY_ENABLED=true`  
- **Un** Notify UI con ProcessKey FINALIZADO real  
- Destinatarios: confirmar `CORREOS.xlsx` sandbox (o procedimiento acordado) — **envío real**  
- Validar: 202, doble clic 409, completed, control → `PENDIENTE_ASIENTOS`, PDF en carpeta correos, reintento idempotente, 0 Finalize nuevo, 0 Merge  

---

## 14. Rollback específico

Si el defecto es solo Notify:

1. `UI_NOTIFY_ENABLED=false`  
2. Redeploy/restart del paquete off (o PUT `.env` + OneDeploy static)  
3. Confirmar `notify_allowed=false` y POST 403  
4. Generate + Finalize UI **siguen** habilitados  
5. PA contratos intactos  

Rollback completo a ZIP U3-B solo si regresión global (auth, Generate, Finalize, PA).

---

## 15. Confirmación de esta entrega (plan)

| Ítem | Estado |
|------|--------|
| Código escrito | **0** |
| Deploy | **0** |
| Notify ejecutado | **0** |
| Push | **0** |
| Merge | **0** |
| Artefacto | este plan (`docs/plans/u3c1-notify-from-ui.md`) |

---

## Alcance explícitamente fuera de U3-C1

- Merge / Dry-run / Apply desde UI  
- Overrides `to`/`cc`/`historical_file_path` en UI  
- Producción / Entra  
- Migración control → listas  
- Cambiar plantilla HTML/PDF del correo (salvo bugs bloqueantes descubiertos en implementación)

---

## Orden de implementación sugerido (cuando se autorice código)

1. Flag + bootstrap + `notify_capabilities`  
2. `JobManager` notify lock + `NotifyQueueService`  
3. Adaptar PA router al servicio (contrato estable)  
4. `POST /api/ui/v1/processes/notify` + resolución por ProcessKey  
5. SPA: acción Notify + poll + razones  
6. Tests seguridad/locks/idempotencia/PA  
7. Docs implementation + ZIP Paso 1 off  

---

## Recomendación

**Aprobar el plan U3-C1** con énfasis en:

1. Smoke Paso 2 = **correo real** → validar destinatarios sandbox antes.  
2. Migrar cola Notify a `JobManager` (deuda actual vs Generate/Finalize).  
3. Mantener Generate+Finalize on en sandbox; Notify off hasta Paso 2 autorizado.
