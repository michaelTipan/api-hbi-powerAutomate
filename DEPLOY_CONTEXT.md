# DEPLOY_CONTEXT — Runbook de despliegue Azure (obligatorio antes de deploy)

**Léelo completo antes de empaquetar o desplegar.** Evita repetir fallos caros
(crash loop, reinstalación de FastAPI, worker en production con disco sandbox,
ZipDeploy “ok” con código viejo).

Fuente viva del producto: rama / worktree `ui-stable`
(`D:\CMC\HBI_Capital\wt-ui-stable`). Pack de secretos (no git):
`D:\CMC\HBI_Capital\api-hbi-powerAutomate.env`.

Postmortem largo: `docs/implementation/u4-rc-sandbox-worker-stale-incident.md`.
Principios RC: `docs/release/u4-rc-sandbox-reproducible-deploy.md`.

---

## Comandos cortos (frases canónicas)

Sandbox y producción UI son **exactamente iguales** (mismo tip/`HEAD` de
`ui-stable`, mismos flags/permisos/ops). Solo difieren el panel de entorno y
las **rutas** SharePoint/Contabilidad (PRUEBAS vs reales). Producción = carpetas
reales + UI operable. Sandbox = misma UI/ops + paths PRUEBAS.

| Frase corta (preferida) | Equivalentes | Expande a |
|---|---|---|
| **`deploy prod UI HEAD`** | `prod UI head`, `ir a producción UI completa`, «producción con rutas reales y UI lista hasta HEAD» | `switch-env -Target production-ui-enabled` → empaquetar + ZipDeploy tip `ui-stable` HEAD → verificar bootstrap ops `allowed=true` + `paths-probe` **sin** PRUEBAS + Contabilidad |
| **`deploy sandbox UI HEAD`** | `sandbox UI head`, `ir a pruebas UI completa`, «sandbox con todos los cambios hasta HEAD» | `switch-env -Target sandbox-ui-enabled` → empaquetar + ZipDeploy tip `ui-stable` HEAD → verificar bootstrap ops `allowed=true` + `paths-probe` **PRUEBAS** |

Detalle del camino feliz: §1. Paridad flags/gates: `.cursor/rules/production-ui-parity.mdc`.
**No** activar R0–R3 ni extract-index “de paso”.

---

## 0. Identidad (un solo App Service)

| Clave | Valor |
|-------|--------|
| App | `app-hbiauto-prod-001` |
| URL | `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net` |
| UI | `{URL}/app/` |
| SCM / Kudu | `https://app-hbiauto-prod-001-afawg2g7frgte8c5.scm.eastus-01.azurewebsites.net` |
| PublishSettings | `D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings` |
| Rol publish | ~Reader SCM → **no** `az webapp restart` / `/api/app/restart` (403) |
| Python runtime | Linux, **3.14** (wheels deben ser Linux, no Windows `.pyd`) |
| Oryx build en deploy | **OFF** (`.deployment` → `SCM_DO_BUILD_DURING_DEPLOYMENT=false`) |

**Implicación:** el ZIP **debe** llevar `.python_packages/lib/site-packages`
(Linux). Sin eso → `ModuleNotFoundError: fastapi` / exit 3 / 503. **No**
confíes en que Oryx reinstale deps en el ZipDeploy.

---

## 1. Camino feliz (sandbox UI) — haz esto siempre

Orden estricto:

```powershell
cd D:\CMC\HBI_Capital\wt-ui-stable

# 1) Entorno del PACK (no despliega solo)
.\scripts\switch-env.ps1 -Target sandbox-ui-enabled
.\scripts\switch-env.ps1 -Status
# Esperado: ACTIVE_ENVIRONMENT=sandbox
# GRAPH_CLIENTS_BASE_PATH contiene "03 COMWARE PRUEBAS"

# 2) Empaquetar CON deps Linux (NO omitir -PythonPackagesSource)
$pkgs = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages"
if (-not (Test-Path $pkgs)) {
  # Requiere Docker Desktop
  .\scripts\build-linux-python-packages.ps1
}
# Preferido (overlay + packages + EnforceSandboxUi):
.\scripts\build-u4-rc-sandbox-ui-package.ps1 -Flavor sandbox-ui-enabled
# Equivalente manual:
# .\scripts\build-azure-package.ps1 `
#   -PythonPackagesSource $pkgs `
#   -EnforceSandboxUi `
#   -BuildId ("u4-rc-sandbox-ui-enabled-" + (git rev-parse --short HEAD)) `
#   -ZipPath "D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip"

# 3) Preflight ZIP (falla si falta fastapi en .python_packages)
.\scripts\verify-azure-package.ps1 `
  -ZipPath "D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip" `
  -RequireSpa -RequirePythonPackages

# 4) ZipDeploy (reinicia contenedor; Reader-friendly)
.\scripts\deploy-zipdeploy.ps1 `
  -ZipPath "D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip"

# 5) Verificar WORKER en vivo (no solo disco / no solo health)
# Ver §4 — health + paths-probe con X-API-Key + (ideal) bootstrap
```

**UI readonly** (writes off): mismo flujo con `-Flavor sandbox-ui-readonly`
/ `-Target sandbox-ui-readonly`.

**Producción UI (contrato operador):** frase corta **`deploy prod UI HEAD`**
(también «producción» / «todo en producción» / «absolutely everything until
HEAD») → overlay **`production-ui-enabled`** (no `production` paths-only).
Misma superficie de flags que `sandbox-ui-enabled`; solo cambian rutas
(clientes reales + Contabilidad). Ver § Comandos cortos y
`.cursor/rules/production-ui-parity.mdc`.

```powershell
.\scripts\switch-env.ps1 -Target production-ui-enabled
.\scripts\switch-env.ps1 -Status
# Esperado: ACTIVE_ENVIRONMENT=production
# GRAPH_CLIENTS_BASE_PATH=INFORMACION CREDITOS-CLIENTES (sin COMWARE PRUEBAS)
# Pre-deploy: diff flags UI vs sandbox-ui-enabled (paridad; rechazar extras)
# Empaquetar con -PythonPackagesSource / packages Linux (mismo criterio §0–§2)
```

**Producción SharePoint sin UI** (Power Automate / paths-only): overlay
`production` solo si el usuario lo pide explícitamente como «sin UI».

**Lección ae73d51:** flags `UI_*_ENABLED=true` en el overlay **no bastan** si el
bootstrap o `/banks` AND-gatean con `environment == "sandbox"`. Capacidades de
operador = `ui_write_environment_allowed` + flags. Tras deploy prod UI verificar
bootstrap (`finalize`/`notify`/`merge`/`amortization` allowed), no solo health.

---

## 2. Qué NO hacer (lista negra)

| Prohibido | Por qué |
|-----------|---------|
| `build-azure-package.ps1` **sin** `-PythonPackagesSource` | ZIP sin FastAPI → crash loop; pierdes 15–40+ min recuperando |
| Subir site-packages **Windows** (`.pyd`) | App Service es Linux; no arranca |
| Confiar en Oryx `pip install` durante ZipDeploy | Build Oryx desactivado; timeouts; árbol incompleto |
| OneDeploy `type=static` **a ciegas** para “reiniciar” | Restaura el **último** deploy exitoso; puede dejar worker en **production** con disco sandbox |
| Declarar éxito solo con `GET /health` | Health no prueba SharePoint ni entorno |
| Declarar éxito si `deploy-zipdeploy.ps1` dice «SIGUE EL CODIGO VIEJO» o «CODIGO NUEVO» mirando `/graph/diagnostics` **sin** API key | Ese path responde **401** sin key → **falso negativo** habitual |
| Confiar solo en `.env` en disco (Kudu VFS) | Worker en memoria puede seguir en production |
| `rm -rf /home/site/wwwroot` o clean global | Borra jobs / packages; recuperación dolorosa |
| Borrar `.payment_validation_jobs` en deploy | Pierdes historial de jobs en App Service |
| ZIP con backslashes `\` | OneDeploy/rsync Linux falla (`Invalid argument`) — el build ya fuerza `/` |
| Extracción grande vía `unzip` síncrono Kudu `/api/command` | 504/499; árbol a medias (gunicorn sin workers, sin pydantic) |
| Deploy a producción SharePoint “por probar” | Clientes reales; sandbox es `…/03 COMWARE PRUEBAS-…` |
| Mutar Graph/SharePoint prod mientras diagnosticas | Solo `paths-probe` / health RO |

---

## 3. Fallos conocidos ↔ síntoma ↔ arreglo

### A) `ModuleNotFoundError: fastapi` / app exit 3 / 503

- **Causa:** ZIP sin `.python_packages` o árbol incompleto / `.pyd` Windows.
- **Prevención:** siempre `-PythonPackagesSource` o `build-u4-rc-sandbox-ui-package.ps1`;
  `verify-azure-package.ps1 -RequirePythonPackages`.
- **Si ya pasó:** no improvisar pip en Kudu. Reconstruir packages Linux
  (`build-linux-python-packages.ps1`), **reempaquetar ZIP completo**, ZipDeploy de nuevo.
- **Recuperación histórica (último recurso):** ver incidente
  `u4-rc-sandbox-worker-stale-incident.md` (VFS + extract background + symlink).
  Preferir **no** llegar ahí.

### B) Disco `.env` = sandbox, worker = production / UI bootstrap 404 fail-closed

- **Causa:** recycle static OneDeploy restauró artifact viejo; o `.env` no recargado.
- **Verdad:** `GET /graph/diagnostics/paths-probe` con `X-API-Key`.
- **Arreglo:** redeploy ZIP sandbox correcto + reafirmar pack; evitar static restart
  a ciegas. Tras static, re-subir `.env` sandbox si hace falta.

### C) Script dice «SIGUE EL CODIGO VIEJO» tras ZipDeploy bueno

- **Causa:** poll a `/graph/diagnostics` sin API key → 401.
- **Arreglo:** ignorar ese mensaje; validar con `/health` (build/commit) +
  `paths-probe` autenticado (§4).

### D) ZipDeploy HTTP 400 (flaky)

- Reintentar async/`isAsync` según docs; no mezclar con VFS delete-all.
- Preferir el script `deploy-zipdeploy.ps1` del repo actual.

### E) Credencial no reinicia (`/api/app/restart` 403)

- ZipDeploy **sí** reinicia al terminar (por eso es el camino preferido).
- Static OneDeploy restart solo si el último artifact es el deseado + reafirmar `.env`.

### F) Docker apagado / falta `linux-site-packages`

- Path canónico:
  `D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages`
- Alternativa zip histórico: `_work\u4_rc\linux-site-packages.zip` (extraer antes).
- Arrancar Docker Desktop → `.\scripts\build-linux-python-packages.ps1`.

---

## 4. Verificación post-deploy (criterio de éxito)

No digas “deploy OK” hasta cumplir esto:

```powershell
$dest = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
$localEnv = "D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"
$apiKey = (Select-String -Path $localEnv -Pattern "^API_HTTP_KEY=" |
  Select-Object -First 1).Line.Substring(13)

$h = Invoke-RestMethod "$dest/health" -TimeoutSec 30
$pr = Invoke-RestMethod "$dest/graph/diagnostics/paths-probe" `
  -Headers @{ "X-API-Key" = $apiKey } -TimeoutSec 120
$c = $pr.checks | Where-Object { $_.name -eq "clients_base" } | Select-Object -First 1

"HEALTH=$($h.status) build=$($h.build) env=$($h.environment) ui=$($h.ui_enabled)"
"PROBE_ENV=$($pr.active_environment)"
"CLIENTS=$($c.path)"
```

### Sandbox OK si y solo si

1. `health.status == ok`
2. `health.build` contiene el marker esperado (p. ej. `u4-rc-sandbox-ui-enabled-<sha>`)
3. `health.environment == sandbox` (si el campo existe)
4. `paths-probe.active_environment == sandbox`
5. `clients_base.path` contiene **`COMWARE PRUEBAS`** (no `02 COMWARE AUTOMATIZACION` de prod)
6. Ideal: `GET /api/ui/v1/bootstrap` → 200 y entorno coherente
7. Ideal: `GET /app/` → 200

Helper histórico: `D:\CMC\HBI_Capital\_work\u4_rc\verify_sandbox_live.ps1` (si existe).

### Producción UI (`production-ui-enabled`) OK si y solo si

1. `health.status == ok`, build esperado, `ui_enabled` / environment production
2. `paths-probe.active_environment == production`
3. `clients_base.path` = raíz clientes reales (**sin** `COMWARE PRUEBAS` en base)
4. Contabilidad presente en probe (hostname/path configurados)
5. `GET /api/ui/v1/bootstrap` → writes + finalize/notify/merge/amortization
   **allowed** (paridad sandbox-ui-enabled; no UI “montada pero read-only”)
6. Pre-deploy: overlay prod no enciende flags ausentes en sandbox-ui-enabled
   (R0–R3, extract-index campaigns, etc.)

---

## 5. Checklist rápido (copiar antes de deploy)

- [ ] Worktree correcto (`wt-ui-stable` / rama acordada)
- [ ] `switch-env -Status` = sandbox-ui-* **o** `production-ui-enabled` (según pedido)
- [ ] Si prod UI: paridad flags vs `sandbox-ui-enabled` (ver `production-ui-parity.mdc`)
- [ ] Existe `linux-site-packages` (o se acaba de construir con Docker)
- [ ] Build **con** `-PythonPackagesSource` / script `build-u4-rc-sandbox-ui-package.ps1`
- [ ] `verify-azure-package.ps1 -RequireSpa -RequirePythonPackages` OK
- [ ] ZipDeploy del ZIP recién verificado (path explícito)
- [ ] Poll: health build + paths-probe (PRUEBAS o prod real) con API key
- [ ] Si prod UI: bootstrap con writes/finalize/notify/merge/amort allowed
- [ ] No se usó OneDeploy static “por si acaso”
- [ ] No se tocó SharePoint productivo en smoke (salvo ops UI autorizada)

---

## 6. Scripts canónicos

| Script | Rol |
|--------|-----|
| `scripts/switch-env.ps1` | Overlay pack local `.env` (no reinicia Azure) |
| `scripts/build-linux-python-packages.ps1` | Wheels Linux 3.14 → `_work/.../linux-site-packages` |
| `scripts/build-u4-rc-sandbox-ui-package.ps1` | ZIP sandbox UI + packages (preferido) |
| `scripts/build-azure-package.ps1` | ZIP genérico; **pasar** `-PythonPackagesSource` |
| `scripts/verify-azure-package.ps1` | Preflight ZIP (`/` + SPA + packages) |
| `scripts/deploy-zipdeploy.ps1` | Sube ZIP y reinicia; **ignorar** veredicto 401 de diagnostics |
| `scripts/deploy-kudu-vfs.ps1` | Alternativa VFS (más frágil; no default) |
| `scripts/oryx-pip-and-health.ps1` | Legacy recovery; **no** camino feliz |

PublishSettings y secretos: **nunca** dentro del ZIP.

---

## 7. Por qué el último deploy se demoró (2026-08-03 / `928651a`)

1. Primer empaquetado **sin** `.python_packages` → App Service sin FastAPI.
2. Segundo build con `linux-site-packages` + redespliegue.
3. Falso negativo del poll de `deploy-zipdeploy.ps1` (401 sin API key).
4. Contención opcional por tareas git paralelas (purga de ramas).

**Lección:** el paso 2 del camino feliz no es opcional; el verify con
`-RequirePythonPackages` debe ejecutarse **antes** del ZipDeploy.

---

## 8. Actualización de este archivo

Tras cualquier incidente nuevo de deploy: añadir fila en §3 y una línea en §7.
Mantener alineado con `PROJECT_CONTEXT.md` (sección Despliegue apunta aquí).
