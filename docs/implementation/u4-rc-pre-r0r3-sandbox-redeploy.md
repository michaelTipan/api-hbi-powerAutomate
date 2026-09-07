# Deploy sandbox — pre R0–R3 (`integration/performance-and-ui`)

**Fecha:** 2026-08-03  
**Decisión:** SANDBOX ROLLBACK/DEPLOY a tip pre-R0–R3  
**Push/merge/prod:** cero

## Artefacto

| Campo | Valor |
|---|---|
| Rama | `integration/performance-and-ui` |
| HEAD | `b7dcc03` — catálogo de documentos (antes de R0) |
| Worktree | `D:\CMC\HBI_Capital\wt-operator-web-ui` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-pre-r0r3-b7dcc03.zip` |
| SHA-256 | `0D239B2AE3E4DCC2D30B1384DFC1B58A0B1F170022F0DE275CFFCAFBA6DC7026` |
| Build live | `u4-rc-sandbox-ui-enabled-b7dcc03` |
| Bundle SPA | `index-BtmwbCWv.js` |
| Deploy | OneDeploy `type=zip&clean=false&restart=true` HTTP 200 |

## Gate

| Check | Resultado |
|---|---|
| `/health` | sandbox + `u4-rc-sandbox-ui-enabled-b7dcc03` |
| bootstrap | writes/finalize/notify/merge/amort = true; **sin** `review_edit` / `asientos_upload` (aún no existían) |
| paths-probe | status ok, active=sandbox (15/16 checked; sin fallos required) |
| Overlay | `config/environments/sandbox-ui-enabled.env` + pack `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env` |

## Nota

Esto **quita** del App Service las mejoras R0–R3 / UX in-app. Para volver a ellas: redeploy desde `feat/ui-in-app-review-and-asientos` (p. ej. `d7da479` / docs en esa rama).
