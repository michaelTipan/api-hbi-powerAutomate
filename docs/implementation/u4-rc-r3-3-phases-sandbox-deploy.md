# U4-RC-R3.3+ — Detalle por fases desplegado en sandbox

**Fecha:** 2026-08-01  
**Decisión:** DETALLE POR FASES DESPLEGADO EN SANDBOX  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `37acf3e9d1342fef48e42871c8e167bb78163e8e` |
| Commit | `feat(ui): detalle de proceso por fases sin secciones técnicas` |
| Incluye también | `4161db2` legibilidad botones/hover tarjetas |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-r33-phases.zip` |
| SHA-256 | `71C24C1A5E43BF8E1710062D3E1096C800E3AE000767FED6903D15B953F6BCFD` |
| Build live | `u4-rc-sandbox-ui-enabled-r33-37acf3e` |
| Bundle | `index-B19NftQJ.js` / `index-Dg_oePbg.css` |
| Deploy | OneDeploy `dfdbdcfe-…` status=4; `clean=false&restart=true` |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_r33_continuity\postdeploy_phases\` |

## Gate

- sandbox / PRUEBAS / Contabilidad disabled / paths 16/16
- jobs **17 → 17**
- UI enabled + writes/merge true
- SPA: stepper «Progreso del proceso», «Sus documentos por fase»
- Sin «Historial de intentos», «Detalles técnicos», «Abrir control del proceso»
- Sin palabra «secretaría» en bundle; `secretary_file` solo como rel técnico
- Detalle Bancolombia: links operativos sin `control` / `execution_log`
- Botones de acción: texto blanco (`color:#fff`) sobre `--accent`

## Rollback (no ejecutado)

- Previo: `azure-deploy-u4-rc-sandbox-ui-enabled-r33-continuity.zip` SHA `72D7F884…`
- CSRF: `azure-deploy-u4-rc-sandbox-ui-enabled-csrf-fix.zip` SHA `834A13F8…`
