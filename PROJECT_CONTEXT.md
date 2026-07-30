# PROJECT_CONTEXT — API HBI Capital (automatización de validación de pagos)

Fuente de verdad del estado del proyecto. Actualizar tras cada cambio significativo.

## Documentación para operadores

- **Manual de usuario:** `../MANUAL_USUARIO.md` (raíz `HBI_Capital`). Lenguaje no técnico; flujo por correos + `EMPEZAR VALIDACION`; tipos `PAGO` / `PAGO Y ABONO CAPITAL` / `ABONO CAPITAL` / `ABONO MORA`; Revisión vacía antes del Flujo 1; Notify dentro del Flujo 2.

## Stack

- **API**: FastAPI + Pydantic. Servida con Gunicorn + `UvicornWorker`, **1 worker**.
- **Integración**: Microsoft Graph API vía HTTP (`client_credentials`), sin SDK.
- **Documentos**: openpyxl (Excel), pypdf (unión de PDF), reportlab.
- **Configuración**: variables de entorno leídas de un `.env` en la raíz (`load_dotenv`).
- **Pruebas**: pytest con dobles en memoria de Graph. No hay `conftest.py` global.
- **Zona horaria operativa**: `America/Bogota` (Colombia, UTC-5, sin DST). Ver sección siguiente.

## Zona horaria (Colombia)

La API corre en Azure (UTC). **Toda marca de tiempo visible** al operador, a la
secretaría o al desarrollador debe generarse en hora de Colombia:

| Uso | Helper (`app/application/services/colombia_time.py`) |
|---|---|
| ISO con offset `-05:00` (jobs, control `LastUpdatedAt*`, bitácora amort) | `now_colombia_iso()` / alias histórico `utc_now_iso()` |
| Excel legible (`Fecha procesamiento`, CreatedAt/UpdatedAt follow-up) | `now_colombia_wall_clock()` → `YYYY-MM-DD HH:MM:SS` |
| `process_date` por defecto / ProcessKey fallback | `today_colombia()` / `today_colombia_iso()` |
| Logs `%(asctime)s` | `logging_config` convierte a Bogotá |

**No se convierten** fechas de negocio que ya llegan como calendario (`fecha_banco`,
`fecha_limite`, fechas leídas del Excel/PDF): son fechas colombianas de origen.

Dependencia `tzdata` en `requirements.txt` para que `ZoneInfo("America/Bogota")`
funcione en Windows y en contenedores sin zona IANA del sistema.

## Arquitectura

Hexagonal por capas:

- `app/adapters/primary/http/` — routers, dependencias, fábrica de la app.
- `app/adapters/secondary/` — cliente de Graph y proveedor de credenciales.
- `app/application/` — casos de uso, servicios y configuración.
- `app/domain/` — puertos, entidades y excepciones.

Los trabajos largos se ejecutan en el proceso y se consultan por `job_id`. El estado se
persiste en disco (`PAYMENT_VALIDATION_JOBS_DIR` o `wwwroot/.payment_validation_jobs`)
para sobrevivir reciclajes: al arrancar, jobs `queued`/`running` huérfanos pasan a
`failed` con `JobInterruptedByProcessRestart`. Generate emite heartbeat (`updated_at`)
cada ~30s. **Un solo worker sigue siendo obligatorio** (el BackgroundTask no migra).

## Credenciales

Dos fuentes, seleccionadas con `GRAPH_CREDENTIAL_SOURCE`:

- `env` (defecto): `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET`.
- `key_vault`: los tres secretos se leen de Azure Key Vault con la identidad
  administrada del App Service. Es el modo de producción, porque los valores en texto
  plano no se entregan al equipo de desarrollo.

**Regla no negociable**: la lectura es perezosa. Ocurre en la primera petición real a
Graph, nunca al importar módulos ni al construir la app. Así `/health` responde 200 aun
con la configuración incompleta, y un fallo de Key Vault no impide el arranque. El token
de acceso se cachea en memoria hasta cinco minutos antes de vencer.

## SharePoint: dos sitios

| Contexto | Sitio | Contenido |
|---|---|---|
| Operaciones | `sites/OperacionesHBICapital` | Todo el proceso: bancos, clientes, control, revisión, histórico, trazabilidad, correos |
| Contabilidad | `sites/HBICapitalContabilidad` | Solo el destino del PDF consolidado |

El sitio se resuelve por `hostname` + ruta (`/sites/{host}:/sites/{nombre}`), que es
determinista. El mecanismo antiguo por `?search=` se conserva como respaldo para el
ambiente de pruebas y se usa solo cuando las variables nuevas no están definidas.

El sitio de Contabilidad es **opcional**: si no está configurado, el consolidado se
sigue guardando en Operaciones, igual que antes.

### Estructura en Operaciones (sandbox Comware, 2026-07-29)

Raíz sandbox: \…/02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES/(\GRAPH_CLIENTS_BASE_PATH\). Clientes, carga banco y validación viven al mismo nivel.

\02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES/
├── 01 CARGA TRANSACCIONES BANCO/     BANCO_BOGOTA.xlsx, BANCO_BANCOLOMBIA.xlsx
├── 02 VALIDACION PAGOS/
│   ├── 01 REVISION/                  validacion_pagos_*.xlsx del día
│   ├── 02 CONTROL OPERATIVO/         CORREOS, IBR_DIARIO, pagos_adelantados
│   ├── 03 HISTORICO/                 cartera_validada por fecha
│   ├── 04 CORREOS ENVIADOS/          PDF de cada correo enviado
│   ├── 90 ACCESO RESTRINGIDO/
│   │   ├── 01 TRAZABILIDAD/          manifiestos merge
│   │   ├── 02 LOGS/                  bitácora JSON (EXECUTION_RUN_LOG_ENABLED)
│   │   │   └── YYYY-MM-DD/execution_log_{banco}_{…}_{step}_{RESULT}_{id8}.json
│   │   └── 03 CONTROL TECNICO/       control_proceso_validacion_pagos_banco_*.xlsx
│   └── 99 SOPORTES DE PAGO CONSOLIDADOS - PRUEBAS/   Merge (Contabilidad off)
└── <cliente>/                        créditos + ASIENTOS CONTABLES CRED {n} + EXTRACTOS
\
En producción real las carpetas cambiarán de nuevo; no apuntar a rutas productivas
mientras el sandbox siga activo. No existe carpeta de errores: el código no la referencia.

### Bitácora de ejecución (\execution-run-log\)

- **Flag**: \EXECUTION_RUN_LOG_ENABLED\ (default \alse\). Con \alse\, el flujo financiero es idéntico al actual.
- **Ubicación** (sandbox): \90 ACCESO RESTRINGIDO/02 LOGS/{YYYY-MM-DD}/\ (sin subcarpetas
  \lote_…\). Un JSON por intento de endpoint:
  \execution_log_{banco}_{YYYYMMDD}_{HHMMSS}_{step}_{RESULT}_{id8}.json\.
  \RESULT\ ∈ \STARTED|SUCCEEDED|FAILED|PARTIAL|REJECTED\. Todos los archivos de una
  corrida completa comparten el mismo \execution_id\ (UUID) dentro del JSON.
- **Correlación**: columnas aditivas \ExecutionId\ / \ExecutionLogPath\ en el Excel de
  control. Se escriben al aceptar Generate (202), sin tocar EstadoProceso/IsActive/
  ProcessKey ni claves de idempotencia. Reutiliza \execution_id\ en reintentos
  VACIO/ERROR_*; nuevo UUID tras \AMORTIZACION_APLICADA\.
- **Hooks**: Generate → Finalize → Notify → Merge → Dry-run → Apply (best-effort; fallo
  de log no tumba el negocio). Se registra éxito y fallo.
- Independiente de \90 …/01 TRAZABILIDAD\ (manifiestos).

### Estructura en Contabilidad

```
Documentos/{año}/TESORERIA {año}/{MM MES}/{carpeta del banco}
```

Ejemplo: `2026/TESORERIA 2026/07 JULIO/INGRESOS BANCO BOGOTA`.

Reglas de resolución:

- El mes se toma de la **Fecha banco de cada pago**, no de la fecha mínima del reporte.
  Una corrida que cruza fin de mes reparte cada consolidado en su mes correcto.
- Año, `TESORERIA {año}` y mes se crean si faltan.
- La carpeta del banco **no se crea nunca**. Su nombre no es derivable
  (`INGRESOS PA BANCOLOMBIA` es patrimonio autónomo), así que si no existe se informa un
  error accionable con la lista de carpetas presentes.
- La comparación tolera tildes, mayúsculas y espacios repetidos, para reutilizar
  `07 Julio` en lugar de crear un duplicado `07 JULIO`.
- Se cachea por combinación de año, mes y banco: una corrida completa cuesta cuatro
  consultas, no una por PDF.
- La comprobación de existencia previa del PDF se hace contra Contabilidad, que es donde
  se escribe. Sin esto, cada re-ejecución duplicaría archivos.

## Clientes frente a carpetas de automatización

Los clientes conviven con `00 CARGA TRANSACCIONES BANCO` y `01 VALIDACION PAGOS`. Las
exclusiones se **derivan de la configuración**: cualquier carpeta de automatización que
viva justo debajo de la raíz de clientes queda fuera, sin nombres fijos que mantener.
`GRAPH_CLIENTS_EXCLUDED_FOLDERS` permite añadir nombres extra por coma.

Aplica en el emparejamiento de clientes de `generate` (evita coincidencias
parciales espurias). La creación de carpetas documentales ya no es masiva:
Finalize provisiona `ASIENTOS CONTABLES CRED {n}` y `EXTRACTOS` solo en créditos
con Validar=SI. El endpoint `ensure-asientos-contables-folders` fue retirado.

## Diagnóstico sin acceso a logs

En producción no hay rol sobre el App Service, así que no hay acceso a logs, App Settings
ni Startup Command. Para operar en esas condiciones existe:

```
GET /graph/diagnostics
```

Devuelve siempre 200 e informa: fuente de credenciales y qué falta, si el token se
obtuvo, si cada sitio se resuelve, las rutas efectivas y las rutas por banco. **Nunca
devuelve valores de secretos**, solo nombres de configuración.

## Mensajes al operador

Los nombres y la numeración de las carpetas de SharePoint cambian entre ambientes, así que
los textos visibles (`user_message`, `next_action`, descripciones de la API) nombran cada
carpeta por su rol: «la carpeta de revisión», «la carpeta de control», «la carpeta de
correos enviados», «la carpeta destino del consolidado». Los números viven únicamente en
los valores por defecto de `payment_validation_settings.py` y en el `.env`, que son
configurables. Dos pruebas en `tests/test_operational_message_humanization.py` bloquean
la reintroducción de nombres numerados: una revisa los catálogos de mensajes y otra recorre
todo `app/` en busca de literales tipo `01 REVISION`.

## Despliegue

### Procedimiento que funciona (rol Reader)

La cuenta de despliegue solo tiene rol `Reader`, así que `az webapp`, los App Settings del
portal y `POST /api/app/restart` (403) no están disponibles. La secuencia operativa es:

```powershell
.\scripts\build-azure-package.ps1      # empaqueta app/ + artefactos + .env
.\scripts\deploy-kudu-vfs.ps1          # sube por VFS y extrae en wwwroot
.\scripts\oryx-pip-and-health.ps1      # instala deps con el Python de Oryx
.\scripts\try-onedeploy-restart.ps1    # reinicia el contenedor
```

Detalles que importan:

- `.deployment` debe llevar `SCM_DO_BUILD_DURING_DEPLOYMENT=false`. Con `true`, Oryx
  comprime la salida en `output.tar.zst` y se pierde `app/`.
- El contenedor de Kudu es distinto al de la app: `ps` no ve gunicorn y no se puede matar
  el proceso desde ahí.
- El único reinicio que funciona sin Contributor es
  `POST /api/publish?type=static&path=...&restart=true`. `POST /api/app/restart` da 403 y
  `POST /api/zipdeploy` da 400.
- Copiar los archivos a `wwwroot` **no** basta: sin reinicio, el contenedor sigue sirviendo
  el build anterior.
- `scripts/kudu-inspect.ps1` ejecuta comandos en el servidor. La API de Kudu parte el
  comando por espacios, así que hay que envolverlo en `bash -c "..."` con comillas dobles.

### Recursos

Kudu ZIP Deploy con el perfil de publicación. El paquete lleva `application.py`,
`startup.sh`, `.deployment`, `requirements.txt`, la carpeta `app/` y un `.env` en la raíz
que se copia a `/home/site/wwwroot/.env`.

Recursos de producción: grupo `rg-hbiautomatizacion-prod-001`, App Service
`app-hbiauto-prod-001`, Key Vault `keyvaulthbiautoprod001`.

## Herramientas

- `python tools/list_env_vars.py` — inventario de variables de entorno realmente leídas
  por el código, para mantener el `.env` alineado sin sobras ni faltas.
- `scripts/switch-env.ps1 -Target sandbox|production` — aplica overlays de rutas
  SharePoint (`config/environments/*.env`) sobre `../api-hbi-powerAutomate.env`
  (archivo de deploy) sin tocar secretos. `-Status` muestra el entorno activo.
  Producción queda bloqueada hasta `ENV_READY=true` en `production.env`.
- Frases Cursor: «ir a pruebas» / «ir a producción» → regla
  `.cursor/rules/environment-switch.mdc`.
- `GET /graph/diagnostics/paths-probe` — sondeo **solo lectura** de todas las
  rutas del `.env` activo (Operaciones + Contabilidad). Seguro en producción.

## Estado actual

Suite completa en verde: **831 pruebas pasan, 1 omitida, 0 fallos**.

### Desplegado en Azure (2026-07-29) — entorno activo: sandbox / pruebas

- `ACTIVE_ENVIRONMENT=sandbox`, build `sandbox-03-comware-20260729`.
- Raíz pruebas: `…/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`.
- Contabilidad apagada; Merge → `99 SOPORTES DE PAGO CONSOLIDADOS - PRUEBAS`.
- `paths-probe` live: **16/16 OK**, `read_only=true`.

### Desplegado en Azure (2026-07-29) — producción real (disponible vía switch)

- Overlay `production` listo: `ACTIVE_ENVIRONMENT=production`.
- Clientes: `GRAPH_CLIENTS_BASE_PATH=INFORMACION CREDITOS-CLIENTES`.
- Carga banco: `…/01 CARGA TRANSACCIONES BANCO/BANCO_{BOGOTA|BANCOLOMBIA}.xlsx`.
- Validación: `…/02 VALIDACION PAGOS` (misma organización interna que sandbox).
- Exclusión de clientes: `03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`.
- Contabilidad **habilitada**:
  `gecolsacat.sharepoint.com/sites/HBICapitalContabilidad` →
  `{año}/TESORERIA {año}/{MM MES}/{INGRESOS BANCO BOGOTA|INGRESOS PA BANCOLOMBIA}`.
- Carpeta sandbox `99 SOPORTES…` **desactivada** en producción (consolidados van a Contabilidad).
- Verificación live `paths-probe` (2026-07-29): **20/20 OK**, `read_only=true`,
  sin crear ni modificar nada.
- Build marker histórico: `prod-paths-probe-20260729`.

### Sandbox (cuando se vuelva a pruebas)

- Carpeta de pruebas:
  `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`.
- Dentro: `01 CARGA…` + `02 VALIDACION PAGOS` + clientes de prueba.
- Contabilidad apagada; Merge escribe en `99 SOPORTES DE PAGO CONSOLIDADOS - PRUEBAS`.
- Volver: `.\scripts\switch-env.ps1 -Target sandbox` + rebuild/deploy.

### Desplegado en Azure (2026-07-29) — Fecha pago = Fecha banco

- Apply/dry-run: columna «Fecha pago» usa **solo Fecha banco** (serial Excel
  soportado); sin fallback a `report_date`. Si falta → `FECHA_BANCO_REQUIRED`.
- Aplica a **PAGO y ABONO** (capital/mora): la fecha del asiento queda solo
  como auditoría (`fecha_asiento` / `payment_date_matches_asiento`).
- Tests: suite verde. `/health` ok en `app-hbiauto-prod-001`.

### Desplegado en Azure (2026-07-29) — resiliencia Generate (estrés 43)

- `JobManager` persiste jobs en disco (`PAYMENT_VALIDATION_JOBS_DIR` o
  `wwwroot/.payment_validation_jobs`). Tras recycle, jobs `queued`/`running` →
  `failed` con `JobInterruptedByProcessRestart` (polling compatible).
- Generate: heartbeat ~30s, `progress.bank_rows_*`, `asyncio.sleep(0)` por fila,
  caché de candidatos de crédito por carpeta de cliente (PAGO/ABONO/MORA).
- `/health` expone `build` (`generate-resilience-20260729`) para verificar deploy.
- Estrés sandbox: **43** movimientos banco_bogota; job final `completed`; un solo
  Excel de revisión (idempotencia `already_generated` / `file_action=reused`).
- Parches E2E de Secretaría/Errores/Finalize **no** forman parte del código productivo.

### Desplegado en Azure (2026-07-28) — bitácora + sandbox

- `EXECUTION_RUN_LOG_ENABLED=true` en `.env` del App Service.
- Bitácoras (antes del rename): `…/01 VALIDACION PAGOS/06 LOGS/…` — supersedido por
  estructura 2026-07-29 arriba.
- Contabilidad **deshabilitada** (`GRAPH_ACCOUNTING_SITE_HOSTNAME` vacío).
- Módulo `execution_run_log.py` presente en wwwroot; `/health` ok; `/graph/diagnostics` ok.

### Completado

- Finalize **bloquea** si la hoja `Errores` del Excel de revisión tiene casos abiertos
  (`review_has_open_errors`). Mensaje operativo para correo vía enrichment. Sin hoja
  Errores o con hoja vacía (solo encabezado) el cierre sigue permitido.
- Reloj operativo `America/Bogota` centralizado (`colombia_time.py`): Excel de control,
  jobs HTTP, ProcessKey fallback, follow-up CreatedAt/UpdatedAt, bitácora amort, PDF
  de correo, logs `asctime`, y `process_date` por defecto. Alias `utc_now_iso` conserva
  el nombre pero emite `-05:00`. Dependencia `tzdata`.
- Auth HTTP aditiva: `API_HTTP_KEY` + header `X-API-Key` (middleware). Sin variable,
  comportamiento idéntico al anterior; con variable, 401 si falta/incorrecta.
  `/health` exento.
- Correo Notify: el intro enumera **todas** las fechas banco validadas (no un solo día
  ni un rango).
- Artefactos únicos por lote: `ProcessKey = payment-validation|{banco}|{fecha}|{uuid}`,
  nombres `cartera_validada_*_{fecha}_{uuid}.xlsx` / soporte / revisión. Tras
  `AMORTIZACION_APLICADA` se puede iniciar otro lote el mismo día.
- `id_pago` = UUID v4 completo (sin truncar a 8 hex).
- Al cierre exitoso de Apply se elimina el Excel de revisión y se limpia
  `ValidationFilePath` (la copia canónica queda en Histórico).
- Proveedor de credenciales perezoso con soporte de Key Vault y caché de token.
- Endpoint de diagnóstico sin secretos.
- Resolución de los dos sitios, aditiva y retrocompatible con `?search=`.
- Destino contable dinámico por mes y banco, con idempotencia en Contabilidad.
- Estructura de carpetas nueva y eliminación de la dependencia de la carpeta de errores.
- Blindaje de la raíz de clientes.
- `.env.production.example` verificado contra la estructura real de SharePoint.
- Textos visibles al operador reescritos para nombrar las carpetas por su rol.

### Desplegado en Azure (2026-07-27)

Ambiente de pruebas en `app-hbiauto-prod-001`, apuntando al sandbox de SharePoint
(`02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES`) y con el sitio de
Contabilidad desactivado. `/health` responde `ok`, `/docs` carga y el OpenAPI expone 30
rutas.

**Bloqueante abierto: el client id de Key Vault es incorrecto.** `/graph/diagnostics`
devuelve `AADSTS700016` porque el secreto `clientid-app-hbiautoprod-001` contiene el mismo
GUID que `tenantid` (`f49f6ea8-…`), es decir el id del directorio en lugar del id de la
aplicación. Según el inventario de infraestructura, el `appId` real de la registración
`app-hbiautoprod-001` empieza por `fc73002d-…`. Hasta corregir ese secreto, ninguna llamada
a Graph funciona; el resto de la configuración sí quedó validada.

Comprobado de paso: la identidad administrada **sí** puede leer Key Vault (los tres
secretos se resolvieron), así que el rol `Key Vault Secrets User` está concedido.

Las credenciales del despliegue anterior no sirven como alternativa: pertenecen al tenant
de Comware (`28c8c2be-…`) y Graph responde `Invalid hostname for this tenancy` para
`gecolsacat.sharepoint.com`.

### Plantilla Excel de carga bancaria (2026-07-27)

Archivo en la raíz del monorepo: `Plantilla_Carga_Pagos_Banco.xlsx` (regenerable con
`_build_plantilla_carga_banco.py`).

- Fila 1: nombre del banco (editable).
- Fila 2: encabezados bloqueados (`Fecha`, `Crédito`, `Concepto`, `Tipo Aplicación`, `Transacción`).
- Fila 3: ejemplo bloqueado (celdas con prefijo `ejemplo:`); `Tipo Aplicación` (D3) desbloqueado para arrastrar el desplegable.
- Filas 4+: editables; Fecha=`DD-MMM`, Crédito=`#,##0.00`, resto texto; lista de tipos.
- Solo hoja `Carga`. Protección permite pegar en filas de datos (contraseña `hbi`).
- Pegar datos desde la fila 4 (no desde la 1–3).

### Reintentos sin parámetros extra (2026-07-27)

Los flujos se consumen desde **Power Automate con un body fijo**, así que un paso que
quedó incompleto o con error debe poder repetirse llamando otra vez la misma URL.

- Merge: `MERGE_RUNNABLE_STATES` = `PENDIENTE_ASIENTOS`, `MERGE_PARCIAL`, `ERROR_MERGE`,
  `CONSOLIDANDO`, `CONSOLIDADO`. Repetir tras `CONSOLIDADO` completo devuelve el resultado
  previo por idempotencia (`already_merged`), no un error.
- Amortización: `AMORTIZATION_RUNNABLE_STATES` = `CONSOLIDADO`, `MERGE_PARCIAL`,
  `ERROR_APPLY`, `AMORTIZACION_PARCIAL` (reintento tras apply parcial).
- Escritura en tablas con celdas combinadas: `_set_cell_value` escribe en el ancla
  del merge (evita `MergedCell` read-only en tablas DIEGO).
- Notify con `historical_file_path`: siempre relee `ProcessKey` del control para no
  regenerarlo con el mínimo de fechas del Excel banco.

Los mensajes de “paso adelantado” (`NO_READY_PROCESS`, `control_not_ready_*`) usan
lenguaje claro y nombran el paso previo, sin jerga de estados internos.

### Desplegado en Azure (2026-07-28, amortización EQUINORTE + Finalize Errores)

Redeploy a `app-hbiauto-prod-001` (Kudu VFS + Oryx pip + OneDeploy static restart).
`/health` → ok. `/graph/diagnostics` sin clave → 401 (API Key activa; el script de
reinicio interpreta 401 como “código viejo”, pero es auth). En wwwroot están
`amortization_event_order.py`, el gate `review_has_open_errors` y Apply sin
arrastre O:P.

### Desplegado en Azure (2026-07-27, redeploy merge retry)

Redeploy con el flujo de Kevin (PublishSettings + Kudu VFS + Oryx pip + OneDeploy
restart). Código local sincronizado con el override `GRAPH_CLIENT_ID` sobre Key Vault
(`env_overrides.client_id: true`). Graph token OK, SharePoint sandbox OK, Contabilidad
desactivada. Incluye reintentos de Merge/amortización sin body extra y mensajes de
paso adelantado.

### Matriz de prueba Generate (2026-07-27)

Inspección sandbox de extractos (TOTAL A PAGAR + max fecha límite PDF) para
GEOEXCON, EQUINORTE, AGRECAR, ACIMOR, MINCIVIL e INVERSIONES. Artefacto:
canvas `preprod-test-matrix` en el proyecto Cursor.

### E2E API sandbox Bogotá (2026-07-27) — ejecutado

Flujo API (sin Power Automate) sobre `BANCO_BOGOTA.xlsx` existente: Generate →
idempotencia → Finalize → Notify → asientos → Merge (parcial → CONSOLIDADO) →
amortización dry-run/apply. Asientos de prueba en `asientos_prueba/generados/`.
Resultados en `_work/`. Fixes desplegados: parse ISO en fechas abono Finalize,
fechas `DD-abr` en Notify, encode de rutas `#` en `path-content`, DELETE item.

### Fixes post-E2E (2026-07-27, créditos + ProcessDate)

- Extracción de crédito: `normalize_credito_digits` y merge de carpetas leen el
  número tras «CREDITO #», no el prefijo ordinal (`2 CREDITO #37` → `37`).
- Notify y Merge: `ProcessDate` / ciclo de carpeta priorizan la fecha del
  `ProcessKey` del control; el mínimo de fechas del Excel banco es solo fallback.
- Tests: `test_normalize_credito_digits`, ordinal en merge, `_process_date_from_process_key`.

### Amortización sandbox OK (2026-07-27, tarde)

Dry-run `can_apply=true` (8 eventos) + Apply escribió **6 tablas** + IBR en PAGO;
ABONO sin IBR. Control `AMORTIZACION_APLICADA`. Apply idempotente
(`already_applied`). Fixes: no cerrar apply con 0 tablas; dry-run acepta
`APLICANDO_AMORTIZACION`; merge elige asiento por tipo de aplicación.
README de casos: `docs/CASOS_PROBADOS_PRODUCCION.md`.

### Stress E2E + hardening amort/merge (2026-07-28)

Lote 25 filas sandbox (créditos nuevos A&M/DIEGO/G&J/INDUCAB/AGRECAR). Generate→
Merge OK; Apply parcial (MergedCell DIEGO + ProcessKey corrupto a `2025-09-15` vía
Notify con `historical_file_path`). Fixes desplegados a `app-hbiauto-prod-001`:

- Escritura amort: descombinar MergedCell antes de escribir en la fila/col destino.
- Causac Inter Mes / O:P: extender fórmulas a `última_aplicación + 1`.
  **Revertido el 2026-07-28 (ver caso EQUINORTE abajo): la API ya no toca O:P.**
- `AMORTIZACION_PARCIAL` y `APLICANDO_AMORTIZACION` reintentables.
- Notify: ProcessKey desde control aunque venga histórico en body.
- Fallback asientos en `PROCESADOS/` (basename + nombre canónico + listado).
- Gate ABONO no bloquea por `can_apply=false` de errores PAGO.
- Idempotencia: hash PDF manda sobre eTag (movidos a PROCESADOS).
- Re-apply si el log existe pero la fila de aplicación quedó vacía (verify fallida).

Control stress cerrado en `AMORTIZACION_APLICADA` con ProcessKey `2026-07-28`.
DIEGO #32 verificado: IBR en cuota, aplicaciones 32–33, Causac hasta fila 34.

### Limpieza G&J #224 + regresión merge/amort (2026-07-28 noche)

- Eliminadas filas duplicadas 17–18 (re-apply concurrente); fechas 14–15
  corregidas de `2025-09-15` → `2026-07-28`; log de duplicados removido.
- Regresión: Merge×2 `already_merged`/`pdf_reused`; Apply×2 `already_applied`
  sin escrituras nuevas. Artefactos: `_work/stress_e2e/26_gj224_cleanup.json`,
  `37_regression_summary.json`.

### Caso EQUINORTE 258/265 — orden de filas y columnas O:P (2026-07-28)

Comparación del llenado manual contra el de la API sobre el mismo par de soportes
(`caso-analizar/`). Los montos extraídos coincidían; fallaba todo lo demás.

**Orden de filas.** El crédito 265 traía dos asientos: comprobante 3494 (pago de
cuota) y 3495 (ajuste de saldos menores por 285). El manual pone la cuota primero;
la API los invirtió porque `_pick_asiento_names_for_group` devuelve los nombres en
orden alfabético y `...credito-265-evento-2.pdf` ordena antes que
`...credito-265.pdf`. El abono a capital de una fila alimenta el capital base del
período siguiente, así que la causación de abril quedó en 585.194,65 en vez de
545.481,32.

Corregido con `app/application/services/amortization_event_order.py`: los asientos
de un mismo ID Pago se ordenan por fecha del asiento → pago con recaudo bancario
antes que ajuste puro de saldos menores → consecutivo del documento → orden
original. El dry-run pre-parsea los asientos (con caché de bytes y de eventos, sin
descargas ni parseos extra) y asigna `event_index` sobre ese orden.

**Parser.** `fecha_asiento` y el consecutivo no se leían de estos PDFs: la fecha
sale como `23 4 2026 Fecha :` (pypdf invierte los tokens de la rejilla Año/Mes/Día)
y el número va solo en la primera línea, sin la palabra "comprobante". Se añadieron
los patrones y el campo `numero_asiento`. **`comprobante` se dejó intacto** porque
alimenta `build_amortization_idempotency_key`.

**Columnas O:P.** Se eliminó `ensure_application_related_formulas`. El multiplicador
de `Causac Inter Mes` (`=+O{fila}*N`) es criterio contable —en los archivos manuales
sigue `30 − día de corte del período anterior`, con ajustes a mano en el bloque
X:AI— y el arrastre lo copiaba literal: escribió `=+O9*10` donde el manual tiene
`=+O9*8`, inflando la causación de abril del 258 en 1.723.382,94. La secretaria las
completa a mano. Apply y dry-run conservan O:P exactamente como estaban; las claves
`formula_fill_*` quedan en cero por compatibilidad.

**Fecha pago.** Únicamente la **Fecha banco** del Excel BANCO_* (histórico /
manifest) para **PAGO y ABONO** (capital/mora). Sin fallback a `report_date` ni a
la fecha del asiento. Si no se puede leer (p. ej. serial Excel), el item falla
con `FECHA_BANCO_REQUIRED` en lugar de escribir la fecha del día o del asiento.
Cuando difiere de la del asiento, el item lleva
`payment_date_matches_asiento=false` y el resumen de apply cuenta
`payment_date_differs_from_asiento` — solo auditoría.

Tests: `test_amortization_event_order.py`,
`test_dry_run_orders_pago_cuota_before_saldos_menores_adjustment`,
`test_dry_run_flags_payment_date_differing_from_asiento`,
`test_apply_leaves_op_columns_untouched*`, `test_parser_reads_fecha_and_numero_from_erp_grid`.

### UX correo y Generate (2026-07-28, sin deploy aún)

1. **`review_folder_not_empty`:** el mensaje ya no dice “día anterior”; habla de Excel
   de una ejecución anterior o archivo pendiente de archivar (la regla sigue siendo:
   carpeta de revisión no vacía).
2. **Notify:** omite la fila de plantilla (`ejemplo: …`) al armar la tabla HTML/PDF
   del correo de validación de extractos.
3. **Merge / Flujo 3:** el job expone `consolidation_folder_web_url`,
   `consolidation_folder_relative_path` y, por output, `output_web_url` /
   `output_folder_web_url` / `output_folder_relative_path` (Graph `webUrl`). Power
   Automate debe usar el link de carpeta en el correo (no la ruta textual con
   “(ejemplo)”).
4. **Enlaces Excel en correo:** `sharepoint_open_in_browser_url` añade `?web=1` a los
   `webUrl` de tablas de amortización (Flujo 4) y a histórico/Asientos_Pendientes
   (Finalize), para abrir en Excel Online en lugar de descargar el `.xlsx`.
5. **Hipervínculos en Excel (Generate/Finalize):** celdas con link usan azul `#0563C1`,
   subrayado y fondo `#E8F4FC` (estilo Excel estándar). Finalize ya no pisa esa fuente
   al aplicar el estilo de cuerpo. Abonos también convierte `Link extracto` HTTP en
   hipervínculo (conserva N/A).
6. **Notify HTML/PDF:** tablas con encabezado navy, filas zebra y tipografía Calibri/
   Segoe UI; mismos datos y títulos de sección.
7. **Pool combinado de extractos (Generate):** `_resolve_extract_pdf_pool` ya no aplica
   prioridad excluyente de `EXTRACTOS`. Une PDFs strict de raíz + `EXTRACTOS`; cada
   candidato lleva `relative_path` / `source_location`. Selección por `fecha_limite`
   (V2) + dedupe SHA-256 (preferir `EXTRACTOS`) + empate fail-closed. Si gana la raíz
   con `EXTRACTOS` presente → observación no bloqueante
   `EXTRACT_OUTSIDE_CANONICAL` (no cambia Estado Pago ni mueve archivos). Sin lotes
   ni índice eTag (fase 2). **2026-07-30:** un PDF del pool con fecha límite ilegible
   o descarga fallida ya no se omite en silencio: falla
   `fecha_limite_extracto_not_readable` aunque existan otros extractos legibles
   (caso Equinorte extracto dañado en EXTRACTOS).
9. **Generate recrea Excel ausente:** si el lote está en `REVISION_CREADA` (o
   `ERROR_GENERATE`) y el archivo de `ValidationFilePath` ya no existe en SharePoint,
   Generate crea uno nuevo (`file_action: "recreated"`) en lugar de devolver
   `already_generated` con un enlace fantasma. Si el archivo sí existe → `reused`
   como antes. No aplica tras Finalize avanzado.
10. **Cancel proceso activo (2026-07-30):**
    `POST /graph/sharepoint/payment-validation/cancel-active-process/queue`
    con `bank_code` **opcional** y `process_key` opcional. Job type
    `cancel_active_process`. Sin `bank_code`: auto-detect del único banco en
    `REVISION_CREADA`/`ERROR_GENERATE` + `IsActive`; si hay dos →
    `MULTIPLE_READY_PROCESSES`; si ninguno → `already_cancelled` (idempotente).
    Con `bank_code` explícito se cancela solo ese. Resetea a `VACIO` +
    `IsActive=false`, limpia claves/rutas e intenta borrar el Excel de revisión.
    Rechaza `FINALIZADO`/merge/amort. Mutex compartido con Generate/Finalize.
    Tests: `test_cancel_process_control.py`, router cancel.

### Pendiente

- **API Key en producción:** **ACTIVA** en `app-hbiauto-prod-001` (`API_HTTP_KEY` en
  `.env` del wwwroot). Sin header `X-API-Key` → `401`. `/health` público.
  Power Automate debe enviar el mismo secreto en **todos** los HTTP (POST y GET jobs).
- Decidir consumidor de `pagos_adelantados` para cierre IBR en corridas futuras
  (hoy solo registra en Finalize; el IBR de la misma corrida sí se llena en amort).
- Generate deja Validar=SI en todas las filas de crédito: la secretaria debe
  marcar NO en las que no apliquen (comportamiento operativo, no bug de crash).
- Worker único: Generate largo bloquea polling de jobs (mejora de escala).
- Cuando Infra corrija `clientid-app-hbiautoprod-001` en Key Vault, retirar
  `GRAPH_CLIENT_ID` del `.env` fuente.
- Corregir el secreto `clientid-app-hbiautoprod-001` en Key Vault con el `appId` real.
- Prueba de integración real contra los dos sitios de producción.
- Contabilidad 2027 (smoke 2026-07-28): **OK** — la app creó
  `2027/TESORERIA 2027/07 JULIO` (+ `INGRESOS BANCO BOGOTA` y PDF de humo solo para
  la prueba) vía `POST /graph/diagnostics/accounting-folder-smoke` (gated por
  `ACCOUNTING_FOLDER_SMOKE_ENABLED`). Permiso Graph alcanza a crear año nuevo.
  El usuario borrará manualmente la carpeta `2027` de Contabilidad. Tras la prueba,
  Contabilidad quedó de nuevo deshabilitada en el `.env` del App Service (sandbox).
- Confirmar el nombre real de la biblioteca de documentos en ambos sitios: la interfaz
  muestra `Documentos` en el menú y `Documentos compartidos` en la ruta de acceso. Si
  falla, `/graph/diagnostics` devuelve la lista de nombres disponibles.
- Decidir si se necesita `Mail.Send` según el resultado de la prueba de correo.
- Rotar la clave del Storage Account, que circuló en texto plano por correo.
