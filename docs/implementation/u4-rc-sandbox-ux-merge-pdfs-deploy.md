# U4-RC — Deploy sandbox UX (modales, spinner, multi-PDF Merge)

**Fecha:** 2026-08-01  
**Decisión:** DESPLEGADO EN SANDBOX  
**Push/merge:** cero · **Producción:** cero  
**Graph mutable:** 0 · **SharePoint modificado:** 0  
**Mutaciones UI (Generate/Notify/Merge/Apply):** no ejecutadas

## Artefacto

| Campo | Valor |
|---|---|
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-ux-merge-pdfs.zip` |
| SHA-256 | `593F8BEB531E39E4724735D528808B89010EC9A788F000AC3F492876916A7005` |
| Build live | `u4-rc-sandbox-ui-enabled-ux-merge-pdfs-007480b` |
| Bundle | `index-Db7veR5y.js` / `index-C_C_SqK8.css` |
| Deploy | OneDeploy `f81512a7-…` status=4; `clean=false&restart=true` HTTP 200 (~47 s) |
| EnvSource | `.env` live predeploy (flags UI + `UI_NOTIFY_SANDBOX_TO` preservados) |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_ux_merge_pdfs\` |

## Incluye

- Modales sin avisos redundantes «no se ejecutará consolidación/amortización…»
- `ProcessingBanner` mientras job `queued`/`running` o sync
- PDFs Merge desde `outputs[]` (`merge_pdf` / `merge_pdf:N`; mismo crédito → `· Pago N`)
- Solo `.pdf`; manifiesto JSON excluido; sin duplicar `primary_output_path`
- Enlaces conservados aunque falte `web_url`
- Carpetas ASIENTOS: mensaje claro sin botón «(no disponible)»
- Títulos «Documentos por fase» con mayor jerarquía

## Gate post-deploy (solo lectura)

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK (`u4-rc-sandbox-ui-enabled-ux-merge-pdfs-007480b`) |
| bootstrap sandbox + `Entorno de validación` + recipients | OK |
| `.env` sha256 pre/post | `F571E084…E76D35` (igual) |
| Contabilidad | disabled |
| Código en disco (`manifest_outputs`, labels) | OK |
| SPA bundle nuevo + copy Crédito / carpeta | OK |
| Mutaciones UI / Graph | 0 |

## Smoke manual pendiente (operador)

En `/app/` → proceso Bancolombia → **Documentos por fase**:

1. Deben verse **todos** los PDFs consolidados reales.
2. **Ningún** enlace debe abrir el manifiesto JSON.
3. Si un crédito tiene varios PDFs: etiquetas `· Crédito X · Pago N`.

Sin Generate / Notify / Merge / Apply salvo autorización adicional.

## Rollback (no ejecutado)

- Previo: `azure-deploy-u4-rc-sandbox-ui-enabled-consolidated.zip` SHA `1EDD4A1A…F94DB688` build `u4-rc-sandbox-ui-enabled-consolidated`
