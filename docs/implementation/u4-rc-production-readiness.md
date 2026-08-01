# U4-RC Production Readiness — Implementation

## Estado

Fases 1–2 completas en sandbox. Fase 3: overlay productivo **estático** OK;
**paths-probe live RO en runtime aislado no ejecutado** (bloqueante de
infraestructura). Fase 4: ZIP production-candidate creado (**no** desplegado),
manifest de diff y rollback documentados.

**Decisión:** NO LISTO PARA PRODUCCIÓN.

## HEAD

| Rol | Valor |
|-----|-------|
| Código congelado RC | `001f2a9` |
| Docs tip | `d1a93b2` (+ commits locales de cierre si aplica) |
| Rama | `integration/performance-and-ui` |
| Worktree | `D:\CMC\HBI_Capital\wt-integration-performance-and-ui` |
| SPA | `index-DyDwMASQ.js` |

## Suites (congelación)

| Suite | Resultado |
|-------|-----------|
| pytest | 1301 passed, 1 skipped |
| frontend vitest | 56 passed |
| `tsc --noEmit` | OK |
| `vite build` | `index-DyDwMASQ.js` |

## Incidente `.env` stale (Kudu VFS)

- **Causa:** `deploy-kudu-vfs` no eliminaba `.env` antes del unzip → overlay
  previo (production) sobrevivía al paquete sandbox.
- **Duración:** orden de minutos tras el primer deploy U4-RC; UI fail-closed (404).
- **Escrituras:** cero detectadas (UI off; Graph operable con API key).
- **Corrección:** `rm -rf … .env` en `scripts/deploy-kudu-vfs.ps1` (`a992588`).
- **Prueba del fix:** dos deploys sandbox consecutivos + bootstrap/paths-probe.
- **Prevención:** rollback y checklist exigen rm `.env` antes del unzip.

## Incidente reinicio OneDeploy `type=static` (post Fase 2)

- **Causa:** restart vía `publish?type=static&restart=true` sin subir el ZIP
  sandbox final → el runtime volvió a operar con `ACTIVE_ENVIRONMENT=production`
  mientras el disco podía quedar/restaurarse a sandbox.
- **Síntoma:** `wwwroot/.env` = sandbox (PRUEBAS) pero
  `GET /graph/diagnostics/paths-probe` = `production` y
  `GET /api/ui/v1/bootstrap` = 404 fail-closed (`local_session` solo sandbox).
- **Fail-closed:** UI deshabilitada (correcto). Paths-probe RO contra rutas
  productivas ocurrió mientras el worker no recargó `.env`.
- **Mitigación intentada:** VFS redeploy sandbox-final (disco OK); touch
  `.ostype` (no recycle); `/api/app/restart` **403**; ZipDeploy sync **400**;
  ZipDeploy `isAsync=true` aceptado (verificar post-deploy).
- **Prevención:** no usar OneDeploy static solo para restart tras VFS. Tras
  cualquier deploy/restart, validar **workers** (bootstrap + paths-probe), no
  solo el `.env` en disco. Preferir ZipDeploy del ZIP conocido o restart Portal /
  `az webapp restart`.

## Incidente restore sandbox + crash loop (2026-08-01)

Cascada posterior al forzar pruebas: ZIP con backslashes → unix ZIP → static
restart → 503 por site-packages incompletos/Windows → rebuild Linux via Docker
→ extract Kudu con timeouts → cierre con paquetes Linux (`so=85`,`pyd=0`) +
`.env` sandbox reafirmado. Live verificado:
`paths-probe env=sandbox` + path `…/03 COMWARE PRUEBAS-…`.

**Postmortem quirúrgico paso a paso (para otro agente):**
`docs/implementation/u4-rc-sandbox-worker-stale-incident.md`.

## Incidente claves ProcessKey (Notify/Merge/Apply)

- **Causa:** Generate/Finalize no limpiaban `NotifyIdempotencyKey` / Merge /
  Apply del ProcessKey anterior → UI creía Notify ya hecho.
- **Corrección:** limpieza en Generate/Finalize; proyección/notify ignoran
  claves ≠ ProcessKey (`001f2a9` + test de regresión).

## Evidencia Fase 1

| Área | Path / clave |
|------|----------------|
| Bogotá E2E completo | `_work/u4_rc/e2e_bogota/` — ProcessKey `…\|banco_bogota\|2026-07-31\|6f90381b-…` → `AMORTIZACION_APLICADA` / `COMPLETADO` |
| Bancolombia Notify | `_work/u4_rc/e2e_bancolombia/` — `…\|c217f87c-…` → `already_notified`, correo sandbox |
| Errores | `_work/u4_rc/errors/` — live 9/9; fixture subset pytest OK |
| Responsive | `_work/u4_rc/responsive/manifest.json` — 61/61 |
| Status F1/F2 | `_work/u4_rc/FASE1_FASE2_STATUS.md` |

## Fase 3 / 4 artefactos

| Artefacto | Valor |
|-----------|-------|
| Overlay RO aislado | `_work/u4_rc/production_readonly/` + `static_validation.json` |
| ZIP sandbox final | `azure-deploy-u4-rc-sandbox-final.zip` SHA `0010D026…B95342` |
| ZIP production-candidate | `azure-deploy-u4-rc-production-candidate.zip` SHA `B833FA11…9899E6` (**no desplegado**) |
| Diff ZIP | `_work/u4_rc/zip_diff_manifest.json` (solo `.env`) |

## Observaciones no bloqueantes de E2E

- `GET /jobs/{uuid-inexistente}` → HTTP 500 (debería 404).
- Bancolombia post-Notify: proyección puede mostrar `CORRECCION_REQUERIDA`
  con issues vacíos / control `PENDIENTE_ASIENTOS` (Notify OK).
- Responsive: cobertura de modales limitada (botones a menudo deshabilitados).

## Push / merge / producción

- Push: no.
- Merge git: no.
- Deploy producción: no.
- Mutaciones productivas intencionales: cero.
