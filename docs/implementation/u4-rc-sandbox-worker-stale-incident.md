# Incidente U4-RC — Worker producción vs disco sandbox + crash loop (2026-08-01)

Documento quirúrgico para otro agente (ChatGPT / Cursor): **qué falló, por qué,
qué se intentó en orden, qué funcionó, qué no tocar, y cómo verificar**.

No es un plan de producto. Es un postmortem operativo del App Service
`app-hbiauto-prod-001` mientras el pack local debía permanecer en **sandbox/pruebas**.

---

## 0. Identidad del entorno

| Clave | Valor |
|-------|-------|
| App URL | `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net` |
| SCM / Kudu | `https://app-hbiauto-prod-001-afawg2g7frgte8c5.scm.eastus-01.azurewebsites.net` |
| PublishSettings | `D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings` (perfil `ZipDeploy`) |
| Pack `.env` que se empaca | `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env` |
| Worktree | `D:\CMC\HBI_Capital\wt-integration-performance-and-ui` |
| Rama | `integration/performance-and-ui` |
| Código RC congelado | `001f2a9` |
| Sandbox path requerido | `GRAPH_CLIENTS_BASE_PATH=INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES` |
| Marker env | `ACTIVE_ENVIRONMENT=sandbox` |
| Helper scripts / zips | `D:\CMC\HBI_Capital\_work\u4_rc\` |

**Regla de negocio durante el incidente:** dejar la UI/API controlando **solo
pruebas**. No Generate/Finalize/Notify/Merge/amort sobre SharePoint productivo.

---

## 1. Síntoma (lo que el usuario veía)

Tres capas **desalineadas**:

| Capa | Estado observado |
|------|------------------|
| Local `switch-env` / pack `.env` | `sandbox` + ruta `…/03 COMWARE PRUEBAS-…` |
| Disco `wwwroot/.env` (Kudu VFS) | a menudo `sandbox` (correcto en disco) |
| **Worker Python en vivo** | `ACTIVE_ENVIRONMENT=production`, path `INFORMACION CREDITOS-CLIENTES` (sin PRUEBAS) |
| UI bootstrap | **404 fail-closed** (`local_session` solo permitido en sandbox) |

Interpretación quirúrgica: **no basta mirar el `.env` en disco**. Hay que
validar el **proceso en memoria** con:

```text
GET /graph/diagnostics/paths-probe   (header X-API-Key)
GET /api/ui/v1/bootstrap             (si existe en el build desplegado)
GET /health
```

Criterio de éxito sandbox:

- `paths-probe.active_environment == "sandbox"`
- `clients_base.path` contiene `PRUEBAS`
- (ideal) bootstrap `active_environment == "sandbox"`

---

## 2. Causas raíz (hay varias, en cascada)

### Causa A — OneDeploy `type=static` recycle “a ciegas”

- Endpoint usado:  
  `POST {scm}/api/publish?type=static&path=/home/site/wwwroot/.<marker>&restart=true`
- Efecto: Azure **reaplica el último deployment exitoso** y reinicia workers.
- Si el último artifact “exitoso” no es el ZIP sandbox correcto, o el worker no
  recarga `.env`, aparece el split:
  - disco = sandbox
  - worker = production

Esto ya estaba documentado en
`docs/implementation/u4-rc-production-readiness.md` (incidente post Fase 2).

### Causa B — ZIP Windows con backslashes (OneDeploy/rsync Linux)

- `ZipFile.CreateFromDirectory` en Windows puede escribir entradas con `\`.
- En App Service Linux, rsync falla con `Invalid argument`.
- Fix en código: `scripts/build-azure-package.ps1` fuerza paths con `/`.
- Artifact útil: `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-unix.zip`.

### Causa C — Crash loop 503 tras recycle (dependencias Python)

Tras forzar restart / deploy incompleto:

1. Oryx a veces **ignora** `run.sh` custom y genera gunicorn propio.
2. Faltaba o estaba roto `__oryx_packages__` / `.python_packages`.
3. Subir `site-packages` construidos en **Windows** (`.pyd`) → Linux no arranca.
4. `unzip`/`rm -rf` grandes vía Kudu `/api/command` → **504/499**; extracción
   parcial (p. ej. `gunicorn` sin `gunicorn/workers`, o sin `pydantic`).
5. Azure puede **bloquear cold starts** tras fallos consecutivos → 503 sostenido.

### Causa D — Permisos de restart “oficiales”

| Método | Resultado |
|--------|-----------|
| Kudu `/api/app/restart` | **403** (credencial PublishSettings ≈ Reader SCM) |
| Kudu `/api/restart` | **403** |
| `az webapp restart` | `az` no instalado / winget falló (`exit 2316632070`) |
| OneDeploy static restart | **aceptado** (pero peligroso: restaura último deploy) |
| Soft kill `killall gunicorn` | BusyBox: `killall: not found` |

### Causa E — Quirks de Kudu BusyBox + PowerShell

Al orquestar recovery desde Windows:

- Comillas simples en comandos remotos se rompen (Kudu wrappea `bash -c`).
- `pgrep -a` / `tail -n` mal parseados → `invalid option -- 'a'`.
- `ConvertTo-Json` + heredocs anidados en un solo `-Command` rompen el parser PS.
- `$1` / `$(...)` en strings dobles de PS se expanden localmente si no se escapan.
- Solución estable: scripts `.ps1` en disco + `python3` remoto vía base64;
  evitar comillas simples en el remote command.

---

## 3. Cronología de intentos (orden real de procedimiento)

Cada paso indica **objetivo → acción → resultado → decisión siguiente**.

### Paso 1 — Diagnóstico de capas

- Leer pack local (`ACTIVE_ENVIRONMENT`, `GRAPH_CLIENTS_BASE_PATH`).
- Leer `wwwroot/.env` por Kudu VFS.
- Llamar `paths-probe` + `bootstrap`.
- **Hallazgo:** disco sandbox, worker production, UI 404 fail-closed.

### Paso 2 — Intentar recycle “limpio”

- Touch / static publish restart.
- `/api/app/restart` → 403.
- Confirmar que static restart **sí** recicla, pero puede reintroducir artifact viejo.

### Paso 3 — Forzar ZIP sandbox con paths unix

- Rebuild package con `/` en entradas ZIP.
- OneDeploy del `azure-deploy-u4-rc-sandbox-unix.zip` → status OK.
- Worker a veces seguía en production hasta un static restart posterior.
- Tras recycle real: sitio entra en **503 / crash loop**.

### Paso 4 — Intentos fallidos de deps in-place

Intentos (todos insuficientes o parciales):

- Confiar en Oryx `pip install` en el App Service (lento / incompleto / timeout).
- Symlink `__oryx_packages__` sin árbol completo.
- Subir site-packages **Windows** → boot Linux falla (`.pyd`).
- `unzip` síncrono vía `/api/command` → **504**, árbol a medias.
- Vaciar/limpiar agresivo sin zip listo → peor (paquetes rotos).

### Paso 5 — Construir site-packages Linux correctos

1. Arrancar Docker Desktop (antes estaba apagado).
2. `docker run python:3.14-slim` + `pip install -r requirements.txt -t …`
3. Empaquetar:
   - `D:\CMC\HBI_Capital\_work\u4_rc\linux-site-packages.zip` (~80 MB)
   - Contenido raíz: `site-packages/...`
   - Validación local: `so≈85`, `pyd=0`, incluye `fastapi`, `pydantic`,
     `gunicorn/workers`, `uvicorn`, `pandas`.

### Paso 6 — Subir zip + extracción robusta

Patrón que **sí** funciona bajo timeouts Kudu:

1. `PUT` VFS del zip a `/home/site/wwwroot/linux-site-packages.zip`.
2. `PUT` script `ex.py` (extract con `zipfile`, rename de `site-packages` viejo
   a `.partial`, marker `/tmp/ex.done`).
3. Preferir extract **en background** (`nohup python3 ex.py >/tmp/ex.log 2>&1 &`)
   porque extract síncrono → **504** aunque el proceso remoto a veces continúe.
4. Poll de `/tmp/ex.log` + presencia de `pydantic` + `gunicorn/workers`.
5. `ln -sfn .python_packages/lib/site-packages __oryx_packages__`.
6. Reafirmar `.env` sandbox por VFS **después** de cualquier static restart.

Scripts clave:

- `_work/u4_rc/ex.py`
- `_work/u4_rc/finish_sandbox_boot.ps1` (falló: 504 mid-extract + restart prematuro)
- `_work/u4_rc/bg_extract_boot.ps1` ( BusyBox quoting issues; matado y corregido)
- `_work/u4_rc/force_sandbox_now.ps1` (**cierre efectivo**)

### Paso 7 — Cierre efectivo (`force_sandbox_now.ps1`)

Cuando el poll ya mostraba `HAS_PYDANTIC` / paquetes casi completos:

1. Check remoto: `fastapi/pydantic/uvicorn/pandas/gunicorn/workers` = True,
   `so=85 pyd=0`, `__oryx_packages__` presente.
2. Upload `.env` sandbox desde pack local.
3. `ln -sfn .python_packages/lib/site-packages __oryx_packages__`.
4. Upload `run.sh` forzando exports sandbox + path PRUEBAS (defensa en profundidad;
   Oryx puede ignorarlo).
5. Static restart OneDeploy (único recycle confiable con estas credenciales).
6. Reafirmar `.env` + symlink **otra vez** (por si el restart restauró artifact).
7. Poll `health` + `paths-probe`.

### Paso 8 — Verificación final (éxito operativo)

```text
HEALTH status=ok  build=errores-detalle-archivos-20260730
PROBE env=sandbox
PATH=INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES
switch-env -Status → sandbox (pack local alineado)
```

**Nota bootstrap:** `GET /api/ui/v1/bootstrap` puede seguir en **404** porque el
build live (`errores-detalle-archivos-20260730`) es anterior al endpoint UI U4.
Eso **no** implica producción: el worker Graph ya lee sandbox vía paths-probe.
No confundir “bootstrap 404” con “entorno production”.

---

## 4. Estado final (post-incidente)

| Ítem | Valor |
|------|-------|
| Live Graph env | `sandbox` |
| Live clients path | `…/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES` |
| Health | `ok` |
| Pack local | sandbox |
| Decision U4-RC prod | sigue **NO LISTO PARA PRODUCCIÓN** |
| Escrituras SharePoint prod intencionales | cero |
| Push/merge | no |

---

## 5. Lecciones quirúrgicas (para el próximo agente)

1. **Validar workers, no solo disco.** Siempre `paths-probe` (+ bootstrap si existe).
2. **OneDeploy static restart restaura el último deploy exitoso.** Úsalo solo si
   ese artifact es el deseado, o reafirma `.env`/packages inmediatamente después.
3. **Nunca subir `.pyd` / site-packages Windows a App Service Linux.**
4. **Extract grandes: background + python `zipfile`, no `unzip` síncrono Kudu.**
5. **Rename > `rm -rf`** para árboles grandes (evita timeout).
6. **Kudu remote cmds:** sin comillas simples; preferir `python3 -c` / scripts
   subidos; scripts PS en archivo, no heredoc gigante en línea.
7. **Credencial PublishSettings no alcanza para `/api/app/restart`.** Plan B:
   static publish restart o Portal / `az` con identidad adecuada.
8. **Fail-closed de UI es correcto** cuando worker ≠ sandbox; no implica que
   Graph con API key esté seguro — paths-probe RO contra prod ocurrió mientras
   worker estaba en production.
9. **No declarar éxito solo por health=ok.** Health no prueba el entorno SharePoint.
10. **No redeploy production-candidate** en esta app hasta paths-probe prod RO
    aislado + recycle confiable documentado.

---

## 6. Comando mínimo de verificación (copiar/pegar)

```powershell
$dest = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
$localEnv = "D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"
$apiKey = (Select-String -Path $localEnv -Pattern "^API_HTTP_KEY=" |
  Select-Object -First 1).Line.Substring(13)
$h = Invoke-RestMethod "$dest/health" -TimeoutSec 30
$pr = Invoke-RestMethod "$dest/graph/diagnostics/paths-probe" `
  -Headers @{ "X-API-Key" = $apiKey } -TimeoutSec 120
$c = $pr.checks | Where-Object { $_.name -eq "clients_base" } | Select-Object -First 1
"HEALTH=$($h.status) build=$($h.build)"
"ENV=$($pr.active_environment)"
"PATH=$($c.path)"
# Éxito sandbox: ENV=sandbox y PATH contiene PRUEBAS
```

Helper existente: `_work/u4_rc/verify_sandbox_live.ps1`.

---

## 7. Artefactos de recuperación

| Artefacto | Uso |
|-----------|-----|
| `azure-deploy-u4-rc-sandbox-unix.zip` | Deploy sandbox con paths `/` |
| `_work/u4_rc/linux-site-packages.zip` | Wheels Linux listos (~80 MB) |
| `_work/u4_rc/ex.py` | Extract remoto idempotente |
| `_work/u4_rc/force_sandbox_now.ps1` | Reafirmar env + symlink + restart + poll |
| `_work/u4_rc/bg_extract_boot.ps1` | Extract background (histórico; quirks BusyBox) |
| `scripts/build-azure-package.ps1` | Debe emitir ZIP con `/` |
| `scripts/switch-env.ps1` | Solo cambia pack local; **no** recicla Azure solo |

---

## 8. Relación con docs U4-RC

- Plan / decisión NO LISTO: `docs/plans/u4-rc-production-readiness.md`
- Implementation + incidentes previos (`.env` stale VFS, static restart):
  `docs/implementation/u4-rc-production-readiness.md`
- Este archivo: cronología completa del **crash loop + restore sandbox** del
  2026-08-01 tras forzar pruebas.

Chat / transcript fuente:
`agent-transcripts/4c85823a-a89c-448a-82e2-180d38d3e420`.
