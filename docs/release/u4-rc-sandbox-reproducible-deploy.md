# Plan de deploy futuro — U4-RC sandbox reproducible (NO EJECUTAR)

Estado previo live: sandbox Graph OK, UI off, U4-RC parcial. Esta guía es para
**después** de tener los ZIPs R1 validados en Docker.

## Principios

1. No OneDeploy `type=static` a ciegas.
2. No confiar solo en `.env` de disco: verificar `paths-probe` + `bootstrap` + `build`.
3. No `production-candidate`.
4. No clean global de `wwwroot`.
5. Preservar `.payment_validation_jobs`.
6. Rollback inmediato si health/bootstrap/paths-probe fallan.

## Preservación de jobs (procedimiento)

1. Inventariar `wwwroot/.payment_validation_jobs` (conteo + sample job_ids).
2. Desplegar por ZipDeploy/OneDeploy del ZIP R1 **sin** borrar el directorio de jobs
   (el paquete no lo incluye; el unzip no debe usar mode delete-all).
3. Si se usa VFS sync, excluir explícitamente `.payment_validation_jobs`.
4. Post-deploy: listar de nuevo y comparar conteos.
5. Nunca `rm -rf /home/site/wwwroot`.

## ETAPA 1 — UI readonly

1. Backup/inventario jobs.
2. `switch-env.ps1 -Target sandbox-ui-readonly` (local pack).
3. Build ZIP readonly (`-EnforceSandboxUi -PythonPackagesSource … -SkipFrontendBuild` si dist listo).
4. Deploy ZIP (cuando se autorice).
5. Recycle controlado (Portal/`az webapp restart` preferible a static a ciegas).
6. Verificar:
   - `GET /health` → build `u4-rc-sandbox-ui-*`, environment sandbox, ui_enabled true
   - `GET /api/ui/v1/bootstrap` → 200, writes disabled
   - `GET /app/` → 200
   - `paths-probe` → sandbox + PRUEBAS
   - POST mutables UI → 403
7. Rollback: redeploy ZIP sandbox previo conocido + reafirmar `.env` sandbox.

## ETAPA 2 — UI enabled

Solo si Etapa 1 verde:

1. Deploy ZIP `sandbox-ui-enabled`.
2. Verificar sandbox + bootstrap writes true.
3. Smoke controlado Generate→… solo en PRUEBAS.
4. No tocar Contabilidad productiva.

## Prohibido

- Push/merge sin revisión.
- Mutar SharePoint productivo.
- Usar ZIP con backslashes.
- Subir `.pyd` Windows.
