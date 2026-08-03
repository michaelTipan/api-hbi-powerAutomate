# Deploy sandbox — UX in-app review/asientos (post R0–R3)

**Fecha:** 2026-08-03  
**Decisión:** SANDBOX UI IN-APP UX REDESPLEGADO  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `d7da479` — `fix(ui): priorizar revisión y asientos in-app sobre SharePoint` (incluye `9065f5a` fix:botones + R0–R3) |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-inapp-ux-d7da479.zip` |
| SHA-256 | `651FDDE3F5F321D96A1094391E98BC8331797702802130A74301F38354572422` |
| Build live | `u4-rc-sandbox-ui-enabled-d7da479` |
| Bundle SPA | `index-BppSfKSa.js` |
| Deploy | OneDeploy `type=zip&clean=false&restart=true` HTTP 200 |

## Qué corrige vs `b331bc7`

R0–R3 ya estaban en Azure con flags ON, pero el operador seguía en SharePoint porque:

1. Copy de Generate / estado / guidance pedía abrir Excel y `Procesar = SI`
2. «Abrir archivo de revisión» y carpetas ASIENTOS competían con los paneles
3. Paneles «Revisión del lote» / «Cargar asientos» quedaban debajo del CTA SharePoint-first
4. Carga de asientos sin ítems listados no ofrecía formulario manual

Ahora: paneles bajo el CTA de fase, copy UI-first, sin Abrir Excel ni carpetas ASIENTOS con R1/R3, carga manual de asientos, job Generate apunta al detalle UI.

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` | `u4-rc-sandbox-ui-enabled-d7da479`, sandbox, ui_enabled |
| bootstrap | `review_edit_allowed` + `asientos_upload_allowed` = true |
| SPA | strings «Revisión del lote», «Cargar asientos», «Carga manual» |
| flags `.env` | `UI_REVIEW_EDIT_ENABLED=true`, `UI_ASIENTOS_UPLOAD_ENABLED=true` |
| paths-probe | **16/16** ok, `active_environment=sandbox`, contabilidad disabled |

## Rollback

Redeploy ZIP `azure-deploy-u4-rc-sandbox-ui-enabled-review-asientos.zip` (build `b331bc7`) o regenerar desde ese commit.
