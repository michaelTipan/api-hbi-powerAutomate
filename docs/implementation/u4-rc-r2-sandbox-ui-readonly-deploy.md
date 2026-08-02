# U4-RC-R2 — Deploy controlado UI readonly (sandbox Azure)

**Decisión:** UI READONLY SANDBOX DESPLEGADA  
**Fecha:** 2026-08-01  
**HEAD local:** `6fc89a2`  
**Push/merge:** cero  

## Artefacto

- ZIP: `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-readonly.zip`
- SHA-256 completo:
  `B56A9ACD9EB0D5B84B20082BA593CC1B8833E03ED9257AA8CD71A85398918548`
- Método: `POST {SCM}/api/publish?type=zip&clean=false&restart=true`
- Resultado deploy: HTTP 200 (~200 s)

## Preflight (antes)

- `/health` 200 (build legacy `errores-detalle-archivos-20260730`)
- `paths-probe` sandbox + PRUEBAS; Contabilidad disabled
- `/app/` 404; `/api/ui/v1/bootstrap` 404

## Post-deploy (worker)

- `/health`: `u4-rc-sandbox-ui-readonly-c100e02`, `environment=sandbox`, `ui_enabled=true`
- `/api/ui/v1/bootstrap` 200: `SANDBOX / PRUEBAS`, writes/finalize/notify/merge/amortization = false, `auth_mode=local_session`
- `paths-probe`: clients
  `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- `/app/` 200; assets `index-DyDwMASQ.js` / `index-CEYMIQaf.css` 200
- OpenAPI (con API key): rutas `/api/ui/v1/*` presentes; Graph intactas
- Login `operador_hbi` 200; `/processes` 200 (0 items en este momento); `/banks` 200 (2)
- POST `/api/ui/v1/processes/generate` (probe noop) → **403** `ui_write_disabled`
- Jobs: directorio ausente antes y después (0→0); sin jobs nuevos

## Snapshot / rollback

- Evidencia: `D:\CMC\HBI_Capital\_work\u4_rc_readonly_deploy\predeploy\`
- `predeploy_manifest.json` + `critical_predeploy_local.zip`
- Rollback: **no requerido**

## Dependency lock (local, no altera el ZIP)

- `requirements.lock.txt` (repo)
- Meta: `docs/release/u4-rc-r2-dependency-lock-meta.json`
- Python 3.14.6 / pip 26.1.2; so=85 pyd=0

## Prohibiciones respetadas

Sin paquete enabled, sin production-candidate, sin operaciones de negocio,
sin Graph mutable, sin SharePoint/Contabilidad mutables, sin push/merge,
sin static marker restart, sin clean=true.
