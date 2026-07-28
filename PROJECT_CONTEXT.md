# PROJECT_CONTEXT — API HBI Capital (automatización de validación de pagos)

Fuente de verdad del estado del proyecto. Actualizar tras cada cambio significativo.

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

Los trabajos largos se ejecutan en memoria del proceso y se consultan por `job_id`.
**Un solo worker es obligatorio**: con más de uno, el job quedaría en otro proceso y su
consulta devolvería 404.

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

### Estructura en Operaciones

```
INFORMACION CREDITOS-CLIENTES/
├── 00 CARGA TRANSACCIONES BANCO/     BANCO_BOGOTA.xlsx, BANCO_BANCOLOMBIA.xlsx
├── 01 VALIDACION PAGOS/
│   ├── 01 CONTROL/                   controles por banco, CORREOS, IBR_DIARIO, pagos_adelantados
│   ├── 02 REVISION/                  validacion_pagos_*.xlsx del día
│   ├── 03 HISTORICO/                 cartera_validada por fecha
│   ├── 04 TRAZABILIDAD/              manifiestos y bitácora
│   └── 05 CORREOS ENVIADOS/          PDF de cada correo enviado
└── <cliente>/                        los clientes están en la raíz, junto a las dos anteriores
```

No existe carpeta de errores: el código no la referencia en ningún flujo.

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

Aplica en dos puntos: el emparejamiento de clientes de `generate` (evita coincidencias
parciales espurias) y `ensure-asientos-contables-folders` (evita crear subcarpetas
basura dentro de la estructura operativa).

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

## Estado actual

Suite completa en verde: **742 pruebas pasan, 1 omitida, 0 fallos**.

### Completado

- Reloj operativo `America/Bogota` centralizado (`colombia_time.py`): Excel de control,
  jobs HTTP, ProcessKey fallback, follow-up CreatedAt/UpdatedAt, bitácora amort, PDF
  de correo, logs `asctime`, y `process_date` por defecto. Alias `utc_now_iso` conserva
  el nombre pero emite `-05:00`. Dependencia `tzdata`.
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

### Pendiente

- **API Key / auth HTTP** en App Service (obligatorio antes de banca real).
- Decidir consumidor de `pagos_adelantados` para cierre IBR en corridas futuras
  (hoy solo registra en Finalize; el IBR de la misma corrida sí se llena en amort).
- Generate deja Validar=SI en todas las filas de crédito: la secretaria debe
  marcar NO en las que no apliquen (comportamiento operativo, no bug de crash).
- Worker único: Generate largo bloquea polling de jobs (mejora de escala).
- Cuando Infra corrija `clientid-app-hbiautoprod-001` en Key Vault, retirar
  `GRAPH_CLIENT_ID` del `.env` fuente.
- Corregir el secreto `clientid-app-hbiautoprod-001` en Key Vault con el `appId` real.
- Prueba de integración real contra los dos sitios de producción.
- Confirmar el alcance del permiso en Contabilidad más allá de `2026/TESORERIA 2026`
  (en enero de 2027 hará falta crear `2027/TESORERIA 2027`).
- Confirmar el nombre real de la biblioteca de documentos en ambos sitios: la interfaz
  muestra `Documentos` en el menú y `Documentos compartidos` en la ruta de acceso. Si
  falla, `/graph/diagnostics` devuelve la lista de nombres disponibles.
- Decidir si se necesita `Mail.Send` según el resultado de la prueba de correo.
- Rotar la clave del Storage Account, que circuló en texto plano por correo.
- Columnas O:P de Causac aún hardcodeadas (validar layouts no estándar en dry-run).
