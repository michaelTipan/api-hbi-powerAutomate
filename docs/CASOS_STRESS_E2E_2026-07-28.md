# Casos stress E2E — API HBI (sandbox) 2026-07-28

Fecha: **2026-07-28**  
App Service: `app-hbiauto-prod-001`  
Process date: `2026-07-28`  
Banco: **Banco Bogotá**  
Artefactos: `_work/stress_e2e/`

## Objetivo

Batería **nueva** (sin reusar GEOEXCON 231/254, EQUINORTE 258/264/265, AGRECAR #37).
Montos/fechas de extracto con regla **max(fecha_limite)** (`GENERATE_EXTRACT_SELECTION_V2`).

## Plan de datos (25 filas)

| Tag | Cantidad |
|-----|----------|
| pago_adelantado | 8 |
| pago_atrasado (~18% de PAGOS principales) | 2 |
| pago_y_abono | 3 |
| abono_capital | 4 |
| abono_mora | 3 |
| errores usuario (cliente fantasma / ACIMOR / MINCIVIL / sin extracto) | 4 |
| pago_adelantado_extra | 1 |

**Créditos nuevos:** 215, 32, 92, 94, 224, 284, 296, 150, 88, 71  
**Clientes:** A&M CONSTRUCOL, DIEGO RAMIRO…, G&J INGENIERIA, INDUCAB, AGRECAR (+ negativos)

Extractos ganadores: `_work/stress_e2e/extract_winners.json`.

## Resultados por endpoint

| Paso | Resultado |
|------|-----------|
| Health / diagnostics | OK |
| Merge demasiado pronto | Job en cola (luego falla control / no corrompe) |
| Generate | **OK** — 25 transacciones, 5 errores hoja, 18 pagos / 7 abonos detectados; ~14.3 min |
| Generate ×2 | **Idempotente** `already_generated: true` |
| Notify antes de Finalize | **Bloqueado** `control_not_ready_for_notify` (mensaje claro) |
| Finalize | **OK** — 21 validados (14 pagos + 7 abonos) |
| Notify | **OK** (correo + PDF) |
| Amort antes de Merge | **Bloqueado** `control_not_ready_for_dry_run` |
| Ensure asientos | OK |
| Merge sin asientos | skip todos (`asiento_contable_not_found`) — esperado |
| Merge con asientos | **OK** — `outputs_count=21`, `skipped=0` |
| Merge ×2 | **Idempotente** `already_merged: true` |
| Amort dry-run | OK `can_apply=true` |
| Amort apply | **Parcial** — 13 aplicados, 8 errores, 7 tablas subidas → `AMORTIZACION_PARCIAL` |
| Amort apply ×2 | **Bloqueado** (antes del fix): `AMORTIZACION_PARCIAL` no estaba en `AMORTIZATION_RUNNABLE_STATES` |

## Reglas de negocio observadas

- Tipos PAGO / PAGO Y ABONO / ABONO CAPITAL / ABONO MORA transitaron Generate→Merge.
- IBR escrito en tablas G&J/A&M donde correspondía (`ibr_escritos` > 0).
- INDUCAB atrasados aplicaron sin IBR vigente (0 `ibr_escritos`) — coherente si no hay tasa.
- Asientos movidos a PROCESADOS: 13.

## Bugs encontrados y fixes (código local)

1. **`MergedCell` read-only** en tablas DIEGO (#32, #92, #94) → `TABLE_APPLY_FAILED`.  
   Fix: `_set_cell_value` escribe en ancla del merge (`amortization_workbook.py`). Test: `tests/test_merged_cell_write.py`.

2. **Reintento tras `AMORTIZACION_PARCIAL` bloqueado** pese a documentación.  
   Fix: añadir `AMORTIZACION_PARCIAL` a `AMORTIZATION_RUNNABLE_STATES`.

3. **ProcessKey/ProcessDate reescritos a min(fecha banco)** al llamar Notify con
   `historical_file_path` (Power Automate / E2E): no se leía el control y se
   reconstruía el key con `2025-09-15` (AGRECAR).  
   Fix: en override de histórico, cargar `ProcessKey` desde el control del banco.

## Scripts

- `scripts/_stress_inspect_extracts.py` — ganadores por max fecha límite  
- `scripts/_stress_e2e_run.py` — pipeline completo  
- `scripts/_stress_e2e_continue.py` — retoma desde finalize  

## Pendiente operativo

- **Deploy** de fixes MergedCell + runnable PARCIAL a `app-hbiauto-prod-001`.  
- Reintentar Amort apply sobre el proceso parcial para cerrar DIEGO.  
- Decidir si ProcessDate del control debe imponerse siempre sobre min(fecha banco).
