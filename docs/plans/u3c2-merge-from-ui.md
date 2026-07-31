# Plan U3-C2 — Merge (Consolidar soportes) desde la UI

**Fecha:** 2026-07-31  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Precondición:** U3-C1 **cerrado** en sandbox (`UI_NOTIFY_ENABLED=true`, idempotencia Notify validada).  
**Estado de este documento:** PLAN únicamente.  
**NO autorizado en esta entrega:** código de producto, deploy, Merge real, Dry-run, Apply, push, merge git.

---

## 0. Estado runtime a conservar (sin cambios en U3-C2 plan)

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true          # sandbox only — no tocar
UI_AUTH_MODE=local_session
UI_MERGE_ENABLED=false          # NUEVO propuesto — fail-closed hasta Paso 2 futuro
EXTRACT_INDEX_MODE=off
# Contabilidad off · mocks off
# Dry-run / Apply: FUERA de U3-C2 (interno; sin botón ni POST UI)
```

### Aclaración UX obligatoria

| Superficie | Visible al operador | En U3-C2 |
|---|---|---|
| **Merge / “Consolidar soportes”** | Sí (acción) | Sí |
| Dry-run | No botón, no `available_actions`, no POST UI, no llamada React | No |
| Apply | No | No |

Dry-run puede seguir existiendo en `steps`/auditoría como estado interno traducido a lenguaje operativo, pero **no forma parte del alcance de implementación U3-C2**.

### Proceso sandbox de referencia (post U3-C1)

| Campo | Valor |
|-------|--------|
| Banco | `banco_bogota` |
| ProcessKey | `payment-validation\|banco_bogota\|2026-07-30\|8a5c7ad3-faae-412f-928d-5878442c700d` |
| Estado actual | `PENDIENTE_ASIENTOS` (Notify ya enviado; Merge **aún no** ejercitado post-fix) |
| Histórico / email PDF | presentes |
| Notify | completado (2 jobs históricos incidentales; idempotencia bloquea reenvío) |

---

## 1. Endpoint Power Automate actual (shape exacto — no cambiar contrato)

| Ítem | Evidencia |
|------|-----------|
| **Enqueue** | `POST /graph/sharepoint/merge-composite-validado-pdfs` → **202** |
| **Poll** | `GET /graph/sharepoint/merge-composite-validado-pdfs/jobs/{job_id}` |
| **Router** | `app/adapters/primary/http/routers/sharepoint.py` |
| **Auth** | `X-API-Key` vía `api_key_auth.py` (cuando `API_HTTP_KEY` está set); sin key → 401 |
| **Body model** | `MergeCompositeValidadoRequest` en `app/models.py` |
| **Montaje** | `app_factory.py` → `include_router(sharepoint.router)` |

### Request PA (body opcional; `{}` / omitido válidos)

```python
class MergeCompositeValidadoRequest(BaseModel):
    bank_code: str | None = None              # banco_bogota | banco_bancolombia
    historical_file_path: str | None = None   # override manual
    email_pdf_path: str | None = None         # override manual
    force_rebuild: bool = False               # regenera aunque exista consolidado
```

Si no hay overrides, el use case auto-detecta el único banco con estado ∈ `MERGE_RUNNABLE_STATES` + `IsActive` + histórico + email PDF.

### Response 202 (enqueue)

```json
{
  "status": "queued",
  "job_id": "<uuid4>",
  "estimated_processing_seconds": 300,
  "message": "Trabajo en cola. Consulta /graph/sharepoint/merge-composite-validado-pdfs/jobs/{job_id}"
}
```

### Polling

- Hoy: job en **memoria** del módulo sharepoint (`_validation_jobs` + `asyncio.Lock`).
- Estados: `queued` → `running` → `completed` | `failed`.
- Respuesta enriquecida con `enrich_job_for_http_response` (`job_status_enrichment.py`; tipo `merge_composite_validado_pdfs`).
- **Limitación actual:** el job **no sobrevive** recycle del worker (GET → 404). La verdad de negocio sí sobrevive en Control + PDFs + manifiesto SharePoint.

### Resultado `completed` (campos que el runner serializa hoy)

Incluye, entre otros: `status`, `outputs[]`, `skipped`, `merge_control_*`, `merge_manifest_path`, `process_key`, `process_control_estado`, `already_merged`, `file_action` (`created`|`partial`|`reused`), `merge_idempotency_key`, `pdf_created`, `pdf_reused`, `already_consolidated`, `force_rebuild_used`, counts payment/abono, URLs de carpeta consolidación.

**Invariante U3-C2:** misma URL, mismo body, misma 202, mismo poll path, misma auth X-API-Key, mismos reintentos PA **sin** parámetros extra obligatorios.

---

## 2. Use case actual

| Ítem | Valor |
|------|--------|
| **Archivo** | `app/application/use_cases/merge_composite_validado_pdfs.py` |
| **Función principal** | `merge_composite_validado_pdfs(...)` |
| **Runner HTTP** | `_run_merge_composite_validado_pdfs_job` en `sharepoint.py` (`asyncio.create_task`) |
| **Servicios** | control (`read/update_process_control_*`), histórico (`read_validated_*_rows`), `merge_group_validation`, `merge_manifest_gate.assess_manifest_completeness`, `review_schema` policy, `AccountingDestinationResolver` (si Contabilidad configurada), `pypdf` merge |
| **Cola actual** | **No** hay `MergeQueueService`. No usa `BackgroundTasks` ni `JobManager`. |
| **Store** | `_validation_jobs` en RAM (módulo sharepoint) |

---

## 3. Estados de control aceptados

### Entrada runnable — `MERGE_RUNNABLE_STATES`

```text
PENDIENTE_ASIENTOS   # post-Notify: primer intento
MERGE_PARCIAL        # faltaron soportes; reintentable
ERROR_MERGE          # fallo duro previo; reintentable
CONSOLIDANDO         # quedó a medias (p. ej. recycle); reintentable
CONSOLIDADO          # repetición → rama idempotente already_merged
```

### Escritos por Merge

| Estado | Cuándo |
|--------|--------|
| `CONSOLIDANDO` | al iniciar trabajo |
| `CONSOLIDADO` | todos los grupos OK |
| `MERGE_PARCIAL` | grupos incompletos / fallidos / outputs vacíos |
| `ERROR_MERGE` | excepción no recuperada tras haber entrado a `CONSOLIDANDO` |

Estados posteriores de amortización (`APLICANDO_AMORTIZACION`, …) aparecen en proyección UI como “merge done”, pero **no** son inputs de Merge ni parte de U3-C2.

---

## 4. Precondiciones

| Gate | Regla |
|------|--------|
| Auto-banco | Exactamente un banco ready (runnable + active + histórico + email PDF) |
| `IsActive` | `true` (salvo overrides manuales de path en body PA) |
| ProcessKey | desde control; si vacío se construye bank+fecha Colombia |
| Histórico | path requerido |
| Email PDF / soporte correo | path requerido (post-Notify) |
| Filas | `Validar Pago=SI` (pagos); abonos con `Validar Abono=SI` + rutas |
| ASIENTOS | `RutaAsientosContables` por crédito; ≥1 PDF con dígitos de crédito; subcarpetas `PROCESADOS`/`PROCESADO` **ignoradas** al listar |
| Extractos | según política / `Ruta`; faltantes → skip grupo |
| Contabilidad | opcional; si site configurado, resuelve carpeta año/mes/banco |

**Nota:** overrides PA (`historical_file_path`, `email_pdf_path`, `force_rebuild`) **no** se expondrán en el body UI.

---

## 5. Efectos secundarios

1. Control → `CONSOLIDANDO`.
2. Descarga histórico + PDF correo + fuentes por grupo.
3. Upload PDF consolidado por `id_pago` (Contabilidad si aplica; si no, carpeta Operaciones de merge).
4. Upload manifiesto `merge_manifest_{bank}_{date}.json`.
5. Control → `CONSOLIDADO` | `MERGE_PARCIAL` (+ paths, counts, `MergeIdempotencyKey=process_key`).
6. En error duro → `ERROR_MERGE`.

**No hace hoy:** mover asientos a `PROCESADOS` (solo las ignora al listar), no envía correo, no Generate/Finalize, no Dry-run/Apply.

---

## 6. Idempotencia actual

| Escenario | Comportamiento |
|-----------|----------------|
| Control `CONSOLIDADO` + manifiesto completo + `force_rebuild=false` | Early return: `already_merged=true`, `pdf_reused=true`, `file_action=reused`, sin reescribir PDFs |
| PDF destino ya existe + grupo COMPLETE en manifiesto previo | Reutiliza (`group_can_reuse_existing_pdf`) |
| `MERGE_PARCIAL` | Reintento permitido; revalida; reusa COMPLETE; reconstruye faltantes |
| Clave | `MergeIdempotencyKey = ProcessKey` (no hash/eTag de contenido) |
| `force_rebuild=true` (solo PA) | Fuerza regeneración |

---

## 7. Concurrencia actual (deuda a cerrar en U3-C2)

| Aspecto | Hoy | Riesgo |
|---------|-----|--------|
| Doble POST Merge | Nuevo UUID cada vez; **sin** 409 busy | Dos merges concurrentes; last-writer-wins en control |
| Mutex con Generate/Finalize/Notify | **No** participa | Puede solaparse con otras etapas |
| JobManager | Sin `try_start_merge` | Jobs Merge no en disco |
| Restart | Job RAM perdido; control puede quedar `CONSOLIDANDO` (reintentable) | Poll 404; operador confuso |

---

## 8. Errores recuperables (muestra; enrichment existente)

| Código / caso | Mensaje operativo (orientación) |
|---------------|----------------------------------|
| `NO_READY_PROCESS` / `control_not_ready_for_merge` | Completar Finalize + Notify antes |
| `MULTIPLE_READY_PROCESSES` | Indicar banco |
| `missing_*_path` | Falta histórico o PDF de correo |
| `asiento_contable_not_found` / mismatch | Cargar/renombrar soportes en ASIENTOS |
| `extract_routes_missing` | Corregir rutas de extracto |
| `MERGE_PARCIAL` (completed warning) | Cargar faltantes y reintentar consolidación |
| Fallos Graph upload/download | Reintentar / permisos / archivo abierto |

---

## 9. Diseño propuesto — `MergeQueueService`

### Objetivo

Una sola orquestación compartida por **Power Automate** y **UI**, al estilo `FinalizeQueueService` / `NotifyQueueService`.

```text
PA POST /graph/.../merge-composite-validado-pdfs
UI  POST /api/ui/v1/processes/merge
        │
        ▼
 MergeQueueService.enqueue(...)
        │
        ├─ try_start_merge()          # JobManager (nuevo)
        ├─ set_job(...) persistido    # .payment_validation_jobs
        ├─ BackgroundTasks / runner
        ├─ merge_composite_validado_pdfs(...)
        └─ finish_merge()
```

### Reglas de cableado

- **No** HTTP interno UI → `/graph`.
- **No** importar runners privados del router PA (`_run_merge_*` se mueve/delega al service).
- Routers PA y UI solo adaptan auth/HTTP → service.
- Poll PA **conserva** la misma URL; internamente lee JobManager (+ enrichment), no solo RAM.

### Extensión JobManager

| Método | Rol |
|--------|-----|
| `try_start_merge()` | Adquiere mutex compartido con Generate/Finalize/Notify |
| `finish_merge()` | Libera mutex |
| `is_merge_active()` | Lectura para proyección / availability |
| Persistencia | Igual patrón disk + reconcile orphaned → `failed` / `JobInterruptedByProcessRestart` |
| Evidencia | Opcional: `find_successful_merge_by_process_key` / `has_completed_merge` (espejo Notify) para UI tras restart |

### Mutex — decisión de diseño

**Merge comparte el mutex global actual** con Generate, Finalize y Notify.

Motivos:

- Evita dos escritores concurrentes sobre el mismo control/SharePoint.
- Alinea operador: “una etapa a la vez”.
- Doble clic / doble POST → **409** busy (un solo job).

**Reintento `MERGE_PARCIAL`:** permitido cuando el mutex está libre y el estado sigue runnable.

---

## 10. Flag — `UI_MERGE_ENABLED`

```text
UI_MERGE_ENABLED=false   # default
```

| Regla | Detalle |
|-------|---------|
| Ausente / inválido | `false` |
| Independiente | No implica Dry-run ni Apply; no altera Generate/Finalize/Notify |
| Entorno | Solo sandbox en esta fase; producción fail-closed |
| Corte temprano | Con `false`: **403** antes de lock, job, Graph o archivos |
| Rollback | Solo apaga Merge UI; Generate/Finalize/Notify siguen |

Bootstrap UI debe exponer `merge_allowed` (análogo a `notify_allowed`).

---

## 11. Endpoint UI propuesto

```http
POST /api/ui/v1/processes/merge
```

### Body mínimo cerrado

```json
{
  "bank_code": "banco_bogota",
  "process_key": "payment-validation|banco_bogota|2026-07-30|…"
}
```

### Prohibido desde el navegador

`paths`, URLs, carpeta destino, `historical_file_path`, `email_pdf_path`, `secretary_file_path`, manifest path, `force` / `force_rebuild`, `dry_run`, `apply`, destinatarios, API key.

El backend resuelve todo desde **control + configuración activa**.

### Respuestas esperadas

| HTTP | Caso |
|------|------|
| 202 | Encolado (`job_id`, polling UI vía job read existente) |
| 401 | Sin sesión |
| 403 | CSRF/Origin; o `ui_merge_disabled`; o producción |
| 409 | Merge/otra etapa busy; o `already_merged` (si se modela como Notify) |
| 422 | Body con campos extra / paths |

Auth: sesión `local_session` + CSRF + Origin allowlist (mismo patrón U3-A/B/C1).

---

## 12. `available_actions.merge` — `compute_merge_availability` (puro)

Entradas típicas: flags, sandbox, locks, snapshot control, existencia paths (histórico/email), resumen liviano de soportes (si ya cacheado), job merge activo, evidencia `has_completed_merge` / control `CONSOLIDADO`.

| Resultado | Condición orientativa |
|-----------|------------------------|
| `allowed=false` | flag off / no sandbox / lock ocupado / no ProcessKey / no IsActive / estado no runnable / faltan precondiciones / ya consolidado completo |
| `allowed=true` | sandbox + flag + `PENDIENTE_ASIENTOS`\|`MERGE_PARCIAL`\|`ERROR_MERGE`\|`CONSOLIDANDO` stale + precondiciones OK + mutex libre |
| reason operativo | p. ej. “Faltan soportes contables.” / “Los soportes están listos para consolidar.” / “La consolidación quedó parcial; …” / “Ya consolidado.” |

**Prohibido en availability:** crear carpetas, mover archivos, generar PDF, adquirir lock, Graph mutante, parseo masivo de PDFs. Listar nombres/conteos de ASIENTOS solo si es read-only y barato (o reutilizar datos ya proyectados).

**No** exponer `dry_run` ni `apply` en `available_actions` en U3-C2.

---

## 13. Readiness para el operador (antes de Merge)

Mostrar en detalle de proceso:

- Banco, ProcessKey, estado (traducido).
- Histórico presente / link.
- Soporte de correo (PDF enviado) presente / link.
- Cantidad de pagos/créditos esperados vs soportes encontrados.
- Lista de soportes faltantes (crédito / tipo).
- Links a carpetas ASIENTOS donde cargar.
- Advertencia: “Al consolidar se generarán los PDFs compuestos y se actualizará el control.”

Mensajes ejemplo:

- “Faltan soportes contables.”
- “Cargue los archivos pendientes antes de consolidar.”
- “Los soportes están listos para consolidar.”
- “La consolidación quedó parcial; corrija los archivos indicados y reintente.”

No usar el nombre interno del estado como **única** explicación.

---

## 14. Frontend

| Elemento | Propuesta |
|----------|-----------|
| Botón / acción | **“Consolidar soportes”** (visible cuando `available_actions.merge.allowed`) |
| Durante job | Polling; deshabilitar doble clic; mostrar progreso |
| Éxito | “Consolidación completada”; links a PDFs / carpeta destino; nota si `pdf_reused` |
| Parcial | Mensaje operativo + lista faltantes + CTA reintentar |
| Oculto | Dry-run, Apply, endpoints, rutas técnicas, manifiesto como “acción” |

Tras éxito, step `merge` → `completed` (o `partial` si `MERGE_PARCIAL`).

---

## 15. Seguridad — plan de pruebas

| Caso | Esperado |
|------|----------|
| Sin sesión | 401 |
| Solo `X-API-Key` en UI | 401 UI |
| Sin CSRF | 403 |
| Origin incorrecto/ausente | 403 |
| `UI_MERGE_ENABLED=false` | 403 **antes** de efectos |
| Body con paths / force / dry_run | 422 |
| Producción | bloqueado fail-closed |
| Cookie UI en `/graph` | no autentica PA |
| API key en `/api/ui` | no autentica UI |

---

## 16. Idempotencia y concurrencia — plan de pruebas

| Caso | Esperado |
|------|----------|
| Doble clic durante Merge | 409; **un** solo job |
| Reintento tras `CONSOLIDADO` | `already_merged` / `pdf_reused`; cero PDF duplicado |
| Mismo ProcessKey / manifiesto estable | sin drift |
| `MERGE_PARCIAL` | reintentable; solo pendientes; COMPLETE reusado |
| PDFs ya en destino / grupos COMPLETE | detectados; no duplicar |
| Restart mid-flight | job persistido o control `CONSOLIDANDO` reintentable; **no** segunda consolidación fantasma |
| PA y UI | misma evidencia JobManager + control |

---

## 17. Deploy futuro (dos pasos — no en esta entrega)

### Paso 1 — código Merge UI apagado

```text
UI_MERGE_ENABLED=false
# Generate / Finalize / Notify siguen true en sandbox
```

Validar: POST Merge UI → 403; PA contrato intacto; cero Merge real.

### Paso 2 — activación sandbox

```text
UI_MERGE_ENABLED=true
```

Validar: readiness → un Merge real sandbox → doble clic 409 → polling → éxito o parcial/reintento → idempotencia → **cero** Dry-run/Apply.

---

## 18. Rollback

| Nivel | Acción |
|-------|--------|
| **Específico Merge** | `UI_MERGE_ENABLED=false` — **sin** apagar Generate/Finalize/Notify |
| Completo | Solo ante regresión global de la app (fuera del default U3-C2) |

---

## 19. Riesgos

1. **Migración store:** pasar Merge de RAM → JobManager puede romper poll PA si el GET no se adapta bien — mitigar con adapter que preserve path y shape.
2. **Mutex nuevo:** PA que hoy permite Merge concurrente con otras etapas pasará a 409 — documentar en runbook; es mejora deseada.
3. **`force_rebuild`:** solo PA; UI no lo expone — operadores UI deben usar reintento parcial, no rebuild forzado (salvo herramienta PA).
4. **Contabilidad off en sandbox:** carpeta destino Operaciones vs Contabilidad — validar paths sandbox en Paso 2.
5. **Readiness barata vs completa:** listar ASIENTOS sin parsear PDFs; no reimplementar todo el use case en proyección.
6. **Proceso Bogotá actual en `PENDIENTE_ASIENTOS`:** candidato natural a primer Merge sandbox en Paso 2 (tras cargar soportes), no en esta entrega.
7. **Scope creep Dry-run/Apply:** mantener fuera de U3-C2 aunque existan steps internos.

---

## 20. Confirmación de esta entrega (plan)

| Ítem | Estado |
|------|--------|
| 0 código de producto | ✅ |
| 0 deploy | ✅ |
| 0 Merge ejecutado | ✅ |
| 0 Dry-run | ✅ |
| 0 Apply | ✅ |
| 0 push | ✅ |
| 0 merge git | ✅ |
| Runtime Generate/Finalize/Notify sandbox | **sin cambios** |

---

## Mapa de entregables solicitados

| # | Tema | Sección |
|---|------|---------|
| 1 | Endpoint PA | §1 |
| 2 | Use case | §2 |
| 3 | Cola/store actual | §2, §7 |
| 4 | Estados y precondiciones | §3–§4 |
| 5 | Efectos secundarios | §5 |
| 6 | Locks | §7, §9 |
| 7 | Idempotencia | §6, §16 |
| 8 | Recuperación parciales | §3, §6, §8 |
| 9 | MergeQueueService | §9 |
| 10 | Endpoint UI | §11 |
| 11 | Flag | §10 |
| 12 | available_actions | §12 |
| 13 | readiness | §13 |
| 14 | frontend | §14 |
| 15 | seguridad | §15 |
| 16 | pruebas | §15–§16 |
| 17 | deploy dos pasos | §17 |
| 18 | rollback | §18 |
| 19 | riesgos | §19 |
| 20 | confirmación | §20 |

---

## Próximo paso (requiere autorización explícita)

Implementar U3-C2 en código **solo** tras aprobación de este plan, empezando por:

1. `MergeQueueService` + JobManager merge mutex/persistencia.
2. Thin adapters PA (contrato intacto) + flag `UI_MERGE_ENABLED=false`.
3. Endpoint UI + availability + readiness + botón “Consolidar soportes”.
4. Tests (sin deploy hasta Paso 1 autorizado).
