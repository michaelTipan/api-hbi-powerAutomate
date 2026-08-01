# U4-RC-R1 — Paquete sandbox reproducible con UI

## Objetivo

Preparar ZIPs locales `sandbox-ui-readonly` y `sandbox-ui-enabled` validables
en Docker/Linux **sin tocar** el App Service live.

## Estado live (no modificar en esta fase)

- Graph: `sandbox` + path `…/03 COMWARE PRUEBAS-…`
- Contabilidad: disabled
- Backend: OK
- UI: `UI_ENABLED=false` → `/app/` y bootstrap 404
- U4-RC: **parcial** en disco; Oryx ignora `run.sh`
- Worker: Python 3.14.4; paquetes vía `__oryx_packages__`

## Decisiones R1

1. **ZIP Unix paths** — `ConvertTo-UnixZipEntryName` + `New-UnixPathZipFromDirectory`
2. **Build marker** — `app/build_info.py` + `/health` con `build`/`commit`/`environment`/`ui_enabled`
3. **Overlays** — `sandbox-ui-readonly` / `sandbox-ui-enabled`
4. **Deps** — `.python_packages/lib/site-packages` (Linux cpython-314) en el ZIP;
   `application.ensure_packaged_site_packages()` sin depender de `run.sh` ni symlink manual
5. **Startup validado** — `gunicorn -k uvicorn_worker.UvicornWorker application:app`
6. **Jobs** — nunca clean ciego de `.payment_validation_jobs`

## Artefactos

Ver `docs/implementation/u4-rc-sandbox-reproducible.md` y
`docs/release/u4-rc-sandbox-reproducible-deploy.md`.
