# U4-RC — Production readiness (implementación)

## Cambios de código (sesión)

### B1 / B2 — Proyección operativa

- Nuevo `OperationalStatus`: `PENDIENTE_NOTIFICACION`
- `derive_operational_status`: matriz completa; `DESCONOCIDO` solo estado corrupto
- `derive_operational_guidance`: título + mensaje + referencia técnica
- Campos DTO: `operational_title`, `operational_message`, `technical_status_reference`
- `FINALIZADO` + Notify no iniciado → mensaje «La revisión fue finalizada correctamente.»
  y next action «Enviar validación.»
- Dashboard bucket: activos (en curso), no completado ni error
- Tests: `tests/test_ui_operational_status_matrix.py`

### B3 — Multi-error Finalize

- Varios issues por fila (celdas contables)
- `amount_mismatch` por ID Pago con ubicación
- Acumulación de issues de `Distribucion_Abonos`
- Raise conjunto antes de Graph writes
- Tests ampliados en `tests/test_finalize_multi_error_collection.py`

### B4 — Accesibilidad

- `frontend/src/pages/a11y.pages.test.tsx` (Login, Dashboard, detalle ± issues, 5 modales)
- Fix tabs: quitar `aria-pressed` incompatible con `role=tab`
- Fix heading-order: cards de banco/proceso usan `h2`
- `color-contrast` deshabilitado solo en jsdom (documentado; validar en live)

### B6 — Copy

- Modal Merge: «Soportes:» en lugar de «Readiness:»
- Mocks sin jerga Generate/Finalize/Notify/Merge en textos visibles

## Pendiente para declarar LISTO

1. Deploy sandbox del ZIP U4-RC — **hecho** (`azure-deploy-u4-rc-sandbox.zip`);
   SPA `index-DyDwMASQ.js`; live `FINALIZADO` → `PENDIENTE_NOTIFICACION` verificado.
2. **Incidente deploy:** `deploy-kudu-vfs` no borraba `.env` antes del unzip; el
   App Service quedó un rato con `ACTIVE_ENVIRONMENT=production` (UI fail-closed
   404). Restaurado sandbox (paths Comware PRUEBAS). Fix: `rm .env` en el script.
3. Responsive live + capturas en `_work/u4_rc/responsive/`
4. E2E Bogotá completo + Bancolombia ≥ Finalize+Notify
5. Casos de error E2E
6. Production overlay read-only + paths-probe (sin mutaciones)
7. ZIP production-candidate + SHAs + manifest
8. Rollback plan documental
9. Suite completa pytest + npm + build (parcial ya verde)

## Producción tocada

Mutaciones/SharePoint/Contabilidad/Notify reales: **cero**.
Hubo ventana con overlay `ACTIVE_ENVIRONMENT=production` en runtime por `.env`
stale; restaurado a sandbox antes de E2E. Sin escrituras productivas detectadas
en esa ventana (UI apagada por fail-closed).

