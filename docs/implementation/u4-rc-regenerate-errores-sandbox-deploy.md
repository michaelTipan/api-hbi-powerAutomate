# Deploy sandbox — regenerar Errores + UX cierre + Notify sin encabezado quemado

**Fecha:** 2026-08-02  
**Decisión:** SANDBOX UI ENABLED DESPLEGADO  
**Push/merge:** cero · **Producción:** cero

## Artefacto

| Campo | Valor |
|---|---|
| Commit | `eb46f90` — `feat(ui): regenerar por hoja Errores y cerrar UX al completar` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-regenerate-errores.zip` |
| SHA-256 | `DC2C3C5B243951659804DB514FE3DDF5B0DF104F715D478C54C134385CDD04C9` |
| Build live | `u4-rc-sandbox-ui-enabled-eb46f90` |
| Deploy | OneDeploy `POST /api/publish?type=zip&clean=false&restart=true` → HTTP 200 |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_regenerate_deploy\` |

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK (`u4-rc-sandbox-ui-enabled-eb46f90`) |
| bootstrap writes/finalize/notify/merge/amort | OK (true) · `local_session` · sandbox |
| paths-probe | OK 16/16 · `ACTIVE_ENVIRONMENT=sandbox` · rutas **PRUEBAS** |
| Contabilidad | disabled |
| Jobs | **27 → 27** (preservados) |

## Incluye

- Regenerar por hoja Errores (`force_regenerate`) + aviso temprano en UI
- Modal éxito amortización + ocultar tarjeta al COMPLETADO
- Notify sin encabezado «Reporte de pagos (Banco Bogotá):»
