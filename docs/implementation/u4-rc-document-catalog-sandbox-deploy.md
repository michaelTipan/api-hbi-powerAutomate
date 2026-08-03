# Deploy sandbox — Catálogo documentos (drawer)

**Fecha:** 2026-08-02  
**Decisión:** SANDBOX UI DOCUMENT CATALOG DESPLEGADO  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `3db1a91` — `feat(ui): catálogo drawer para PDFs y tablas sin saturar el detalle` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-document-catalog.zip` |
| SHA-256 | `6F352BA0CFA23DD7460166912A9AAC8FD61D3354E0F0165C96070114068F5281` |
| Build live | `u4-rc-sandbox-ui-enabled-3db1a91` |
| Bundle SPA | `index-BtmwbCWv.js` / `index-BXen-K69.css` |
| Deploy | ZipDeploy Kudu aceptado · app reiniciada |

## Qué incluye

- Resumen + modal catálogo para PDFs consolidados (N≥2) y tablas de amortización
- Sección «Archivos del proceso» + campo aditivo `document_groups`
- PDF correo / Excel lote sin cambio (botones 1:1)
- Carpetas ASIENTOS solo en Merge activo
- Persistencia de tablas amort. en JSON de archivo al Apply OK
- Doc diseño: `docs/implementation/u4-rc-document-catalog-drawer.md`

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK (`u4-rc-sandbox-ui-enabled-3db1a91`) |
| bootstrap writes | OK (`writes=True`, sandbox) |
| `/app/` SPA | 200 · bundles arriba |

## Rollback

Redeploy ZIP previo fase1+2 layout (`azure-deploy-u4-rc-sandbox-ui-enabled-phase12-layout.zip`, build `366fef2`) o regenerar desde commit anterior a `3db1a91`.
