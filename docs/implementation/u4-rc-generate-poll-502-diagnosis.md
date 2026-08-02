# Diagnóstico: «Error HTTP 502» al iniciar validación (Generate)

**Fecha:** 2026-08-01 (actualizado con causa verificada + evaluación propuesta dual)  
**Ambiente:** sandbox Azure · build `u4-rc-sandbox-ui-enabled-r33-37acf3e`  
**Job incidente:** `27291ce6-a3a0-4fd1-a80a-b0b8865a4c88`

## Qué vio el operador

1. Pulsó **Iniciar validación** (Bancolombia).
2. Tarjeta de seguimiento → «Con problemas» + **Error HTTP 502**.
3. Tras recargar: Generate había terminado bien.

## Hechos verificados (no hipótesis)

| Evidencia | Valor |
|---|---|
| Job `status` | **`completed`** (no falló Generate) |
| `elapsed_ms` | **50178** (~50 s de trabajo real) |
| `progress` | quedó en **`bank_rows_done: 0` / `total: 1`** todo el job |
| `heartbeat_at` | un solo beat a +31 s (`15:59:55`) |
| `trigger_source` | `web_ui` / `operador_hbi` |
| Resultado negocio | Excel creado, control `REVISION_CREADA`, `errores: 0` |
| Runtime Azure | `startup.sh` → **gunicorn `--workers 1`** + `UvicornWorker` |
| HTTP access logs | **no habilitados** en App Service (no hay línea `"502"` en LogFiles) |
| Docker platform log | corta a `20:04:43Z` (antes del Generate 20:59Z); no registra el poll |

### Por qué el 502 es del poll, no del negocio

1. El POST Generate responde **202** y el trabajo sigue en `BackgroundTasks` del **mismo** event loop del único worker.
2. Tras procesar la fila bancaria, Generate construye el Excel con **openpyxl síncrono** (`Workbook`…`save`) **sin** `await` — bloquea el loop.
3. El código ya documentaba el riesgo (`await asyncio.sleep(0)` en el loop de filas «para que /health y GET /jobs no se queden sin responder»), pero **no** cubría la fase de armado/serialización del Excel ni el parseo sync de PDF.
4. Con el loop congelado, Azure Front Door / ARR no obtiene respuesta a tiempo de `GET /api/ui/v1/jobs/{id}` → **502 Bad Gateway**.
5. El dashboard (antes del fix) marcaba `failed` al **primer** error de poll y **dejaba de sondear**, aunque el job siguiera y terminara `completed`.

### Prueba de mecanismo (local)

`tests/test_event_loop_job_poll_starvation.py`:

- Trabajo sync dentro de una task async **impide** que otra coroutine (simula GET /jobs) corra hasta que termine.
- Con `asyncio.to_thread`, el poll responde **antes** de que termine el trabajo pesado.

### Aclaración sobre locks

`JobManager.get_job` **no** adquiere `_job_lock`. El endpoint `/jobs/{id}` no «espera un lock de Generate».

Lo que sí ocurría: `set_job` hacía `write_text` **síncrono dentro** del `asyncio.Lock`, lo que congela el loop (y retiene el lock) durante I/O a disco. Eso agrava, pero el bloque dominante del incidente es openpyxl/PDF en Generate.

## Evaluación de la propuesta «dos niveles» (ChatGPT)

| Nivel | Propuesta | ¿Viable? | ¿Mejor que solo FE? |
|---|---|---|---|
| Frontend | Mantener sondeo ante 502/503/red | **Sí** | Necesario (UX): evita falso «Con problemas» |
| Backend | Generate no debe impedir responder `/jobs` | **Sí** | **Sí — es la causa raíz** |
| Backend | Offload Excel/PDF/sync fuera del event loop | **Sí** | Correcto en este runtime (1 worker) |
| Backend | «GET /jobs no debe esperar un bloqueo de Generate» | **Parcial** | El problema real es **starvation del event loop**, no lock en `get_job` |

**Veredicto:** la propuesta dual es **correcta y superior** al fix solo de frontend. El FE mitiga el síntoma; el BE evita el 502 en origen (también protege `/health` y evita recycles).

## Corrección aplicada (local; pendiente deploy)

1. **FE (ya):** reintentos de poll; no marcar `failed` por 502 aislado; copy humano.
2. **BE Generate:** `asyncio.to_thread` para:
   - `openpyxl.load_workbook` del Excel banco
   - parseo PDF `extract_fecha_limite_pago_from_pdf`
   - lectura tabla amortización `_extract_pending_installment`
   - construcción+`save` del Excel de revisión (`_build_review_workbook_bytes`)
3. **BE JobManager:** persistencia a disco de `set_job` vía `to_thread` fuera del lock.

## Evidencia local

`D:\CMC\HBI_Capital\_work\u4_rc_r33_continuity\diagnose_502\`
