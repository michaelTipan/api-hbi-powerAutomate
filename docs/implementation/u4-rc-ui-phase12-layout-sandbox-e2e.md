# E2E sandbox — UI Fase 1+2 + layout fechado (id8)

**Fecha:** 2026-08-02  
**Decisión:** E2E SANDBOX OK — rutas fechadas + archivo de procesos validados  
**Entorno:** `ACTIVE_ENVIRONMENT=sandbox` · rutas **PRUEBAS** · Contabilidad disabled  
**Build live:** `u4-rc-sandbox-ui-enabled-366fef2`  
**Push/merge/prod:** cero

## Proceso ejecutado

| Campo | Valor |
|---|---|
| Banco | `banco_bogota` |
| ProcessKey | `payment-validation\|banco_bogota\|2026-08-02\|1cbfac9c-90d8-4b4c-b89f-1e011d41cd5a` |
| id8 | `1cbfac9c` |
| Flujo | Generate (force) → prepare review → Finalize → Notify → Merge → Apply |
| Resultado | `AMORTIZACION_APLICADA` / `COMPLETADO` |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_ui_phase12_layout\e2e\` |

## Gate de entorno (antes y después)

- Local + live: sandbox / `03 COMWARE PRUEBAS-…`
- paths-probe 16/16 · Contabilidad disabled
- bootstrap writes/finalize/notify/merge/amort = true
- `/app/` 200

## Rutas fechadas verificadas (todas bajo PRUEBAS)

| Artefacto | Path |
|---|---|
| HISTORICO cartera | `…/03 HISTORICO/2026/08/2026-08-02/cartera_validada_banco_bogota_2026-08-02_1cbfac9c.xlsx` |
| HISTORICO soporte | `…/03 HISTORICO/2026/08/2026-08-02/soporte_asientos_contables_banco_bogota_2026-08-02_1cbfac9c.xlsx` |
| PDF correo | `…/04 CORREOS ENVIADOS/2026/08/2026-08-02/ABONOS BANCO BOGOTA 2026-08-02_1cbfac9c.pdf` |
| Manifiesto merge | `…/01 TRAZABILIDAD/2026/08/2026-08-02/merge_manifest_banco_bogota_2026-08-02_1cbfac9c.json` |
| Archivo procesos | `…/04 ARCHIVO PROCESOS/2026/08/2026-08-02/proceso_banco_bogota_2026-08-02_1cbfac9c.json` |

## Intactos (como se diseñó)

- Revisión plana + UUID completo:  
  `…/01 REVISION/validacion_pagos_banco_bogota_2026-08-02_1cbfac9c-90d8-4b4c-b89f-1e011d41cd5a.xlsx`
- Control single-slot (sin multi-fila)

## UI / historial

- `GET /api/ui/v1/process-history/{process_key}` → 200, `source=archive`, `read_only=true`
- Links SharePoint del histórico/PDF/soporte resueltos con `web_url`
- SPA `/app/` 200 tras el flujo

## Notas operativas del E2E

1. Generate con `force_regenerate` porque había lote `REVISION_CREADA` sin Excel.
2. Hoja Errores del Excel de revisión se vació (solo encabezado) para poder Finalize.
3. Tras Notify, la proyección puede quedar unos segundos en `SINCRONIZANDO`; el path del PDF ya viene en `result_summary.email_pdf_path`.
