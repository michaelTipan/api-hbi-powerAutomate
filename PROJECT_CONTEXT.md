# PROJECT_CONTEXT — API HBI Capital (automatización de validación de pagos)

Fuente de verdad del estado del proyecto. Actualizar tras cada cambio significativo.

## Stack

- **API**: FastAPI + Pydantic. Servida con Gunicorn + `UvicornWorker`, **1 worker**.
- **Integración**: Microsoft Graph API vía HTTP (`client_credentials`), sin SDK.
- **Documentos**: openpyxl (Excel), pypdf (unión de PDF), reportlab.
- **Configuración**: variables de entorno leídas de un `.env` en la raíz (`load_dotenv`).
- **Pruebas**: pytest con dobles en memoria de Graph. No hay `conftest.py` global.

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

- Proveedor de credenciales perezoso con soporte de Key Vault y caché de token.
- Endpoint de diagnóstico sin secretos.
- Resolución de los dos sitios, aditiva y retrocompatible con `?search=`.
- Destino contable dinámico por mes y banco, con idempotencia en Contabilidad.
- Estructura de carpetas nueva y eliminación de la dependencia de la carpeta de errores.
- Blindaje de la raíz de clientes.
- `.env.production.example` verificado contra la estructura real de SharePoint.
- Textos visibles al operador reescritos para nombrar las carpetas por su rol.

### Pendiente

- Prueba de integración real contra los dos sitios de producción.
- Confirmar que la identidad administrada tiene el rol `Key Vault Secrets User`.
- Confirmar el alcance del permiso en Contabilidad más allá de `2026/TESORERIA 2026`
  (en enero de 2027 hará falta crear `2027/TESORERIA 2027`).
- Confirmar el nombre real de la biblioteca de documentos en ambos sitios: la interfaz
  muestra `Documentos` en el menú y `Documentos compartidos` en la ruta de acceso. Si
  falla, `/graph/diagnostics` devuelve la lista de nombres disponibles.
- Decidir si se necesita `Mail.Send` según el resultado de la prueba de correo.
- Rotar la clave del Storage Account, que circuló en texto plano por correo.
- Seguridad HTTP del endpoint y estrategia de logs: en espera de accesos.
