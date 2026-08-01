# U4-RC-R3.3 — Continuidad de procesos, lenguaje humano y tema claro

Fecha: 2026-08-01 · Ámbito: **solo local** · Deploy: **0**

Conserva e integra R3.1 (CSRF) y R3.2 (proyección / `unavailable_banks` / `jobMessages`).

## Causa de los problemas observados

| # | Síntoma | Causa |
|---|---|---|
| 1 | Dashboard en 0 con Bancolombia activo | R3.2: proyección rota por `_validation_jobs` ausente + lista que silenciaba fallos |
| 2 | «Iniciar validación» habilitado con proceso activo | `/banks` solo miraba flags/lock; no leía Control |
| 3 | Mensajes técnicos `active_process_exists\|…` | SPA leía `error.message` técnico; labels caían al código crudo |
| 4 | No retomar / sin documentos claros | Detalle inalcanzable (1) + sin CTA «Retomar» + sección docs oculta si no había `web_url` |
| 5 | Botones técnicos | Labels «Consolidar soportes» / estados crudos |
| 6 | UI oscura | Tokens dark-only en `styles.css` |

## Comportamiento anterior → corregido

| Antes | Ahora |
|---|---|
| Generate siempre ofrecido si flags OK | Por banco: `generate` / `resume` / `retry_read` según Control |
| Lista vacía disfrazaba fallos | `unavailable_banks` + «Volver a intentar» (solo lectura) |
| Código técnico en panel de progreso | `user_message` → `error.user_message` → respaldo humano (nunca pipes/códigos) |
| Sin Retomar | «Retomar proceso» → mismo detalle que un proceso nuevo |
| Docs solo si había links con URL | Sección siempre visible; archivos sin URL = «no disponible»; «Actualizar documentos» reconsulta GET |
| Tema oscuro | Tema claro: fondo gris, tarjetas blancas, azul corporativo |

## Archivos modificados (principales)

**Backend**
- `app/application/ui/generate_capabilities.py` — gates + `dashboard_primary_action`
- `app/adapters/primary/http/ui/router_v1.py` — `/banks` lee Control (RO)
- `app/application/ui/schemas.py` — campos de continuidad en `UiBankCapabilities`
- `app/application/ui/process_projection.py` — guidance PENDIENTE_ASIENTOS, next_actions, labels de links
- `app/application/job_status_enrichment.py` — mensaje humano `active_process_exists`
- (previos R3.2) `job_read.py`, lista `unavailable_banks`

**Frontend**
- `frontend/src/copy/labels.ts` — catálogo humano + respaldo sin códigos
- `frontend/src/domain/jobMessages.ts` — prioridad + rechazo técnico
- `frontend/src/pages/DashboardPage.tsx` — Retomar / Volver a intentar / contadores
- `frontend/src/pages/ProcessDetailPage.tsx` — continuidad, docs, refresh RO, CTAs
- `frontend/src/styles.css` — tema claro
- `frontend/src/api/client.ts` — tipos `UiBankCapabilities`

## Matriz estados → textos → botones → enlaces

| Estado control / operativo | Texto visible | Acción primaria dashboard | En detalle |
|---|---|---|---|
| Sin proceso (`VACIO`) | — | Iniciar validación | — |
| Control ilegible | aviso + Volver a intentar | Volver a intentar (GET) | — |
| `REVISION_CREADA` / EN_REVISION | Revisión pendiente | Retomar | Abrir revisión / Finalizar / Reintentar |
| Errores finalize | Requiere corrección | Retomar | Verificar nuevamente + docs |
| `FINALIZADO` | Pendiente de envío | Retomar | Enviar validación |
| `PENDIENTE_ASIENTOS` / ESPERANDO_SOPORTES | **Esperando documentos contables** | Retomar | Ver archivos · Actualizar documentos · Generar PDF consolidado (si Merge allowed) |
| Merge parcial/fallido | PDF consolidado parcial / requiere atención | Retomar | Revisar docs + reintentar Merge |
| `CONSOLIDADO` | Listo / PDF listo | Retomar | Procesar amortización (no Merge como primario) |
| Apply parcial/fallido | Amortización parcial | Retomar | Corregir + reintentar |
| Completado | Completado | Retomar (consulta) | Documentos / resultados |

## Mensajes humanizados (ejemplos)

- `active_process_exists` → «Ya existe una validación activa… Abra el proceso existente…»
- Control ilegible → «No pudimos leer el estado… Vuelva a intentar…»
- Merge not ready (vía readiness) → mensaje del backend + «Actualizar documentos»
- Códigos / pipes / JSON → **nunca** al operador; solo Detalles técnicos

## Recursos recuperables (solo lectura Graph)

Al abrir detalle se resuelven `webUrl` desde rutas del Control:

- Archivo de revisión · Histórico · Asientos pendientes · Correo enviado · PDF consolidado/manifiesto · Control · Registro de ejecución

Si un recurso no resuelve: se muestra «(no disponible)» sin ocultar el resto. «Actualizar documentos» = `GET /processes/{key}` (reconsulta SharePoint; **0 escrituras**).

## Diseño visual

- Fondo `#f4f6f8`, paneles blancos, texto `#1a2332`
- Acento azul `#1f5f9e`
- Éxito / aviso / error suaves
- Botón primario azul sólido; secundario borde gris
- Sin selector de tema; claro por defecto

## Tests

- pytest: **1327 passed, 1 skipped**
- vitest: **81 passed** (17 files)
- `tsc --noEmit`: OK
- `npm run build`: bundle `index-DONiLLTw.js` + `index-CVEikifc.css`

Nuevos / actualizados: `test_ui_generate_capabilities_continuity.py`, `test_ui_banks_continuity.py`, `DashboardPage.continuity.test.tsx`, `jobMessages.test.ts`, `labels.test.ts`, etc.

## Confirmaciones

| Control | Valor |
|---|---|
| Graph mutable | **0** |
| SharePoint modificado | **0** |
| Deploy | **0** |
| Producción | **0** |
| Reglas financieras modificadas | **0** |
| Excel de control modificado | **0** |

Pendiente de autorización: empaquetado/deploy sandbox para validar continuidad live.
