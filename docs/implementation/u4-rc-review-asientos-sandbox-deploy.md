# Deploy sandbox — Review in-app + asientos (R0–R3)

**Fecha:** 2026-08-03  
**Decisión:** SANDBOX UI REVIEW+ASIENTOS DESPLEGADO  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `b331bc7` — `test(ui): corregir regresiones y validar flujo operador R0-R3` (+ R0–R3 + CTA únicos) |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-review-asientos.zip` |
| SHA-256 | `048697E408C546345DE1925F4ADA172EC273655A1AADA4A09AE7C9113B8A80F9` |
| Build live | `u4-rc-sandbox-ui-enabled-b331bc7` |
| Bundle SPA | `index-BOG1e5fg.js` / `index-CkYx7ik_.css` |
| Deploy | OneDeploy `5fd8c14b-…` status=4 complete; `type=zip&clean=false&restart=true` HTTP 200 |

## Qué incluye

- R0: lectura tipada del Excel de revisión en el detalle
- R1: edición + preflight (`UI_REVIEW_EDIT_ENABLED=true`)
- R2: Finalize atómico desde la SPA
- R3: upload PDF asientos por `id_pago`+`credito` (`UI_ASIENTOS_UPLOAD_ENABLED=true`)
- CTA únicos: Regenerar / Abrir revisión una sola vez en la fase activa; sin Abrir en tarjetas del panel

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK (`u4-rc-sandbox-ui-enabled-b331bc7`) |
| bootstrap | `writes/finalize/merge/notify/review_edit/asientos_upload=true`, sandbox |
| `.env` | `ACTIVE_ENVIRONMENT=sandbox`, rutas PRUEBAS, contabilidad vacía, flags R1/R3 true |
| `/graph/diagnostics/paths-probe` | **16/16** ok, `active_environment=sandbox` |
| `/app/` SPA | 200 · bundles arriba |

## Rollback

Redeploy ZIP previo catálogo: `azure-deploy-u4-rc-sandbox-ui-enabled-document-catalog.zip` (build `3db1a91`) o regenerar desde ese commit.
