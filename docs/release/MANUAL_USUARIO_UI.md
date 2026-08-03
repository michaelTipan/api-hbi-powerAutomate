# Manual de usuario — UI de validación de pagos (HBI Capital)

Lenguaje operativo. Entorno de referencia: **sandbox / ENTORNO DE VALIDACIÓN**.

Acceso: ver [ACCESO_OPERADOR_SANDBOX.md](./ACCESO_OPERADOR_SANDBOX.md).

---

## Para qué sirve esta aplicación

Centraliza la **validación de pagos** de un banco en un día:

1. Generar el archivo de revisión a partir del Excel del banco.  
2. Completar la validación de pagos (montos, estado, validar).  
3. Cerrar la revisión.  
4. Enviar el correo de abonos.  
5. Cargar soportes contables (PDF) y generar el PDF consolidado.  
6. Aplicar la amortización.

Objetivo: hacer casi todo **desde la web**. La excepción aceptada es editar el **Excel inicial del banco** en SharePoint (por tiempo / plantilla).

---

## Pantallas principales

### Login

- Usuario de operador (sandbox: `operador_hbi`).  
- Tras entrar verás el badge de entorno (debe decir validación / sandbox en pruebas).

### Panel

- **Nuevo proceso:** elige banco → opcionalmente abre el Excel del banco → **Iniciar validación**.  
- **Seguimiento:** progreso del job de generación.  
- **Procesos activos:** tarjetas del banco en curso → **Continuar proceso** para ir al detalle.

Si el banco ya tiene proceso, no inicies otro: continúa desde la tarjeta activa.

### Historial

Listado de procesos / archivo (según lo disponible en Control + archivo). Útil para consultar días anteriores.

### Detalle del proceso

Orden habitual:

1. Avisos (Errores, archivo faltante) si aplican.  
2. **Fase actual** (título + botón principal: Finalizar, Enviar correo, Generar PDF, Amortización…).  
3. Paneles de trabajo: **Revisión del lote** y/o **Cargar asientos**.  
4. Resumen de estado y stepper (5 fases).  
5. Documentos por fase (enlaces a históricos, correo, PDF consolidado…).

---

## Las 5 fases (en lenguaje claro)

| # | Fase | Qué haces tú |
|---|---|---|
| 1 | Generar archivo | Se lanza desde el Panel. Esperas a que termine. |
| 2 | Finalizar revisión | Editas en **Revisión del lote** y pulsas **Finalizar revisión**. |
| 3 | Enviar correo | Confirmas **Enviar correo**. |
| 4 | Generar PDF consolidado | Subes PDF en **Cargar asientos** y luego **Generar PDF consolidado**. |
| 5 | Procesar amortización | Confirmas **Procesar amortización**. |

Cuando las cinco están en verde: proceso completado.

---

## Revisión del lote (panel)

- Muestra pagos / abonos del Excel de revisión.  
- Con edición activa puedes cambiar campos y **Guardar cambios**.  
- **Comprobar antes de finalizar** valida reglas sin cerrar aún.  
- **Finalizar revisión** (botón de la fase) cierra el lote (incluye cambios sin guardar si el sistema lo indica en el diálogo).

No abras el Excel de revisión en SharePoint salvo que el equipo te lo pida por un caso especial.

---

## Cargar asientos (panel)

- Sube un PDF por **id de pago + crédito**.  
- Si hay pendientes, usa **Elegir PDF** en cada fila.  
- Si no hay lista, usa **Carga manual**.  
- La carpeta y el nombre final los define el servidor (no pegas rutas de SharePoint).

Cuando los grupos estén listos, se habilita **Generar PDF consolidado**.

---

## Botones que verás a menudo

| Botón | Significado |
|---|---|
| Abrir archivo del banco | Excel de entrada (SharePoint). Solo preparación. |
| Iniciar validación | Genera el lote del día. |
| Continuar proceso | Entra al detalle del proceso activo. |
| Finalizar revisión | Cierra la validación del lote. |
| Regenerar archivo de revisión | Solo si hay casos en Errores o falta el archivo. |
| Enviar correo | Notifica abonos. |
| Generar PDF consolidado | Une soportes. |
| Procesar amortización | Aplica tablas. |
| Actualizar (↻) | Relee el estado del proceso. |

---

## Tipos de aplicación (recordatorio de negocio)

En el Excel / revisión pueden aparecer, entre otros:

- `PAGO`  
- `PAGO Y ABONO CAPITAL`  
- `ABONO CAPITAL`  
- `ABONO MORA`  

La UI y el backend validan cuadres y reglas por tipo. Si el preflight o Finalizar reportan un problema, corrige la fila indicada.

---

## Buenas prácticas

1. Un proceso activo por banco: no generes otro si ya hay uno en curso.  
2. No cierres el navegador mientras un job está “En curso”.  
3. Tras un deploy, haz **Ctrl+F5** por si el navegador cachea la SPA.  
4. Si el mensaje habla de SharePoint para la **revisión**, puede ser una versión vieja: verifica `/health` o avisa al equipo.

---

## Pruebas manuales paso a paso

Ver [MANUAL_PRUEBAS_UI_SANDBOX.md](./MANUAL_PRUEBAS_UI_SANDBOX.md).

## Deploy (desarrolladores)

Ver [../contributor/SANDBOX_DEPLOY.md](../contributor/SANDBOX_DEPLOY.md).
