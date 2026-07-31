# UI API Contract v1

**Fase:** U1 + U1.5 (proyección read-only + SharePoint vía `UiSharePointReadPort`)

**Base path:** `/api/ui/v1`

**Auth:** `Authorization: Bearer …` (modo `mock` o `entra`). Nunca `X-API-Key` en el navegador.

U1.5: la proyección consume Control/manifest/meta por puerto read-only inyectable
(fakes en pytest; smoke Graph real solo con `UI_SHAREPOINT_SMOKE=1` + sandbox).
Estados canónicos de pago: NORMAL | ATRASADO | ADELANTADO | REVISION_MANUAL.
Históricos no canónicos → `legacy_state` + `legacy_warning` (sin remapear).

El cliente **no** envía paths ni URLs Graph. Query `path` / `web_url` → 400.
Los paths se derivan en backend desde `bank_code` + Control del ambiente activo.
Enlaces al operador: `web_url` resueltas por el servidor.

Si Control conserva rutas del árbol sandbox anterior
(`02 COMWARE AUTOMATIZACION…`), la respuesta puede incluir
`errors[].error_code = "legacy_sandbox_path"` (severity `warning`) sin abortar
la proyección.
Los contratos `/graph/*` de Power Automate **no** forman parte de este documento y no cambian.

---

## 1. Feature flags (servidor)

| Variable | Valores | Efecto |
|---|---|---|
| `UI_ENABLED` | `false`\|`true` | Si false, la UI no se monta (integración). En U1 el router solo existe en app de test. |
| `UI_WRITE_ENABLED` | `false`\|`true` | Mutaciones. **U1: siempre tratar como false; POST no implementados.** |
| `UI_AUTH_MODE` | `mock`\|`entra` | `api_key` **prohibido**. En **producción**, `mock` fuerza fail-closed (UI off). |
| `ACTIVE_ENVIRONMENT` | `sandbox`\|`production` | Fuente del indicador de ambiente. |

---

## 2. Ambiente

```http
GET /api/ui/v1/environment
```

```json
{
  "environment": "sandbox",
  "display_label": "SANDBOX / PRUEBAS",
  "ui_enabled": true,
  "ui_write_enabled": false,
  "ui_auth_mode": "mock"
}
```

| `environment` | `display_label` |
|---|---|
| `sandbox` | `SANDBOX / PRUEBAS` |
| `production` | `PRODUCCIÓN` |

El frontend **no** compila una constante de ambiente; siempre lee este endpoint (o el campo `environment` embebido en otras respuestas).

---

## 3. Estados

### 3.1 Estado operativo general (`operational_status`)

Derivado por el backend (no inventar en el front):

```text
NUEVO
GENERANDO
EN_REVISION
FINALIZANDO
NOTIFICANDO
ESPERANDO_SOPORTES
CONSOLIDANDO
VALIDANDO_AMORTIZACION
LISTO_PARA_APLICAR
APLICANDO
COMPLETADO
FINALIZADO_PARCIALMENTE
ERROR_RECUPERABLE
CORRECCION_REQUERIDA
REVISION_MANUAL
CANCELADO
DESCONOCIDO
```

### 3.2 Estado por etapa (`steps[].status`)

```text
not_started
in_progress
completed
failed_retryable
failed_business
blocked
skipped
partial
```

Etapas fijas (orden):

```text
generate | review | finalize | notify | merge | dry_run | apply
```

### 3.3 Estado de negocio por pago/crédito (`items[].business_status`)

**Canónicos de Excel** (`EstadoPago` en `review_schema.py` — vigentes):

```text
NORMAL | ATRASADO | ADELANTADO | REVISION_MANUAL
```

**Operativos propios de la proyección UI** (no son dropdown del Excel):

```text
ESPERANDO_IBR | ESPERANDO_SOPORTE | COMPLETADO | ERROR_CORREGIBLE | DESCONOCIDO
```

**`INCOMPLETO`:** **retirado** del flujo operativo (no forma parte de `EstadoPago.ALLOWED`).
Finalize rechaza filas con ese texto (`INCOMPLETO_NOT_SUPPORTED`). Históricos antiguos
pueden aún contener el literal en lectura Notify/Merge, pero la UI **no** lo expone
como estado canónico. Ver `docs/implementation/operator-web-ui.md` § hotfix U1.

> Nota: `DECISIONES_TECNICAS_CERRADAS.md` aún lista `INCOMPLETO` como ejemplo
> histórico de diseño; no se edita en esta rama. La fuente de verdad de código es
> `review_schema.EstadoPago`.

---

## 4. DTOs principales

### 4.1 `UiLink`

```json
{
  "rel": "review_excel",
  "label": "Abrir Excel de revisión",
  "path": "…/01 REVISION/validacion_pagos_….xlsx",
  "web_url": "https://…",
  "open_mode": "sharepoint"
}
```

`web_url` puede ser `null` si solo hay path relativo.

### 4.2 `UiError`

```json
{
  "stage": "notify",
  "severity": "recoverable",
  "error_code": "ERROR_NOTIFY",
  "user_message": "No se pudo enviar el correo…",
  "next_action": "Reintentar el envío de correo…",
  "payment_id": null,
  "client_name": null,
  "credit": null,
  "link": null
}
```

`severity`: `info` | `warning` | `recoverable` | `business` | `fatal`

### 4.3 `UiStepState`

```json
{
  "name": "notify",
  "status": "failed_retryable",
  "updated_at": null,
  "summary": "Correo no enviado; Finalize conservado.",
  "can_retry": true,
  "retry_action": "retry_notify"
}
```

En U1 `can_retry` / `retry_action` son informativos; **no hay POST**.

### 4.4 `UiActiveJob`

```json
{
  "job_id": "uuid",
  "type": "generate",
  "status": "running",
  "store": "job_manager",
  "poll_path_graph": "/graph/sharepoint/payment-validation/jobs/{job_id}",
  "poll_path_ui": "/api/ui/v1/jobs/{job_id}",
  "started_at": "…",
  "progress": null
}
```

`store`: `job_manager` | `sharepoint_memory` | `none`

### 4.5 `UiProcessItem` (pago/crédito)

```json
{
  "payment_id": "1",
  "client_name": "ACME",
  "credit": "CREDITO # 12",
  "application_type": "PAGO",
  "business_status": "NORMAL",
  "stage_hint": "review",
  "observation": null,
  "links": []
}
```

U1 puede devolver `items: []` si aún no se lee el Excel de revisión (lectura Excel = UI v2).

### 4.6 `UiProcessDetail`

```json
{
  "process_key": "payment-validation|banco_bancolombia|2026-07-29|uuid",
  "process_id": "uuid",
  "bank_code": "banco_bancolombia",
  "bank_name": "Bancolombia",
  "process_date": "2026-07-29",
  "environment": "sandbox",
  "operational_status": "EN_REVISION",
  "control_estado_proceso": "REVISION_CREADA",
  "is_active": true,
  "steps": [ /* UiStepState × 7 */ ],
  "items": [],
  "active_job": null,
  "attempts": [],
  "next_actions": [
    {
      "code": "open_review_excel",
      "label": "Abrir Excel de revisión en SharePoint",
      "enabled": true,
      "reason": null
    }
  ],
  "errors": [],
  "links": [],
  "files": {
    "validation_file_path": "…",
    "historical_file_path": null,
    "secretary_file_path": null,
    "email_pdf_path": null,
    "merge_manifest_path": null,
    "control_file_path": "…",
    "execution_log_path": null
  },
  "idempotency": {
    "notify_idempotency_key": null,
    "merge_idempotency_key": null,
    "apply_idempotency_key": null
  },
  "trigger_source": null,
  "requested_by": null
}
```

`trigger_source` / `requested_by`: **opcionales**; `null` en datos legacy. No exigen columnas en Control.

### 4.7 `UiProcessSummary` (listado)

Subconjunto: `process_key`, `bank_code`, `process_date`, `environment`, `operational_status`, `control_estado_proceso`, `is_active`, resumen de errores, `next_actions` cortas.

### 4.8 `UiJobView`

```json
{
  "job_id": "uuid",
  "type": "generate",
  "status": "completed",
  "store": "job_manager",
  "process_key": null,
  "bank_code": null,
  "environment": "sandbox",
  "created_at": null,
  "started_at": null,
  "finished_at": null,
  "result_summary": null,
  "error": null,
  "raw_available": true
}
```

---

## 5. Endpoints U1 (solo GET)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/ui/v1/environment` | Ambiente + flags |
| GET | `/api/ui/v1/processes` | Listado (`bank_code` query opcional) |
| GET | `/api/ui/v1/processes/{process_key}` | Detalle proyección |
| GET | `/api/ui/v1/jobs/{job_id}` | Vista job (JobManager o memoria Notify/Merge si vivo) |

### Query `GET /processes`

- `bank_code` opcional: `banco_bogota` \| `banco_bancolombia`
- Sin banco: intenta ambos controles conocidos.

### Errores HTTP UI

| Código | Cuándo |
|---|---|
| 401 | Bearer ausente/inválido |
| 403 | UI deshabilitada para el principal / modo write (futuro) |
| 404 | Proceso o job no encontrado; o `UI_ENABLED=false` en app montada |
| 409 | Reservado (conflicto eTag / already_running) — mutaciones futuras |
| 422 | Query inválida |

Cuerpo de error UI preferido:

```json
{
  "error_code": "process_not_found",
  "user_message": "No se encontró el proceso solicitado.",
  "next_action": "Verifique el process_key o el banco.",
  "severity": "business"
}
```

---

## 6. Mutaciones UI (U3)

| POST | Paso | Flag |
|---|---|---|
| `/api/ui/v1/processes/generate` | Generate | `UI_WRITE_ENABLED` |
| `/api/ui/v1/processes/finalize` | Finalize | `UI_FINALIZE_ENABLED` |
| `/api/ui/v1/processes/notify` | Notify | `UI_NOTIFY_ENABLED` + destinatarios sandbox |
| Merge / Dry-run / Apply | — | **fuera de U3-C1** |

### Notify (U3-C1)

Body cerrado (`extra=forbid`):

```json
{ "bank_code": "banco_bogota", "process_key": "payment-validation|…" }
```

No aceptar: `to`, `cc`, `historical_file_path`, `force`, paths SharePoint.

Bootstrap / proyección: `notify_test_recipients_configured` (bool) — **sin** direcciones.

En producción/sandbox, el cliente debe mostrar confirmación: environment, banco, ProcessKey, histórico, advertencia de correo real a destinatarios de prueba.

Idempotencia: reutilizar locks/control actuales; respuesta tipo `already_running` / reuse sin romper PA.

---

## 7. Reglas de proyección Notify / Merge

1. `notify.status=completed` solo si Control indica correo hecho de forma persistente  
   (p. ej. `NotifyIdempotencyKey` no vacío y/o `EmailPdfPath` y estado compatible).
2. `merge.status=completed` solo con manifest/idempotency/estado `CONSOLIDADO` (o equivalente).
3. `merge.status=partial` si `MERGE_PARCIAL` / manifest parcial.
4. Un job en memoria `running` puede rellenar `active_job` y `steps[].status=in_progress`, **sin** marcar completed al desaparecer el job tras recycle.
5. Tras recycle sin job: reconstruir desde Control; si `ERROR_NOTIFY` → `failed_retryable`.

---

## 8. Compatibilidad PA

- Mismos use cases internos (cuando existan writes).
- Mismos `process_key` / `job_id`.
- Polling Graph de PA intacto.
- UI puede exponer `poll_path_graph` informativo; el browser solo usa `poll_path_ui`.

---

## 9. Mocks frontend

Los mocks bajo `frontend/src/mocks/` deben cumplir este contrato (mismos campos y enums).
