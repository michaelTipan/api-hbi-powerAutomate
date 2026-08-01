# U4-UX — cierre smoke sandbox

**Fecha:** 2026-07-31  
**Rama:** `integration/performance-and-ui`  
**HEAD:** `57a9e46e07901262c5c6bad94a05358a60472f8b`  
**ZIP:** `D:\CMC\HBI_Capital\azure-deploy-u4-ux-candidate.zip`  
**SHA-256:** `8826F1DD5383A52456CCB35BA636B8B785E7E8FF2085F71C2538CB0F0530649F`  
**Deploy:** Kudu VFS extract + OneDeploy `publish?type=static&restart=true`  
**Rollback:** no usado (ZIP U3-D enabled disponible)

## Proceso

| Campo | Valor |
|-------|--------|
| Banco | `banco_bancolombia` |
| ProcessKey live | `payment-validation\|banco_bancolombia\|2026-07-31\|c217f87c-38cf-4853-a7e4-27304f2dca22` |
| Control inicial | `REVISION_CREADA` / `IsActive=true` |
| Control final | `FINALIZADO` |

## Backup Excel

Graph vía App Service (`item-content` + API key), no `path-content` GET.

- Path: `…/01 REVISION/validacion_pagos_banco_bancolombia_2026-07-31_c217f87c-….xlsx`
- SHA-256: `42E67A080D16A097155867ACE2D63AFE28A7381E3381741565E1957189234B6E`
- eTag: `{F2E07FDC-0887-421C-AF6C-7385ADE10926},4`
- Local: `D:\CMC\HBI_Capital\_work\u4_ux_smoke\review_backup\`

## Errores introducidos

1. `Distribucion_Pagos` fila 4 `Estado Pago`: `ATRASADO` → `PAGADO_PRUEBA`
2. fila 5 `Validar Pago`: `SI` → `TALVEZ`
3. `Control!Procesar`: `NO` → `SI` (para pasar el gate y ejercer validaciones de fila)

## Finalize fallido (multi-error)

- Job: `9b2f6675-8a09-403b-86be-436646f993a7`
- Doble clic: **409** `finalize_busy`
- Outcome: failed / `multiple_review_errors`
- Control permanece `REVISION_CREADA`
- `operational_issues` = 2 (p. ej. `invalid_estado_pago` fila 4 + otro punto de fila)
- Panel: título «La revisión requiere correcciones.»
- Dashboard: **Requieren atención** (`CORRECCION_REQUERIDA`)

## Persistencia

| Paso | Resultado |
|------|-----------|
| Tras polling | 2 issues visibles |
| Reload detalle | OK |
| Logout/login | OK |
| Restart static | OK (`PERSIST_OK=true`) |
| Jobs | sin job fantasma adicional por restart |

## Corrección + reintento

- Preparación controlada: filas `NORMAL` + `Validar=NO` + observación (sin tocar Fecha/Monto/Crédito/ID)
- Job éxito: `e89e6a66-d5f6-4bb4-80d1-c4ab9fe290e1` **completed**
- Control → `FINALIZADO`
- Histórico + Asientos_Pendientes creados
- `operational_issues` vacío
- `available_actions.notify.allowed=true`
- **Notify / Merge / amortización: no ejecutados**

## Regresiones

- SPA bundle `index-ZffpIhze.js` (U4)
- Bogotá `AMORTIZACION_APLICADA` / `COMPLETADO` intacto
- `/graph/diagnostics` sin key → 401; con key → 200
- Correos nuevos: 0
- Escrituras financieras (tablas amortización): 0
- Producción / push / merge: 0

## Notas

- Tras `FINALIZADO` sin Notify, `operational_status` puede ser `DESCONOCIDO` (gap menor de proyección; Notify queda disponible).
- Accesibilidad/responsive: validado en build local + tokens/contraste medidos; smoke sandbox centrado en recuperación/API.

Evidencia: `D:\CMC\HBI_Capital\_work\u4_ux_smoke\`
