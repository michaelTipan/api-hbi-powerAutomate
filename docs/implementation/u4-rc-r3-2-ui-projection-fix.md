# U4-RC-R3.2 — Proyección UI rota y errores ilegibles (fix local, sin deploy)

Fecha: 2026-08-01 · Ambiente diagnosticado: Azure **sandbox** · Deploy: **no ejecutado**

## Síntoma reportado

En la UI live, tras pulsar “Iniciar validación” en Bancolombia:

- Panel de progreso: `Estado: Con problemas` +
  `active_process_exists|payment-validation|banco_bancolombia|2026-07-31|c217f87c-…|PENDIENTE_ASIENTOS`.
- Sin “Siguiente acción” y sin ningún botón de recuperación.
- Dashboard con `Todos (0)` y “No hay procesos en esta categoría”.

## Diagnóstico (solo lecturas)

Evidencia recogida en live con GET exclusivamente (login de operador, jobs,
`/api/ui/v1/processes`, `/api/ui/v1/banks`, y descarga read-only del Control vía
los endpoints de diagnóstico). No se ejecutó Generate/Finalize/Notify/Merge/
Amortización/Cancel, no se modificó SharePoint y no se enviaron correos.

1. **El bloqueo es legítimo.** El Control de Bancolombia mantiene activo el
   proceso `payment-validation|banco_bancolombia|2026-07-31|c217f87c-38cf-4853-a7e4-27304f2dca22`
   en `PENDIENTE_ASIENTOS`; Generate rechaza abrir otro (`active_process_exists`).
   El intento de cancelarlo de hoy (job `6758deec`) falló con
   `cancel_not_allowed|PENDIENTE_ASIENTOS`: cancelar solo aplica mientras el lote
   está en revisión.

2. **La UI mostraba el código técnico.** En el job `864b0afc` live,
   `user_message`/`next_action` de nivel superior venían `null` (el
   enriquecimiento solo los publica arriba en jobs `completed`), mientras
   `error.user_message` y `error.next_action` sí traían el texto al operador. La
   SPA leía solo el nivel superior y caía a `error.message`.

3. **Causa raíz del dashboard vacío y del 500 en el detalle.**
   `read_sharepoint_memory_job` resolvía el store legado así:

   ```python
   try:
       from app.adapters.primary.http.routers import sharepoint as sp
       lookup = lambda jid: sp._validation_jobs.get(jid)
   except Exception:
       return None
   ```

   El `try` cubre el import, no el acceso al atributo — y `_validation_jobs` ya
   no existe en ese módulo (se movió a `JobManager`). Por tanto, cualquier
   proceso con `NotifyJobId`/`MergeJobId` en Control provocaba `AttributeError`
   en `project_bank`, lo que daba:
   - `GET /api/ui/v1/processes/{key}` → 500 sin cuerpo,
   - `GET /api/ui/v1/processes` → 200 con `items: []`, porque el bucle hacía
     `except Exception: continue`.

   Reproducido en local con el Control y los 14 jobs reales descargados de
   sandbox: Bogotá (Control `VACIO`) proyecta bien y se omite por diseño;
   Bancolombia lanzaba el `AttributeError` y, con el store parcheado, proyecta a
   `ESPERANDO_SOPORTES` — la tarjeta que debía verse.

4. **Por eso no había botón:** las acciones de recuperación viven en el detalle
   del proceso, inalcanzable por (3).

## Cambios

| Archivo | Cambio |
|---|---|
| `app/application/ui/job_read.py` | Store legado resuelto con `getattr` (devuelve `None` si no existe) y lookup inyectado protegido con log; sin excepciones que rompan la proyección |
| `app/adapters/primary/http/ui/router_v1.py` | `list_processes` registra el fallo por banco y devuelve `unavailable_banks`; el detalle mapea el fallo inesperado a 503 `process_read_failed` con `user_message`/`next_action` |
| `app/application/ui/schemas.py` | `UiProcessListResponse.unavailable_banks` |
| `frontend/src/domain/jobMessages.ts` | Nuevo: orden de preferencia `user_message` → `error.user_message` → `error.message` |
| `frontend/src/pages/DashboardPage.tsx` | Usa el helper en el panel de progreso; aviso cuando hay bancos no disponibles |
| `frontend/src/domain/resolveDisplayedAttempt.ts` | Usa el helper para el job sondeado localmente |

## Verificación local

- `pytest -q`: **1320 pasados, 1 omitido**.
- `npx tsc --noEmit`: sin errores. `npx vitest run`: **77 pruebas** en verde.
- Nuevas pruebas:
  - `tests/test_ui_process_list_notify_job_regression.py` (store ausente, lookup
    inyectado que falla, `project_bank` con `NotifyJobId`, lista con el proceso,
    `unavailable_banks`, detalle 503 con mensaje).
  - `frontend/src/domain/jobMessages.test.ts`,
    `frontend/src/pages/DashboardPage.jobError.test.tsx`.

## Pendiente / no cubierto

- **Deploy a sandbox: no autorizado todavía.** El fix está solo en local.
- El mensaje de `active_process_exists` sigue sugiriendo “Cancelar proceso
  activo” también en estados donde el backend lo rechaza; y esa acción no está
  expuesta en `/api/ui/v1`. Mejora de UX propuesta y no implementada.
- `/api/ui/v1/banks` reporta `generate.allowed = true` sin consultar el Control,
  así que el botón se ve disponible y falla después.
