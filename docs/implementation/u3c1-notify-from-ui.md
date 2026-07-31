# U3-C1 — Notify desde la UI (sandbox) — implementación local

**Fecha:** 2026-07-30  
**Rama / worktree:** `integration/performance-and-ui` @ `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**Estado:** código + tests + ZIP Paso 1 (Notify **off**).  
**NO autorizado aún:** deploy U3-C1, `UI_NOTIFY_ENABLED=true`, correo real, Notify vía PA, Merge/Dry-run/Apply, push, merge a develop.

## Runtime ZIP Paso 1

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=false
UI_NOTIFY_SANDBOX_TO=            # vacío fail-closed
UI_NOTIFY_SANDBOX_CC=
UI_AUTH_MODE=local_session
EXTRACT_INDEX_MODE=off
Mocks off · Contabilidad off
```

Paquete: `azure-deploy-u3c1-notify-off.zip`  
SHA-256: `88995A6C995506F26EE1199CE03F2AA8BB4FCE302470E9775DA2F5278EA73502`  
HEAD: `0b78d22` (guardrail tests Notify).  
Obsoleto: `azure-deploy-u3c1-notify-off.OBSOLETE.zip` (`BB909956…`).

## Seguridad destinatarios sandbox

| Variable | Rol |
|----------|-----|
| `UI_NOTIFY_SANDBOX_TO` | Destinatarios de prueba (obligatorio no vacío para habilitar Notify UI) |
| `UI_NOTIFY_SANDBOX_CC` | CC opcional |

Reglas:

1. Default vacío → fail-closed.
2. En sandbox, aunque `UI_NOTIFY_ENABLED=true`, Notify UI no se habilita si TO está vacío.
3. `available_actions.notify.allowed=false` con razón: *No están configurados los destinatarios de prueba para Notify.*
4. El navegador **nunca** envía `to`/`cc`.
5. La SPA solo ve `notify_test_recipients_configured=true|false` (sin direcciones).
6. El backend inyecta TO/CC sandbox al use case existente.
7. Solo aplica a Notify iniciado por la UI en sandbox.
8. Contrato PA intacto (`to`/`cc` opcionales + CORREOS.xlsx).
9. Antes del Paso 2 el operador debe **aprobar explícitamente** los destinatarios de prueba.

## Flag `UI_NOTIFY_ENABLED`

- Ausente / inválido → `false`.
- Independiente de Generate y Finalize.
- No habilita Merge / Dry-run / Apply.
- Con `false`, el POST corta **antes** de locks, jobs, Graph y sendMail.

Gate efectivo: UI + write + notify + sandbox + destinatarios configurados + sesión operator + Origin + CSRF + JSON.

## NotifyQueueService

`app/application/services/notify_queue_service.py` — compartido por:

- `POST /graph/sharepoint/notify-validar-extractos-email`
- `POST /api/ui/v1/processes/notify`

Encapsula: `try_start_notify` → job → runner → `send_validar_extractos_notification_email` → terminal → `finish_notify` + auditoría best-effort.

## JobManager

Nuevos: `try_start_notify`, `finish_notify`, `is_notify_active`.  
Mutex cruzado Generate ↔ Finalize ↔ Notify. Un solo JobManager / store.

## Contrato PA (sin cambio de shape)

- 202: `status`, `job_id`, `estimated_processing_seconds`, `message`
- Poll: `GET …/notify-validar-extractos-email/jobs/{job_id}` (lee JobManager)
- Body opcional: `historical_file_path`, `bank_code`, `to`, `cc`
- Auth: X-API-Key

## Endpoint UI

`POST /api/ui/v1/processes/notify` body cerrado:

```json
{ "bank_code": "banco_bogota", "process_key": "…" }
```

`extra=forbid`. Respuesta 202 con `accepted`, `action`, `bank_code`, `process_key`, `job_id`, `status`, `poll_url`.

## Idempotencia

`already_notified` → job `completed` / `SKIPPED_IDEMPOTENT` (sin segundo correo ni PDF).

## Frontend

Acción «Enviar notificación», advertencia de correo real, modal, sin emails completos, sin Merge/Dry-run/Apply.

## Plan Paso 2 (NO ejecutar)

1. Aprobar destinatarios `UI_NOTIFY_SANDBOX_TO` / `CC`.
2. Autorizar deploy + `UI_NOTIFY_ENABLED=true`.
3. Smoke Notify UI en sandbox (correo real a prueba).
4. Verificar control → `PENDIENTE_ASIENTOS` + PDF.
5. Reintento → `already_notified` sin segundo envío.

## ZIP

Ver `PROJECT_CONTEXT.md` / entregable de sesión para SHA-256 de `azure-deploy-u3c1-notify-off.zip`.
