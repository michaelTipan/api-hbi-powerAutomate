# U4-RC Production Readiness — Implementation

## Estado

Fases 1–2 completas. Fase 3: overlay estático OK; **probe live RO bloqueado** (sin slot/AS temporal). Fase 4: ZIP production-candidate creado, no desplegado.

## HEAD

`001f2a9`

## Incidente `.env` stale

- **Causa:** `deploy-kudu-vfs` no eliminaba `.env` antes del unzip.
- **Duración:** orden de minutos tras primer deploy U4-RC; UI fail-closed (404).
- **Escrituras:** cero detectadas (Graph operable con API key; UI off).
- **Corrección:** `rm -rf … .env` en `scripts/deploy-kudu-vfs.ps1` (`a992588`).
- **Prueba:** dos deploys sandbox consecutivos + bootstrap/paths-probe.
- **Prevención:** procedimiento de rollback y checklist exigen rm `.env`.

## Incidente claves ProcessKey

- **Causa:** control retiene Notify/Merge/Apply de lote anterior.
- **Corrección:** Generate/Finalize limpian campos; proyección ignora claves ≠ ProcessKey (`001f2a9`).

## Evidencia

- E2E: `_work/u4_rc/e2e_bogota`, `e2e_bancolombia`, `errors`, `responsive`
- Diff ZIP: `_work/u4_rc/zip_diff_manifest.json`
- Overlay RO: `_work/u4_rc/production_readonly/static_validation.json`
