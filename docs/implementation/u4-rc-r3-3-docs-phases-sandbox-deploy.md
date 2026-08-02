# U4-RC-R3.3+ — Documentos por fase (horizontal) en sandbox

**Fecha:** 2026-08-01  
**Decisión:** DOCS-PHASES DESPLEGADO EN SANDBOX  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| Código (working tree) | UI docs-phases + anti-fragilidad 502 (sin commit dedicado) |
| Tip git al empaquetar | `a98f7bb` (+ cambios locales) |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-docs-phases.zip` |
| SHA-256 | `FC5B98D6C0B79EF062765A666F454084761C2E2628B0BF22FBA46B6E0950CD47` |
| Build live | `u4-rc-sandbox-ui-enabled-docs-phases` |
| Bundle | `index-DOoGXJ8q.js` / `index-CSvq-6DJ.css` |
| Deploy | OneDeploy `99907003-…` status=4; `clean=false&restart=true` |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_r33_continuity\deploy_docs_phases\` |

## Cambios UI incluidos

- Título **Documentos por fase** (sin «Sus»).
- Eliminada frase «Solo consulta: vuelve a detectar…».
- Documentos en columnas horizontales (`phase-docs-row`).
- Enlaces sin duplicar entre fases.
- Stepper: Revisar archivo / Cerrar revisión / Enviar validación / Generar PDF / Aplicar amortización.

## Gate

- sandbox / PRUEBAS / Contabilidad disabled
- jobs **18 → 18**
- bootstrap: `ui_enabled/writes/finalize/merge/amortization=true`, `notify_allowed=true`, recipients configurados
- SPA: frases nuevas presentes; «Sus documentos» y «Solo consulta…» ausentes; CSS `phase-docs-row`
- `UI_NOTIFY_SANDBOX_TO` restaurado desde ZIP r33-phases (el overlay vacío lo había borrado en un intento intermedio)

## Nota operativa

Al empaquetar con `sandbox-ui-enabled.env`, **no** dejar `UI_NOTIFY_SANDBOX_TO` vacío si el sandbox ya tenía destinatarios: reinyectar el valor del ZIP anterior o del `.env` remoto.

## Rollback (no ejecutado)

- Previo: `azure-deploy-u4-rc-sandbox-ui-enabled-r33-phases.zip` SHA `71C24C1A…`
