# Casos probados — API HBI Power Automate (sandbox → producción)

Fecha de validación: **2026-07-27**  
App Service: `app-hbiauto-prod-001`  
Entorno de datos: SharePoint sandbox `02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES`  
Banco ejercitado de punta a punta: **Banco Bogotá**

Este documento resume qué ya está validado en sandbox, qué reintentos/idempotencias
existen, y qué queda operativo / con decisión pendiente antes de apuntar carpetas reales.

---

## 1. Flujo operativo completo (validado)

Orden Power Automate / API:

| # | Paso | Endpoint | Resultado sandbox |
|---|------|----------|-------------------|
| 0 | Setup controles | `POST .../setup/merge-control-workbook` | OK (idempotente) |
| 0b | Setup IBR | `POST .../setup/ibr-workbook` | OK |
| 0c | Setup pagos adelantados | `POST .../setup/payment-followup-workbooks` | OK |
| 1 | Generate | `POST .../payment-validation/generate/queue` | OK + 2.ª corrida `already_generated` |
| 2 | Finalize (asientos CRED n + EXTRACTOS) | `POST .../payment-validation/finalize/queue` | OK |
| 3 | Notify | `POST .../notify-validar-extractos-email` | OK (correo + PDF) |
| 4 | Merge | `POST .../merge-composite-validado-pdfs` | OK (`MERGE_PARCIAL` → reintento → `CONSOLIDADO`) |
| 5 | Amort dry-run | `POST .../amortization/dry-run/queue` | OK `can_apply=true` (8 eventos) |
| 6 | Amort apply | `POST .../amortization/apply/queue` | OK **6 tablas escritas**, IBR en PAGO, ABONO sin IBR |

Evidencia amortización (apply exitoso):

- 8 eventos `APPLIED` (6 PAGO + 2 ABONO)
- Tablas actualizadas: AGRECAR, GEOEXCON 231, GEOEXCON 254, EQUINORTE 258/264/265
- IBR escrito en PAGO (`apply_ibr_written=true` donde correspondía)
- ABONO: IBR `NOT_REQUIRED` (regla de negocio respetada)
- Control quedó en `AMORTIZACION_APLICADA`

Artefactos locales: `_work/`, `_work/prod_validation/`.

---

## 2. Idempotencias y reintentos (lo que el usuario puede hacer)

Todos estos pasos se reintentan **llamando la misma URL** (body `{}` o solo `bank_code`).
No hace falta un flag especial de “force” para el día a día.

| Paso | Si ya se ejecutó bien | Si falló / quedó parcial | Estado de control que permite reintento |
|------|----------------------|---------------------------|----------------------------------------|
| Generate | `already_generated: true` | Corregir Excel banco y volver a Generate | — |
| Finalize | `already_finalized` (si aplica) | Corregir Validar/distribución y reintentar | Tras Generate |
| Notify | `already_notified` | Reintentar tras `FINALIZADO` | `FINALIZADO` |
| Merge | `already_merged: true` | Reintentar con asientos faltantes | `PENDIENTE_ASIENTOS`, `MERGE_PARCIAL`, `ERROR_MERGE`, `CONSOLIDANDO`, `CONSOLIDADO` |
| Amort dry-run | Solo lectura | Reintentar siempre | `CONSOLIDADO`, `MERGE_PARCIAL`, `ERROR_APPLY` |
| Amort apply | `already_applied: true` (0 escrituras) | Reintentar tras corregir docs | `CONSOLIDADO`, `ERROR_APPLY`, `AMORTIZACION_PARCIAL` |

**Probado en sandbox:**

- Generate ×2 → segunda idempotente
- Merge ×2 tras `CONSOLIDADO` → `already_merged`
- Amort apply ×2 tras éxito → `already_applied: true`, `tables_uploaded_count: 0`
- Merge con `MERGE_PARCIAL` (faltaba asiento AGRECAR) → cargar asiento → reintento → `CONSOLIDADO`

**Comportamiento de “paso adelantado”:** si llamas Notify/Merge/Amort antes de tiempo,
la API responde con mensaje claro (`NO_READY_PROCESS` / `control_not_ready_*`) sin corromper el control.

---

## 3. Reglas de negocio ya respetadas en amortización

- **PAGO / PAGO Y ABONO CAPITAL:** escribe fila de aplicación + **IBR** si hay tasa en `IBR_DIARIO.xlsx` para la fecha límite del extracto.
- **ABONO CAPITAL / ABONO MORA:** escribe en **Aplicación de Pagos**; **no modifica IBR**.
- Idempotencia fina por evento (`_AUTOMATION_LOG` + huella PDF): no duplica filas al reintentar.
- Tras apply OK, asientos usados se mueven a `…/ASIENTOS CONTABLES CRED n/PROCESADOS/`.
- Un asiento por tipo de aplicación cuando hay varios PDF en la carpeta (match por nombre: cuota / pago y abono / abono capital / abono mora).

---

## 4. Pagos adelantados e IBR “en corridas futuras”

### Lo que sí está implementado

- Generate marca pagos adelantados (fecha banco &lt; fecha extracto) con observación.
- Finalize **registra** en `pagos_adelantados.xlsx` (hoja `Pendientes`) con `EstadoIBR=PENDIENTE_IBR`.
- En la **misma** corrida de amortización, si el pago entra como PAGO validado y hay IBR para la fecha límite, el IBR **sí se llena** en la tabla (no depende de la bandeja).

### Lo que NO está cableado (necesita tu decisión)

No hay un consumidor que, en una **corrida posterior**, lea `pagos_adelantados.xlsx` y complete IBR/tablas solo desde esa bandeja.

Las columnas `FechaIBRRequerida`, `FilaIBR`, `IBRUsado`, `FechaCierreIBR` existen como esquema, pero **ningún endpoint las cierra automáticamente hoy**.

**Pregunta para ti:** ¿quieres que implementemos ese cierre automático en Amort apply
(leer Pendientes + IBR disponible + actualizar tabla y pasar a Historico), o la bandeja
sigue siendo solo seguimiento manual para la secretaria?

---

## 5. Endpoints smoke (producción App Service)

| Método | Ruta | Estado |
|--------|------|--------|
| GET | `/health` | 200 |
| GET | `/graph/diagnostics` | 200 |
| GET | `/openapi.json` | 200 (~31 rutas) |
| GET | `/graph/sharepoint/resolve-env` | 200 |
| POST | setups control / IBR / followup | 200 |
| POST+GET jobs | generate / finalize / notify / merge / dry-run / apply | 202 + completed |

Utilidades Graph (`item-content`, `path-content`, `children`, etc.) disponibles para operación/soporte.

---

## 6. Bugs corregidos en esta validación (desplegados)

1. Crédito `2 CREDITO #37` → dígitos `37` (no `2`).
2. Notify/Merge ya no reescriben el ciclo con el mínimo de fechas del Excel banco.
3. Apply **ya no marca** `AMORTIZACION_APLICADA` con 0 tablas si no hubo nada writable.
4. Apply ya no se bloquea a sí mismo: dry-run interno acepta estado `APLICANDO_AMORTIZACION`.
5. Merge elige asiento por tipo cuando hay varios PDF en la carpeta (evita `ABONO_ASIENTO_DUPLICADO`).
6. Asientos de prueba E2E con formato parseable (monto + cuenta en la misma línea).

---

## 7. Veredicto de producción

| Área | ¿Lista? |
|------|---------|
| Generate → Finalize → Notify → Merge | **Sí** (sandbox E2E + reintentos) |
| Amortización dry-run + apply (PAGO + ABONO + IBR) | **Sí** (6 tablas + IBR PAGO verificados) |
| Idempotencia apply / merge / generate | **Sí** |
| Reintentos Power Automate (misma URL) | **Sí** |
| Pagos adelantados → Excel bandeja | **Sí (registro)** |
| Pagos adelantados → cierre IBR en corrida futura | **No implementado** (ver §4) |
| Worker único / Generate largo | Limitación de escala conocida |
| Infra (Key Vault clientId, rotar storage, auth HTTP) | Pendiente fuera del código |
| Bancolombia punta a punta | No re-ejecutado en esta batería (mismo código/rutas) |

**Conclusión:** el flujo productivo del usuario (incluir **llenar tablas de amortización e IBR cuando corresponde**) está validado en sandbox y desplegado.  
Para go-live mañana sobre carpetas reales: apuntar env a rutas reales, confirmar `IBR_DIARIO` con tasas vigentes, y decidir §4 (adelantados futuros).

Checklist go-live:

1. Variables de entorno → rutas reales (no sandbox).
2. `IBR_DIARIO.xlsx` con rangos de tasas del periodo.
3. `CORREOS.xlsx` con remitente/receptores reales.
4. Controles por banco creados (`setup/merge-control-workbook`).
5. Power Automate: una acción = un endpoint, reintento = misma llamada.
6. Primera corrida real con un banco y pocos créditos, revisar las 6 tablas + IBR.
