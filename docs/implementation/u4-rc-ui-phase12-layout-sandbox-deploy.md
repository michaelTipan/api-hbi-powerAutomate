# Deploy sandbox — UI Fase 1+2 + layout fechado (id8)

**Fecha:** 2026-08-02  
**Decisión:** SANDBOX UI PHASE1+2 LAYOUT DESPLEGADO  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `366fef2` — `feat(sharepoint): layout fechado YYYY/MM/día e id corto de 8` |
| Incluye | Fase 1 shell/Historial (`7344ec2`), Fase 2 archivo JSON (`dd7d957`), regenerar/Generate tras completado (`83fbee8`) |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-phase12-layout.zip` |
| SHA-256 | `416654C617E218FBEECE0FDF7725369FF6E62ED43338D1E5FB4C0FEC270AEC8F` |
| Build live | `u4-rc-sandbox-ui-enabled-366fef2` |
| Bundle | `index-DL3FlF7Z.js` / `index-Cd6xcT9h.css` |
| Deploy | OneDeploy `69d3b9ed-…` · `POST /api/publish?type=zip&clean=false&restart=true` → HTTP 200 (~163 s) |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_ui_phase12_layout\` |

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK (`u4-rc-sandbox-ui-enabled-366fef2`) |
| bootstrap writes/finalize/notify/merge/amort | OK (true) · `local_session` · sandbox |
| paths-probe | OK 16/16 · `ACTIVE_ENVIRONMENT=sandbox` · rutas **PRUEBAS** |
| Contabilidad | disabled |
| `/app/` + SPA | 200 · bundles arriba |
| OpenAPI | `/api/ui/v1/process-history` (+ detail) presente |
| Código en wwwroot | `dated_artifact_layout.py` + `SHORT_PROCESS_ID_LEN = 8` |
| `.env` | `PAYMENT_VALIDATION_ARCHIVE_FOLDER=90…/04 ARCHIVO PROCESOS` |
| Jobs | **0 → 0** (preservados; sin wipe) |

## Qué validar manualmente (operador)

En `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net/app/`:

1. Login → Panel (Nuevo proceso inline) + Historial (sin botón crear).
2. Flujo de prueba en sandbox: Generate → Finalize → Notify → Merge → Apply.
3. Confirmar rutas nuevas bajo `YYYY/MM/YYYY-MM-DD/` + id8 en HISTORICO, correos, trazabilidad, logs y `04 ARCHIVO PROCESOS`.
4. Control y `01 REVISION` siguen planos con UUID completo.

## Rollback (no ejecutado)

- Previo live: build `u4-rc-sandbox-ui-enabled-eb46f90`  
  ZIP regenerar Errores: `azure-deploy-u4-rc-sandbox-ui-enabled-regenerate-errores.zip` SHA `DC2C3C5B…`
