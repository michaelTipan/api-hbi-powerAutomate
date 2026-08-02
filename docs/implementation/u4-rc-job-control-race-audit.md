# Auditoría: carrera job `completed` vs Control SharePoint (todos los endpoints UI)

**Fecha:** 2026-08-01  
**Alcance:** Generate · Finalize · Notify · Merge · Amortization (UI) · Cancel  
**Pregunta:** ¿El mismo problema de Finalize (UI stale hasta recargar) existe en los demás?

## Resumen ejecutivo

| Endpoint / acción | ¿Mismo problema? | Efecto típico si Control va atrasado | Mitigación FE actual |
|---|---|---|---|
| **Finalize** | **Sí (confirmado en prod/sandbox)** | «Requiere corrección» + stepper en Revisar | Detalle: reintentos GET (`jobProjectionSync`) |
| **Generate** | **Sí (misma mecánica)** | «Requiere corrección» / lista inconsistente | **Dashboard: un solo `reload()` — vulnerable** |
| **Notify** | **Parcial** | Suele quedar en «aún no enviado» (no corrección) | Detalle: reintentos; predicate razonable |
| **Merge** | **Parcial + bug de sync FE** | Queda en «esperando documentos» | Detalle reintenta, pero **`PENDIENTE_ASIENTOS` aborta retries demasiado pronto** |
| **Amortization** | **Parcial / baja** | Paso apply atrasado; rara vez `CORRECCION_REQUERIDA` vía JM | Detalle: reintentos |
| **Cancel** | N/A en SPA | — | No hay botón cancel en UI operador |

**Causa raíz común:** no es que el backend marque el job `completed` *antes* de escribir Control (en el camino feliz escribe Control y luego `set_job(completed)`). El hueco es **consistencia de lectura Graph**: el GET de proyección puede bajar el Excel de Control todavía viejo unos segundos. La proyección interpreta “job completed + evidencia ausente en Control” como **`failed_business`** → **`CORRECCION_REQUERIDA`**.

---

## 1) Orden en backend (colas)

En Generate / Finalize / Notify / Merge / Amortization UI el patrón observado es:

1. Use case muta SharePoint + `update_process_control_row2` (o equivalente).
2. Retorna resultado.
3. Queue service: `set_job(..., status="completed")`.

No se encontró un “completed primero, Control después” en el happy path. El fallo es de **lectura eventual**, no de escritura invertida.

---

## 2) Proyección: ramas “job completed sin evidencia”

Archivo: `app/application/ui/process_projection.py`

| Condición | Paso | → `operational_status` |
|---|---|---|
| `jm_status("generate")=="completed"` y sin `ValidationFilePath` | `failed_business` (~L309–314) | **`CORRECCION_REQUERIDA`** |
| `jm_status("finalize")=="completed"` y sin histórico | `failed_business` (~L368–373) | **`CORRECCION_REQUERIDA`** ← bug visto |
| memory Notify `completed` sin clave/PDF | `failed_business` (~L405–410) | **`CORRECCION_REQUERIDA`** (UI hoy usa JM; menos frecuente) |
| memory Merge `completed` sin manifest | `failed_business` (~L461–466) | **`CORRECCION_REQUERIDA`** (UI hoy usa JM) |
| `jm_status("amortization_apply","apply")=="completed"` y estado ∉ apply-done | `failed_business` (~L517–522) | **`CORRECCION_REQUERIDA`** (tipo UI `amortization_process` casi no matchea `"apply"`) |

Prioridad operacional (~L546–549): cualquier `failed_business` gana sobre `FINALIZADO` / `PENDIENTE_NOTIFICACION`.

Por eso el panel del job puede decir “finalizó correctamente” (job polled) mientras el badge dice «Requiere corrección» (proyección stale).

---

## 3) Frontend por superficie

### ProcessDetailPage (Finalize / Notify / Merge / Amortization)

- Poll: tick **inmediato** + cada 2,5 s.
- Tras terminal: `reloadUntilProjectionMatchesJob` con delays `[0, 700, 1500, 3000]` ms.
- Predicate: `frontend/src/domain/jobProjectionSync.ts`.

| Job | ¿El predicate detecta Control atrasado? | Notas |
|---|---|---|
| Finalize | **Sí** | Exige finalize completed / `FINALIZADO` / `PENDIENTE_NOTIFICACION` |
| Notify | **Sí** | Exige notify completed / `ESPERANDO_SOPORTES` / `email_pdf_path` |
| Merge | **No del todo** | Acepta `PENDIENTE_ASIENTOS` como “ya sync” → **falso positivo**: si Merge acaba de completar y Control aún está en `PENDIENTE_ASIENTOS`, **deja de reintentar** y la UI puede quedarse “esperando documentos” hasta recarga |
| Amortization | **Sí** | Exige apply completed / `COMPLETADO` / `AMORTIZACION_APLICADA` |
| Generate | Cubierto en predicate, **pero el detalle no lanza Generate** | — |

### DashboardPage (solo Generate)

- Tras job terminal: **un único** `reload()` de lista/bancos.
- **Sin** `jobProjectionSync`.
- Misma rama de proyección Generate → riesgo de «Requiere corrección» / tarjeta inconsistente hasta F5.

---

## 4) Detalle por endpoint

### Finalize — vulnerable (confirmado)

- Mecánica exacta del incidente del operador.
- BE: Control write luego `completed` (`finalize_queue_service` + use case).
- Proyección: L368–373.
- FE detalle: mitigado con retries (pendiente deploy del fix).

### Generate — vulnerable (misma clase)

- Proyección L309–314 idéntica en espíritu.
- UI principal: **Dashboard** sin retries.
- Si el operador inicia validación y el primer GET de procesos ve Control sin `ValidationFilePath`, puede pintar corrección falsa hasta recargar.

### Notify — parcialmente vulnerable

- Con jobs en JobManager, la rama dura `failed_business` “completed sin evidencia” está acoplada a **memory**, no a `jm_status`.
- Control stale en `FINALIZADO`: notify suele verse `not_started` (CTA reenviar), **no** «Requiere corrección».
- Peor síntoma: retraso en avanzar a «Enviar hecho / Esperando documentos», no el badge rojo de Finalize.
- FE detalle sí reintenta.

### Merge — parcialmente vulnerable + bug FE sync

- Con JM, `failed_business` “sin manifest” es vía memory (menos probable en UI).
- Control stale post-merge exitoso: a menudo sigue `PENDIENTE_ASIENTOS` / merge `blocked` → UX de “aún esperando” sin badge de corrección.
- **Bug en `jobProjectionSync`:** tratar `PENDIENTE_ASIENTOS` como éxito de sync **corta los reintentos** justo cuando hace falta seguir pidiendo el GET.

### Amortization — riesgo bajo/medio

- Tipo de job UI `amortization_process` no encaja bien en `jm_status(..., "apply")`, así que la rama `failed_business` es rara.
- Puede quedar stepper/apply atrasado hasta F5; FE detalle reintenta con criterio razonable.

### Cancel — fuera de SPA

- Existe en API; la UI operador actual no lo dispara.

---

## 5) Conclusión

1. **Sí: no es solo Finalize.** Generate compartía la mecánica más peligrosa (`CORRECCION_REQUERIDA`).
2. Causa funcional: **desfase temporal entre job `completed` y Control** (no afirmar Graph lag sin prueba instrumental).
3. **Implementado (local, sin deploy):** regla centralizada:
   - BE: `sync_pending` + `SINCRONIZANDO` (no `failed_business` / `CORRECCION_REQUERIDA`).
   - FE: `reloadUntilProjectionMatchesJob` compartido (dashboard + detalle), copy «Sincronizando resultados…», timeout de sincronización (no error financiero).
   - Merge: `PENDIENTE_ASIENTOS` ya no confirma sync.
   - Tests: `tests/test_ui_job_control_sync_pending.py` + `frontend/src/domain/jobProjectionSync.test.ts`.

## 6) Acciones pendientes

| Prio | Acción |
|---|---|
| P0 | Desplegar cuando se autorice (pack sandbox UI + smoke) |
| P1 | Validar en sandbox Generate/Finalize/Notify/Merge/Apply con operador |

## Evidencia de código

- Diagnóstico Finalize: `docs/implementation/u4-rc-finalize-stale-projection-diagnosis.md`
- Sync FE: `frontend/src/domain/jobProjectionSync.ts`
- Proyección: `app/application/ui/process_projection.py` (`sync_pending` / `SINCRONIZANDO`)
- Dashboard + detalle: mismo helper de reintentos
- Tests BE: `tests/test_ui_job_control_sync_pending.py`
