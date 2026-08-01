# U4 Rollback Plan

## Paquetes

| Rol | Archivo | SHA-256 |
|-----|---------|---------|
| RC productivo (candidato, **no desplegado**) | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-production-candidate.zip` | `B833FA113EE7679CFD6AF3F2171C361A9B0412072C482B878E4E4C32559899E6` |
| Sandbox final congelado | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-final.zip` | `0010D0265D052F56FBAC3C03625DC75366749693B017948E723260C029B95342` |
| HEAD código | `001f2a9` | — |

> Antes del primer deploy productivo, registrar aquí el **paquete productivo anterior** (ZIP + SHA) que esté en App Service.

## Procedimiento Kudu (obligatorio)

1. Confirmar paquete y SHA-256 localmente.
2. `deploy-kudu-vfs.ps1 -ZipPath <zip> -SkipBuild` (o flujo equivalente).
3. **Eliminar `.env` remoto antes del unzip** (`rm -rf … .env`) — fix `a992588`; sin esto puede quedar overlay stale.
4. Unzip del paquete en `/home/site/wwwroot`.
5. OneDeploy / restart.
6. Verificar:
   - `GET /health`
   - `GET /api/ui/v1/bootstrap` → `ACTIVE_ENVIRONMENT` esperado
   - Login UI
   - `GET /graph/diagnostics` y `GET /graph/diagnostics/paths-probe` (solo lectura)
7. Validación PA / humo acordada.

## Criterios de rollback

- UI fail-closed / 404 tras deploy
- `ACTIVE_ENVIRONMENT` incorrecto o rutas sandbox/prod cruzadas
- Paths-probe con fallos required
- Correos a destinatarios no autorizados
- Errores de escritura financiera inesperados

## Recuperación de control

- Restaurar control Excel desde backup `_work` / histórico SharePoint del ProcessKey afectado.
- No reaplicar amortización si el control ya está en `AMORTIZACION_APLICADA`.

## Responsable

- Operador release HBI / Comware (definir nombre al ejecutar).

## Prohibiciones

- No usar `-Force` de switch-env a producción sin `ENV_READY=true`.
- No flip del App Service sandbox a production solo para probe.
