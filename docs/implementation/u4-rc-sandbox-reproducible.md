# U4-RC-R1 — Implementation (sandbox reproducible + UI)

## Alcance ejecutado (local)

- Fix ZIP paths `/` + tests (`tests/test_azure_package_zip_unix.py`)
- Health release marker (`app/build_info.py`, `health.py`)
- Overlays `config/environments/sandbox-ui-readonly.env` y `sandbox-ui-enabled.env`
- `switch-env.ps1` acepta ambos targets
- Runtime: `application.ensure_packaged_site_packages()` (sin pip improvisado ni `run.sh`)
- `uvicorn-worker` en `requirements.txt` (worker Oryx real)
- Script deps Linux: `scripts/build-linux-python-packages.ps1`
- Smoke Oryx-style: `tests/test_oryx_style_startup_smoke.py`
- Jobs preservation: `tests/test_jobs_preservation_staging.py`

## Estrategia Python packages (única)

**Elegida:** incluir `.python_packages/lib/site-packages` (wheels Linux 3.14)
en el ZIP y resolver vía `sys.path` en `application.py` **antes** de importar
`app.main`.

**Por qué no depender de `__oryx_packages__`:** el symlink remoto fue una
reparación improvisada; Oryx puede recrearlo, pero el arranque debe funcionar
aunque solo exista `.python_packages`.

`__oryx_packages__` se acepta como alias opcional si ya está presente.

## Overlays

| Overlay | UI | Writes | Mutables |
|---------|----|--------|----------|
| sandbox-ui-readonly | true | false | Finalize/Notify/Merge/Amort false |
| sandbox-ui-enabled | true | true | true (solo sandbox/PRUEBAS) |

Contabilidad productiva: hostname/path vacíos en ambos.

## Frontend

Tras `npm ci` / `npm test` / `tsc` / `npm run build`:

- Tests: 56 passed (11 files)
- Bundle: `index-DyDwMASQ.js` / `index-CEYMIQaf.css`

## Deploy

**Cero.** Ver plan en `docs/release/u4-rc-sandbox-reproducible-deploy.md`.
