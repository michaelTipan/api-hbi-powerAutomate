# Casos stress E2E — API HBI (sandbox) 2026-07-28

> **HISTÓRICO.** Los scripts one-shot (`scripts/_stress_e2e_run.py`,
> `_stress_e2e_continue.py`, helpers que editaban `Distribucion_*`) fueron
> **eliminados** en el cleanup v3. Este documento conserva el plan de datos de
> aquella corrida; no hay runner activo en el repo.

Fecha: **2026-07-28**  
App Service: `app-hbiauto-prod-001`  
Process date: `2026-07-28`  
Banco: **Banco Bogotá**  
Artefactos (época): `_work/stress_e2e/`

## Objetivo (entonces)

Batería nueva sobre montos/fechas de extracto con regla **max(fecha_limite)**.

Workbook operativo actual: hoja **`Aplicacion_Pagos`** (schema v3), no
`Distribucion_Pagos` / `Distribucion_Abonos`.
