# Decisiones técnicas CERRADAS — índice extractos + UI (pre-implementación)

> **SUPERSEDIDO (Bloque C / refactor v3, 2026-08):** el runtime de
> **extract-index** fue **eliminado** por completo (router
> `/extract-index/admin/*`, servicios, flags `EXTRACT_INDEX_*`, tests y
> fake Graph). Este archivo queda como **auditoría histórica** de la
> decisión original; **no** reimplementar ni reintroducir flags/routers.
> Flujo de producto vigente: Generate → Excel **v3** (`Aplicacion_Pagos` /
> `_Meta`) → Finalize / Notify / Merge / Amortización vía UI.

**Estado histórico:** acordado con el negocio (2026-07-29); implementación
posterior retirada del árbol.
**Audiencia:** ChatGPT / Cursor / desarrolladores (solo lectura).

Las secciones siguientes documentan **qué se iba a implementar** entonces.
Prueba de capacidad Graph (crear lista): ver §11 y resultado en vivo.

---

## 1. Reglas no negociables

1. **SharePoint = fuente única de verdad** (clientes, créditos, extractos, Excels, resultados financieros).
2. **No** PostgreSQL / Azure SQL / SQLite / JSON suelto / Excel como almacén del índice.
3. El índice es **caché derivada y reconstruible**; si falla → Generate usa lógica V2 actual.
4. **Power Automate** conserva rutas, bodies, respuestas, `job_id`, polling y `X-API-Key` **sin cambios**.
5. Un solo App Service; **1 worker** Gunicorn (no subir workers para “ir más rápido”).
6. Entorno actual de trabajo: **sandbox** (`ACTIVE_ENVIRONMENT=sandbox`).

---

## 2. Dónde vive el índice (ubicación acordada)

```text
Sitio: Operaciones HBI Capital
       (gecolsacat.sharepoint.com/sites/OperacionesHBICapital)

├── Documentos / INFORMACION CREDITOS-CLIENTES / …
│     (igual que hoy: clientes, banco, validación)
│
└── Listas del sitio (Contenido del sitio) — técnicas, no operativas
      ├── INDICE_EXTRACTOS
      └── CONTROL_INDICE_EXTRACTOS
```

- **No** dentro de carpetas de clientes, `01 REVISION`, `01 CARGA…`, ni Contabilidad.
- Permisos: app Graph + admins/devs; **secretaria no las usa** en el día a día.
- Columna `ENVIRONMENT` = `sandbox` | `production` (mismos nombres de lista en ambos overlays).

**Bloqueo descubierto (2026-07-29):** la app Graph actual recibe `403 accessDenied` al
`POST /sites/{id}/lists`. Hasta ampliar permisos Entra **o** crear las dos listas a mano,
la implementación del índice trabajará sobre listas **preexistentes** (CRUD de ítems), no
sobre creación automática del contenedor.

---

## 3. Qué es el índice (tipo de “archivo”)

| Pregunta | Decisión |
|---|---|
| ¿Excel? | **No** |
| ¿JSON en carpeta? | **No** |
| ¿Qué entonces? | **Listas de SharePoint** (tablas del sitio) |

### `INDICE_EXTRACTOS`
Una fila = un PDF candidato de la lógica V2.

Campos clave: `ENVIRONMENT`, `CREDIT_KEY`, `DOC_KEY`, `DRIVE_ID`, `ITEM_ID`, carpetas, nombre, ruta, `UBICACION`, `CTAG`, `ETAG`, tamaño, fechas, `ESTADO_PARSEO`, `VERSION_PARSER`, `FECHA_LIMITE`, valor opcional, `HASH_CONTENIDO`, `ELIMINADO`, `PARSE_ERROR`, `ULTIMA_REVISION`.

- `CREDIT_KEY` = `environment|drive_id|credit_folder_item_id` (**columna indexada**).
- `DOC_KEY` = `environment|drive_id|item_id` (identidad del documento).
- **No** usar “seleccionado” como verdad financiera: Generate **vuelve a aplicar V2** con el contexto del pago; el índice solo guarda metadata + parse.

### `CONTROL_INDICE_EXTRACTOS`
Control del barrido inicial (reanudable): estado, versiones, totales, último cliente, heartbeats, errores, cancelación.

---

## 4. Cómo se acelera Generate (sin romper lo actual)

Feature flag:

```text
EXTRACT_INDEX_MODE = off | shadow | active
```

| Modo | Comportamiento |
|---|---|
| `off` | Igual que hoy |
| `shadow` | Resultado oficial = V2; índice solo compara/loguea |
| `active` | Usa índice + refresh selectivo; **fallback V2 por crédito** si falla |

Generate del día:
1. Lee Excel banco (SharePoint).
2. Deduplica clientes/créditos del lote.
3. Consulta índice por `CREDIT_KEY`.
4. Lista **solo** metadata de esos créditos.
5. Compara `item_id` + `cTag`/`eTag`.
6. Descarga/parsea solo nuevos o cambiados.
7. Aplica selección V2.
8. Publica Excel revisión (igual que hoy).

**Baseline de medición:** ~8 min Generate limpio / 43 filas (no los 77 min con reciclados).

---

## 5. Barrido inicial (noche / admin) — **por chunks, no un job de horas**

**Prohibido** en el único worker del App Service:

```text
POST bootstrap → 300 clientes → running varias horas
```

Eso competiría con Power Automate (polling), la UI futura, Graph/CPU y los recycles.

**Obligatorio:** campaña cooperativa fragmentada:

```text
Iniciar campaña
  → procesar bloque pequeño (N clientes/créditos O máx. X minutos)
  → checkpoint en CONTROL_INDICE_EXTRACTOS
  → la ejecución HTTP/job TERMINA
  → siguiente bloque (nueva llamada / nuevo job corto)
  → repetir hasta completar
```

Config sugerida inicial (medir y ajustar):

```text
BOOTSTRAP_MAX_CLIENTS_PER_CHUNK=3
BOOTSTRAP_MAX_SECONDS_PER_CHUNK=180
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false|true
```

Reglas:
- Checkpoint **por crédito confirmado** (no solo al final del chunk).
- Pausable / cancelable / reanudable; recycle ≠ empezar de cero.
- **No** bucle infinito que encadene chunks dentro del mismo proceso.
- Cada chunk devuelve estado + `continuation_required`.
- Lock por crédito vs Generate: si Generate usa el crédito → omitir o cortar chunk limpio.
- Endpoint admin con `X-API-Key` + flag bootstrap.
- Métricas mínimas: `campaign_id`, `chunk_id`, clientes/créditos, pdfs listados/descargados/parseados, errores, checkpoint, `elapsed_ms`, `continuation_required`.
- Medir impacto en `/health` y polling PA durante un chunk.

### Orquestación de chunks (quién pide el siguiente)

Cada chunk **termina** y puede devolver `continuation_required=true`.

En Fase 1 el siguiente chunk se inicia **explícitamente**:
- endpoint admin / comando operativo («Procesar siguiente bloque»), o
- más adelante: scheduler o sección admin de la UI con `campaign_id`.

**Prohibido:** recursión interna, bucle infinito o autoencadenamiento de chunks en el mismo worker.  
**No** mezclar este control con el flujo diario de Power Automate.

Endpoint/estado de campaña debe exponer: campaña activa, progreso, checkpoint, chunk actual, heartbeat, errores, `continuation_required`, `paused`, `cancellation_requested`, `completed`.

### Reglas del modo `shadow`

`shadow` es **validación**, no modo operativo permanente.

Debe poder limitarse a: sandbox · bancos · fechas · máx. créditos · muestra/%.

No ejecutar a la vez: bootstrap de chunks + lote grande en shadow + estrés UI.

Orden de integración: `EXTRACT_INDEX_MODE=off` → shadow controlado (lotes pequeños) → `active`.

Registrar por crédito: item_id V2 vs índice, `fecha_limite`, motivo, divergencia, tiempo extra de shadow.

### Estrategia sandbox vs índice productivo (cerrada)

**Probar el código del índice ≠ poblar el índice productivo.**

| Etapa | Ambiente | Qué se hace |
|---|---|---|
| A — desarrollo técnico | sandbox | Código, chunks, locks, fallback, métricas (carpetas atrasadas OK) |
| B — preflight | production | Solo lectura documental; `EXTRACT_INDEX_MODE=off`; bootstrap `false` |
| C — bootstrap productivo | production | Lee árbol real; escribe **solo** filas en las 2 listas; índice sigue `off` |
| D — validación | production | `shadow` muestra pequeña |
| E — activación | production | `active` + fallback V2 por crédito |

Sandbox operativo normal: `EXTRACT_INDEX_MODE=off` (ignora filas `ENVIRONMENT=production`).  
El índice productivo puede existir en las mismas listas sin afectar Generate en sandbox: **toda consulta filtra por `ENVIRONMENT` + `DRIVE_ID` + `CREDIT_KEY`/`DOC_KEY`**.

### Protección absoluta del árbol documental de producción

Durante bootstrap/refresh productivo están permitidas sobre el drive Documentos **solo**:

- resolver sitio/drive · listar carpetas/archivos · leer metadata · **descargar** PDFs candidatos para parsear · leer Excels si hace falta.

**Prohibido** sobre el drive productivo: crear/reemplazar/actualizar contenido, crear carpetas, mover, renombrar, copiar, eliminar, modificar permisos/metadata de documentos, `ensure-asientos-contables-folders`, cualquier upload/mutación documental.

**Únicas escrituras permitidas:** ítems en `INDICE_EXTRACTOS` y `CONTROL_INDICE_EXTRACTOS` (con `ENVIRONMENT=production`).

**Barrera fail-closed:** el bootstrap usa un puerto/repositorio de **solo lectura** para el árbol documental (sin upload/delete/move/rename/create-folder). Si intenta POST/PUT/PATCH/DELETE sobre `/drives/...` de documentos → abortar chunk, registrar violación. POST/PATCH/DELETE solo contra endpoints de ítems de las dos listas.

Bootstrap productivo **nunca** arranca solo por desplegar código: requiere `EXTRACT_INDEX_BOOTSTRAP_ENABLED=true` + invocación admin explícita, preferible fuera de horario, chunk pequeño primero.

---

## 6. UI y Power Automate (convivencia)

```text
PA  → /graph/*     + X-API-Key     (intactos)
UI  → /api/ui/v1/* + Entra Bearer
SPA → servida en /app (mismo App Service, sin Node en Azure)
```

Mismos casos de uso internos. Anti-doble ejecución: `process_key` + `trigger_source` (`power_automate` | `web_ui` | `admin`) + lock actual Generate/Finalize.

**Frontera con rendimiento:**

```text
Rendimiento cambia CÓMO Generate encuentra extractos.
UI consume QUÉ (contrato exterior) devuelve el proceso.
```

La UI **no** debe saber si el extracto salió de V2, índice caliente, fallback o bootstrap parcial.  
`INDICE_EXTRACTOS` **no** es fuente del estado de UI.

### Visión de producto de la UI (obligatoria)

La UI **no** debe imitar visualmente los correos. Debe **cumplir la misma función operativa** que hoy hacen correos + botones/URLs de Power Automate, pero en un solo lugar usable.

Hoy el operador:
1. Lanza Flujo 1 desde `EMPEZAR VALIDACION.url`
2. Espera correo → abre Excel → marca Validar/Procesar
3. Lanza Flujo 2 desde botón del correo
4. Sube asientos → Flujo 3 desde correo
5. Revisa consolidados → Flujo 4 desde correo
6. Ante error: lee correo, corrige, **reintenta** (la API ya es idempotente)

La UI centraliza ese ciclo (dashboard, progreso, reintento por etapa, errores accionables, links SharePoint).

**Requisitos duros:** orden de pasos · reintentos · corrección guiada · **idempotencia** (ProcessKey, jobs, already_*, locks, anti-doble canal).

Referencia: `MANUAL_USUARIO.md`.

### Ramificaciones de negocio (proceso ≠ un solo “fallido”)

La UI debe manejar **dos niveles**:

1. Estado general del proceso (por etapa: Generate, Review, Finalize, Notify, Merge, Dry-run, Apply).
2. Estado **individual** por pago/crédito.

No asumir que todas las filas llegan a Notify/Merge/Amortización el mismo día.

Estados de negocio a contemplar (derivados por la **API**, no inventados en el frontend), p. ej.:

```text
NORMAL | ATRASADO | INCOMPLETO | ADELANTADO | REVISION_MANUAL
ESPERANDO_IBR | ESPERANDO_SOPORTE | COMPLETADO | ERROR_CORREGIBLE
```

- `REVISION_MANUAL` bloquea Finalize (como hoy).
- `ADELANTADO` puede quedar bien aplicado con acciones futuras (IBR/fecha) → **no** es error técnico del proceso.
- Un proceso puede estar `FINALIZADO_PARCIALMENTE` con algunos créditos `ESPERANDO_IBR`.

Fuentes: `review_schema`, control, `pagos_adelantados.xlsx`, resultados reales de use cases.

### Mensajes operativos (semántica de los correos)

Por error/resultado parcial la API/UI deben exponer (no solo HTTP 500):

- etapa · pago/crédito · `user_message` · `next_action` · `severity`
- código técnico (soporte) · link a archivo/carpeta · acción habilitada tras corregir
- qué quedó completo vs pendiente

Ejemplos: Finalize OK + Notify fail → reintentar solo Notify; Merge parcial → PDFs hechos + pendientes + reintento solo pendientes.

### Proyección del proceso (no nueva verdad)

Servicio tipo `PaymentProcessProjectionService` agrega **los almacenes/jobs reales
de cada etapa** (no asumir un único JobManager), más control, revisión, histórico,
bitácora, manifest Merge, amortización →  
`GET /api/ui/v1/processes/{process_key}` con **estado por etapa** (Generate / Review / Finalize / Notify / Merge / Dry-run / Apply), no un solo `failed` global.

Ejemplo: Finalize `completed` + Notify `failed_retryable` → UI ofrece «Reintentar correo» **sin** re-ejecutar Finalize.  
Merge parcial → corregir solo soportes faltantes y reintentar Merge.

Contrato compartido versionado (antes de mocks libres):

```text
api-hbi-powerAutomate/docs/ui-api-contract-v1.md
```

### 6bis. Auditoría obligatoria del modelo de jobs (rama UI)

Informes históricos (p. ej. mayo) hablaban de JobManager para Generate/Finalize y
otro almacén para Notify/Merge/SharePoint. Puede estar desactualizado: **verificar
en el código actual**, no asumir un coordinador único.

Antes de diseñar idempotencia cruzada y `PaymentProcessProjectionService`, documentar
para cada etapa (Generate, Finalize, Notify, Merge, Dry-run, Apply):

1. Qué JobManager o almacén usa  
2. Dónde se persiste el job  
3. Qué endpoint consulta su estado  
4. Qué locks existen  
5. Si permite ejecuciones paralelas hoy  
6. Identificadores compartidos (`process_id`, `process_key`, `job_id`, `historical_file_path`, …)  
7. Qué ocurre tras recycle  
8. Si PA y UI pueden consultar el mismo job sin adaptar contrato  
9. Cambios mínimos para coordinación común  

**Prohibido** unificar/migrar job stores en `feature/operator-web-ui` sin autorización.  
Cambios compartidos → documentar para `integration/performance-and-ui`.

Matriz obligatoria en el primer entregable:

```text
Etapa | store actual | endpoint polling | lock | persistencia |
idempotencia actual | cambio requerido
```

### Revisión Excel — implementación progresiva

| Fase UI | Capacidad |
|---|---|
| **v1** | Estado, resumen, errores, abrir Excel en SharePoint, iniciar/reintentar pasos; **sin** editar Excel en el browser |
| **v2** | Lectura del Excel vía API (Distribución/Errores/Control); columnas/estados desde backend (`review_schema`), no duplicar en TS |
| **v3** | Edición controlada + mismo Excel + eTag → **409** si cambió en Excel Online |
| **v4** | UI como experiencia principal; Excel como respaldo/export |

Validación definitiva **siempre** en la API. No reemplazar `review_schema.py` en el frontend.

### Auth UI

```text
UI_ENABLED=false|true
UI_WRITE_ENABLED=false|true

UI_AUTH_MODE=mock
→ únicamente desarrollo local (pytest / SPA mocks).
→ prohibido en Azure / App Service.

UI_AUTH_MODE=entra
→ opción futura cuando existan permisos y App Registrations
  (JWKS, audience, SPA client, redirect URI).
→ no es requisito operativo con los permisos actuales.

UI_AUTH_MODE=local_session
→ solución operativa actual para sandbox y despliegue.
→ cookie HttpOnly `__Host-hbi_session` + hash PBKDF2 en servidor.
→ sin App Registrations Entra.
```

```text
UI_ENABLED=false
→ /graph/* y Power Automate funcionan exactamente como ahora
→ /api/ui/* y /app no se habilitan (404)

UI_ENABLED=true + UI_WRITE_ENABLED=false
→ SPA /app + /api/ui/v1/* en modo consulta (dashboard, estados, links)
→ auth: local_session (operativo) o entra (cuando esté disponible)
→ no Generate / Finalize / Notify / Merge / Dry-run / Apply

UI_ENABLED=true + UI_WRITE_ENABLED=true
→ acciones operativas (solo tras autorización explícita)
→ idempotencia, Origin/CSRF y validación de ambiente
```

**Prohibido de forma definitiva:**
- `UI_AUTH_MODE=api_key` o usar `API_HTTP_KEY` / `X-API-Key` en el navegador;
- secretos Graph, client secrets o Key Vault en la UI;
- Publish Profile como credencial de usuario de la SPA;
- contraseñas en texto plano (solo `UI_LOCAL_PASSWORD_HASH` PBKDF2 en runtime `.env`);
- tokens de sesión en `localStorage` / `sessionStorage`.

La autenticación UI (sesión o Entra) aplica **solo** a `/api/ui/*`.  
**Nunca** intercepta `/graph/*` (sigue con `X-API-Key` para Power Automate).  
Easy Auth del App Service permanece off. D1: `UI_ENABLED=false`. D2-LS2: consulta read-only con `local_session`.

### Separación de ambientes (UI)

- UI se desarrolla y valida primero **solo contra sandbox**.
- El frontend **no** hardcodea rutas SharePoint ni bases (`GRAPH_CLIENTS_BASE_PATH`, carpetas banco/revisión/histórico, site path).
- SPA solo llama rutas relativas `/api/ui/v1/*`.
- El backend resuelve datos con `ACTIVE_ENVIRONMENT` + overlay desplegado (`scripts/switch-env.ps1`).
- **Mismo código** sandbox y producción; solo cambia configuración/raíz. Sin lógica de negocio distinta por ambiente.
- API UI debe devolver el ambiente activo; SPA muestra indicador permanente **SANDBOX / PRODUCCIÓN** (valor del backend, no variable compilada).
- En producción, acciones mutantes: confirmación con banco, fecha, ambiente, proceso.
- Un solo App Service opera **un** ambiente a la vez (no sandbox y prod simultáneos sin segundo App Service / slot aislado).

### Despliegue y convivencia

Solo `integration/performance-and-ui` → sandbox → probar PA primero → UI → cruzado.

Pruebas mínimas de integración:
- PA inicia Generate → UI ve mismo job → no duplica
- UI inicia → PA no crea otro
- Bootstrap crédito A / Generate crédito B OK; mismo crédito → lock sin corrupción
- Finalize OK + Notify fail → reintento Notify solo
- Índice caído → V2 + contrato PA/UI intactos
- Excel eTag A→B → UI save → 409

---

## 7. Infra (evidencia)

| Dato | Valor |
|---|---|
| App | `app-hbiauto-prod-001` |
| SKU | Basic · 1 instancia |
| Workers | 1 · timeout 600 s |
| `/home` | CIFS persistente (jobs OK; índice = Listas SP) |

---

## 8. Fases de implementación (cuando se autorice código)

**Entrega A — rendimiento**  

```text
Instrumentación
→ validar esquema/columnas/índices de listas existentes
→ validar CRUD y consultas CREDIT_KEY / DOC_KEY
→ V2 compartida
→ bootstrap técnico sandbox
→ pruebas de seguridad y paridad sandbox
→ preflight productivo solo lectura
→ bootstrap productivo por chunks (EXTRACT_INDEX_MODE=off)
→ shadow productivo controlado
→ active productivo
→ prueba 50 pagos
```

**Dos bootstraps distintos (no confundir):**

| Tipo | Propósito | Datos |
|---|---|---|
| **Técnico (sandbox)** | Probar chunks, checkpoints, locks, reconciliación, eliminados/modificados, fallback, barrera read-only | Carpetas sandbox (atrasadas/artificiales). **No** es índice real. |
| **Productivo** | Poblar índice útil | Lee árbol prod; escribe **solo** listas técnicas; índice sigue `off`; admin explícito |

**No** crear contenedores de listas (ya existen; Graph devolverá 403).

Hasta implementar y probar barrera fail-closed + tests de cero mutaciones documentales + preflight + primer chunk mínimo revisado a mano: la arquitectura es segura **por diseño**, no aún verificada **en ejecución**.

**Entrega B — UI** (otra rama/worktree)  
SPA `/app`, Entra, dashboard, jobs; sin tocar Generate/índice.  
**Antes de diseñar proyección/idempotencia:** auditoría del modelo de jobs actual
(ver §6bis) — no asumir un único JobManager para todo el flujo.  
Desarrollo/validación contra **sandbox**; mismo código vía overlay para producción.

**Integración**  
Solo `integration/performance-and-ui` se despliega a Azure.  
Flags iniciales de deploy (sandbox):

```text
ACTIVE_ENVIRONMENT=sandbox
EXTRACT_INDEX_MODE=off
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false
UI_ENABLED=false
UI_WRITE_ENABLED=false
```

Después de verificar PA → `UI_ENABLED=true` + `UI_AUTH_MODE=entra` + `UI_WRITE_ENABLED=false`  
Después de UI consulta → `UI_WRITE_ENABLED=true`

Producción (mismo código, overlay `production`; bootstrap solo con autorización):

```text
ACTIVE_ENVIRONMENT=production
EXTRACT_INDEX_MODE=off          # durante bootstrap y hasta paridad
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false|true  # true solo en ventana controlada
UI_ENABLED=false                # hasta Entra + validación
UI_WRITE_ENABLED=false
```

Luego shadow controlado → `active`.

---

## 8bis. Gobernanza de ramas (anti-conflicto)

- `DECISIONES_TECNICAS_CERRADAS.md` = **solo lectura** en ambas feature branches.
- Documentar implementación en:
  - `api-hbi-powerAutomate/docs/implementation/extract-index-performance.md`
  - `api-hbi-powerAutomate/docs/implementation/operator-web-ui.md`
  - `api-hbi-powerAutomate/docs/ui-api-contract-v1.md`
- **No** modificar en feature branches (dejar nota para integración):
  `application.py`, `app_factory.py`, `requirements.txt`, `startup.sh`,
  `build-azure-package.ps1`, `config/environments/*.env`
- Esos cambios solo en `integration/performance-and-ui`.

**Primer entregable de cada conversación (antes de código):** plan con
rama/worktree, archivos a crear/modificar, contratos intactos, orden de commits,
tests por entrega, riesgos de integración. Luego autorizar código por fases.

| Rama | Scope |
|---|---|
| `feature/extract-index-performance` | índice, Generate, bootstrap, tests índice |
| `feature/operator-web-ui` | frontend, `/api/ui`, Entra, static `/app` |
| `integration/performance-and-ui` | merge + zip Azure |

No desplegar ramas sueltas de forma alternada sobre el mismo App Service.

---

## 10. Seguridad

- `API_HTTP_KEY` rotada (2026-07-29); actualizar PA desde `.secrets/API_HTTP_KEY.new`.
- No pegar secretos en chats/docs.

---

## 11. Prueba de capacidad: crear listas en SharePoint

**Fecha:** 2026-07-29  
**Método:** `POST /graph/diagnostics/list-capability-probe` (App Service con MI + Key Vault; flag `SHAREPOINT_LIST_CAPABILITY_PROBE_ENABLED`).  
**Lista temporal intentada:** `_HBI_CAPABILITY_TEST_LIST_DELETE_ME`  
**Sitio:** OperacionesHBICapital  

### Resultado (re-prueba 2026-07-29, listas creadas a mano)

```text
capability_result = PASS
mode              = item_crud_on_existing_lists
```

| Lista | Encontrada | Crear ítem | Leer | Borrar |
|---|---|---|---|---|
| `INDICE_EXTRACTOS` | sí | 201 | ok | ok |
| `CONTROL_INDICE_EXTRACTOS` | sí | 201 | ok | ok |

Ítems de prueba temporales eliminados. Las listas quedaron vacías otra vez.

**Conclusión de permisos (cerrada):**

```text
La API no crea contenedores de listas.
La API consume las listas técnicas preexistentes.
```

Puede localizarlas, crear/leer/borrar **ítems**. Eso basta para el índice.  
No reintentar creación automática de listas (403 `accessDenied`).

### Resultado anterior (antes de crear las listas)

```text
capability_result = FAIL_NO_CREATE_PERMISSION_OR_ERROR
phase             = create_list
http_status       = 403
Graph code        = accessDenied
```

**Conclusión de entonces:** no podía crear Listas (sigue válido).

Nota: ejecutar el mismo script desde la consola Kudu falla antes (Key Vault / MI no disponible en el proceso SCM). La prueba válida es la del worker de la API.

### Qué implica para la implementación

Opción recomendada (sin esperar rol nuevo):

1. Un admin crea **a mano** una sola vez en Contenido del sitio:
   - `INDICE_EXTRACTOS`
   - `CONTROL_INDICE_EXTRACTOS`
2. La API solo **lee/escribe ítems** de esas listas (permisos de biblioteca/lista existentes o `Sites.Selected` + grant a las listas).

Opción alternativa (Infra / Entra):

- Conceder a la app un permiso de aplicación capaz de crear listas, p. ej. `Sites.Manage.All` o `Sites.FullControl.All` (más amplio; requiere consentimiento admin), **o** un grant `Sites.Selected` con derecho a gestionar listas en Operaciones.
- Re-ejecutar el probe hasta `CAPABILITY_RESULT=PASS`.

**Flag del probe:** dejar en `false` salvo re-prueba puntual (`SHAREPOINT_LIST_CAPABILITY_PROBE_ENABLED`).

---

## 12. Qué NO se implementa todavía

- Lógica del índice dentro de Generate (hasta autorizar código en la rama de rendimiento).
- Bootstrap masivo no fragmentado / job de varias horas.
- UI en producción con `UI_ENABLED=true` hasta que Entra y la rama de integración lo autoricen.
- No se implementará creación automática de contenedores de listas.
  `INDICE_EXTRACTOS` y `CONTROL_INDICE_EXTRACTOS` ya existen y son administradas
  manualmente. La API únicamente valida su esquema y opera sus ítems.
