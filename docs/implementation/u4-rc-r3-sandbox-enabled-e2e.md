# U4-RC-R3 — UI enabled + E2E sandbox (Azure)

**Decisión:** U4-RC SANDBOX FUNCIONAL COMPLETO  
**Fecha:** 2026-08-01  
**HEAD:** `6fc89a2`  
**Push/merge:** cero  

## Deploy

- Artefacto base autorizado:
  `azure-deploy-u4-rc-sandbox-ui-enabled.zip`
  SHA `D4A2990D953134F14BD5F4F01030A9BEA3FEF8FDD31A4D8A57C6310D5EB70D15`
- Método: `POST {SCM}/api/publish?type=zip&clean=false&restart=true`
- Live build: `u4-rc-sandbox-ui-enabled-c100e02`
- environment: sandbox / PRUEBAS
- Contabilidad: disabled
- Delta operativo post-deploy (documentado, no production-candidate):
  - rotación de `UI_LOCAL_PASSWORD_HASH` (password perdida del portapapeles D2);
  - `UI_NOTIFY_SANDBOX_TO=he***@gmail.com` (destinatario sandbox previo u3c1);
  - ZIP credrot local:
    `D:\CMC\HBI_Capital\_work\u4_rc_enabled_e2e\azure-deploy-u4-rc-sandbox-ui-enabled-credrot.zip`

## E2E Bogotá (aceptación completa)

ProcessKey:

`payment-validation|banco_bogota|2026-08-01|0877507c-8005-4c60-bfa1-d04f241a40ca`

| Etapa | Resultado |
|---|---|
| Generate | completed; double-click `generate_busy` 409 |
| Finalize multi-error (demo dedicada) | 2 issues operativos; persisten tras logout/login |
| Finalize corregido | completed; control FINALIZADO |
| Notify | completed; retry `already_notified` 409; 1 correo sandbox |
| Merge | completed; retry `already_merged` 409 |
| Amortización | completed; control `AMORTIZACION_APLICADA`; op `COMPLETADO`; retry `already_applied` 409 |

Evidencia: `D:\CMC\HBI_Capital\_work\u4_rc_enabled_e2e\`

## Multi-error U4-A/B

Demo adicional ProcessKey
`…|b3dc9d29-c6ba-4b3f-80c7-1e1be636a168` (luego cancelado):

- 2 `operational_issues` visibles
- `CORRECCION_REQUERIDA`
- persistencia tras refresh/login (`13_multi_errors_*.json`)

## Bancolombia

Smoke reducido: banco visible; Generate aceptado pero job falló por proceso activo histórico
`…|c217f87c-…|PENDIENTE_ASIENTOS` (cancel Graph falló). No se forzó segundo correo.

## Suites finales

- pytest: 1312 passed, 1 skipped
- frontend vitest: 56 passed
- tsc: OK
- frontend build: `index-DyDwMASQ.js` / `index-CEYMIQaf.css`

## Seguridad / alcance

- SharePoint productivo: cero
- Contabilidad: cero
- production-candidate: no
- Correos productivos: cero (solo destinatario sandbox)
- Rollback readonly: ejecutado una vez por gate prematuro de Notify vacío; luego enabled redeployed
