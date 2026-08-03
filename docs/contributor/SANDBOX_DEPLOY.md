# Deploy a sandbox (entorno de pruebas) — sin producción

Esta guía explica **cómo se despliega hoy** la API + SPA de operador al App Service de Azure usando rutas de **pruebas (sandbox)**. No autoriza deploy a producción.

## 1. Qué es “sandbox” aquí

- El App Service puede ser el mismo host (`app-hbiauto-prod-001…`), pero el **código decide el árbol de SharePoint** según el `.env` empaquetado.
- En sandbox todo apunta a la carpeta de pruebas:

  `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`

- Contabilidad productiva va **apagada** (`GRAPH_ACCOUNTING_SITE_*` vacío).
- La UI se habilita con flags (`UI_ENABLED`, `UI_WRITE_ENABLED`, etc.).

Si el `.env` del paquete apunta a rutas productivas, **no es sandbox** aunque digas “estoy en pruebas”.

---

## 2. Archivos `.env` (rutas exactas)

Hay **dos capas**. No confundirlas.

### A) Pack de secretos (fuera del git — obligatorio para empaquetar)

```
D:\CMC\HBI_Capital\api-hbi-powerAutomate.env
```

- Contiene secretos (Graph, API key, login UI, etc.) + claves base.
- **No se versiona** en GitHub.
- Es el archivo que el script de empaquetado **copia** y luego mezcla con el overlay.
- En tu máquina debe existir en la carpeta **hermana** del repo (un nivel arriba del clon).  
  Si tu repo está en `…\api-hbi-powerAutomate\` o `…\wt-integration-performance-and-ui\`, el pack vive en `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env`.

### B) Overlay sandbox UI (sí está en el repo)

```
config/environments/sandbox-ui-enabled.env
```

Ruta absoluta típica:

```
D:\CMC\HBI_Capital\<tu-clon>\config\environments\sandbox-ui-enabled.env
```

- Define rutas PRUEBAS + flags UI (`UI_ENABLED=true`, `UI_WRITE_ENABLED=true`, `UI_REVIEW_EDIT_ENABLED=true`, `UI_ASIENTOS_UPLOAD_ENABLED=true`, …).
- **No lleva secretos**.
- El empaquetado aplica este overlay **sobre una copia** del pack (A), y el resultado se mete en el ZIP como `.env` de runtime en Azure.

### C) Marcador local (opcional)

```
.env.active   (en la raíz del repo, gitignored)
```

Lo escribe `scripts\switch-env.ps1`. Úsalo para ver el entorno activo:

```powershell
.\scripts\switch-env.ps1 -Status
```

Debes ver algo como:

- `ACTIVE_ENVIRONMENT : sandbox`
- `GRAPH_CLIENTS_BASE  : …/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- `Archivo deploy      : D:\CMC\HBI_Capital\api-hbi-powerAutomate.env`

### Otros overlays (referencia)

| Archivo | Uso |
|---|---|
| `config/environments/sandbox.env` | Solo rutas sandbox (sin forzar UI enabled) |
| `config/environments/sandbox-ui-readonly.env` | UI de solo lectura |
| `config/environments/sandbox-ui-enabled.env` | **El que usamos para deploy de pruebas con UI writable** |
| `config/environments/production.env` | Producción — **no usar** hasta autorización explícita |

---

## 3. Prerrequisitos en la máquina

1. Repo clonado + rama de UI.
2. Archivo pack: `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env` (pedirlo por canal seguro; nunca en el chat/PR).
3. Site packages Linux (una vez):

   ```powershell
   .\scripts\build-linux-python-packages.ps1
   ```

   Destino esperado por defecto:

   `D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages`

4. Perfil PublishSettings de Kudu (despliegue), normalmente:

   `D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings`

5. Node.js (para build del frontend) y PowerShell.

---

## 4. Secuencia de deploy (sandbox UI enabled)

Desde la **raíz del repo**:

### Paso 0 — Confirmar que no estás en producción

```powershell
.\scripts\switch-env.ps1 -Target sandbox
.\scripts\switch-env.ps1 -Status
```

Opcional (marca overlay UI):

```powershell
.\scripts\switch-env.ps1 -Target sandbox-ui-enabled
.\scripts\switch-env.ps1 -Status
```

**Aborta** si `GRAPH_CLIENTS_BASE` no contiene `COMWARE PRUEBAS`.

### Paso 1 — Empaquetar (no despliega)

```powershell
.\scripts\build-u4-rc-sandbox-ui-package.ps1 -Flavor sandbox-ui-enabled
```

Qué hace:

1. Copia `D:\CMC\HBI_Capital\api-hbi-powerAutomate.env` a un temp.
2. Aplica `config/environments/sandbox-ui-enabled.env`.
3. Build SPA (`frontend/`) y la mete en el paquete.
4. Incluye `.python_packages` Linux.
5. Genera ZIP, p. ej.:

   `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip`

El `BUILD_ID` queda tipo `u4-rc-sandbox-ui-enabled-<shortsha>`.

### Paso 2 — Subir a Azure (OneDeploy)

Con el perfil PublishSettings y el ZIP (ejemplo con `curl`):

```powershell
$zip = "D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip"
# Leer usuario/password del PublishSettings (perfil ZipDeploy)
# POST a: https://<scm-host>/api/publish?type=zip&clean=false&restart=true
```

Notas operativas:

- Preferir `type=zip&clean=false&restart=true` (reinicia el contenedor).
- Alternativa histórica: `scripts\deploy-zipdeploy.ps1` / VFS + restart — según permisos del rol.

### Paso 3 — Gate post-deploy (obligatorio)

```text
GET https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net/health
```

Esperado:

- `environment`: `sandbox`
- `ui_enabled`: `true`
- `build`: `u4-rc-sandbox-ui-enabled-<tu-sha>`

```text
GET …/api/ui/v1/bootstrap
```

Esperado (sandbox UI enabled):

- `writes_allowed`, `finalize_allowed`, `notify_allowed`, `merge_allowed`, `amortization_allowed` = true  
- `review_edit_allowed`, `asientos_upload_allowed` = true (si el overlay los trae)  
- `active_environment` = `sandbox`  
- `display_label` ≈ “Entorno de validación”

```text
GET …/graph/diagnostics/paths-probe   (header X-API-Key)
```

Esperado: `summary.ok == 16`, paths bajo **COMWARE PRUEBAS**.

Abrir SPA: `…/app/` → hard refresh (`Ctrl+F5`).

---

## 5. Qué NO hacer

| Acción | Riesgo |
|---|---|
| Empaquetar con overlay `production` | Escribe/lee clientes reales |
| Committear `api-hbi-powerAutomate.env` o el ZIP con `.env` | Filtra secretos |
| Deploy sin mirar `-Status` / paths-probe | Puedes creer que es sandbox y no lo es |
| Cambiar `GRAPH_CLIENTS_BASE_PATH` a la raíz productiva “para probar” | Toca producción |

---

## 6. URL y login de la UI en pruebas

Ver [ACCESO_OPERADOR_SANDBOX.md](../release/ACCESO_OPERADOR_SANDBOX.md).

- URL: `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net/app/`
- Usuario: `operador_hbi`
- Contraseña: **solo por canal seguro** (no documentada aquí).

---

## 7. Si no tienes el pack `.env` ni PublishSettings

Pídelos al dueño del entorno (Michael / equipo HBI). Sin el pack no se puede generar un ZIP runtime válido; sin PublishSettings no se puede OneDeploy.  
Puedes desarrollar y probar la SPA en local contra mocks/tests (`frontend/`, `npm test`) sin desplegar.

---

## 8. Relación con commits recientes

Los deploys de UI in-app (R0–R3 + UX) se documentan en:

- `docs/implementation/u4-rc-review-asientos-sandbox-deploy.md`
- `docs/implementation/u4-rc-inapp-ux-sandbox-redeploy.md`

Úsalos como referencia de gates; **esta guía** es el procedimiento genérico para repetir un deploy sandbox.
