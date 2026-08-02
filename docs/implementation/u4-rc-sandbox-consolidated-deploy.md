# U4-RC — Paquete consolidado sandbox (UI + sync + 502 + polish)

**Fecha:** 2026-08-01  
**Decisión:** CONSOLIDADO DESPLEGADO EN SANDBOX  
**Push/merge:** cero · **Producción:** cero  
**Graph mutable:** 0 · **SharePoint modificado:** 0  
**Mutaciones UI (Generate/Notify/Merge/Apply):** no ejecutadas

## Artefacto

| Campo | Valor |
|---|---|
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-consolidated.zip` |
| SHA-256 | `1EDD4A1AC2E11350A37537FCD84D76EC0126C9508C3A68FF90FFB205F94DB688` |
| Build live | `u4-rc-sandbox-ui-enabled-consolidated` |
| Bundle | `index-jvV9mLlS.js` / `index-BLBAu4eo.css` |
| Deploy | OneDeploy `c46c1405-…` status=4; `clean=false&restart=true` HTTP 200 |
| Nota probe | `paths-probe` timeout puntual post-restart; sandbox confirmado por `.env` + bootstrap + `/graph/diagnostics` |
| EnvSource | `.env` live predeploy (flags UI + `UI_NOTIFY_SANDBOX_TO` preservados) |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_consolidated\` |

## Incluye

- Continuidad / retoma de procesos
- Mensajes operativos entendibles (sin códigos técnicos en UI)
- Tema claro + paleta profesional
- Fases: Generar archivo · Finalizar revisión · Enviar correo · Generar PDF consolidado · Procesar amortización
- «Volver al panel» como enlace estilizado botón
- Badge global **Entorno de validación**
- Actualizar documentos solo cuando corresponde
- Sincronización job ↔ Control (`sync_pending` / `SINCRONIZANDO` + retries FE)
- Mitigación 502 poll / event loop (`asyncio.to_thread` + poll resiliente)
- CSRF + proyección ya existentes

## Suites pre-deploy

| Suite | Resultado |
|---|---|
| pytest | **1335 passed**, 1 skipped |
| vitest | **113 passed** |
| tsc + vite build | OK → bundles arriba |

## Gate post-deploy (solo lectura)

- `ACTIVE_ENVIRONMENT=sandbox`
- `GRAPH_CLIENTS_BASE_PATH` …`03 COMWARE PRUEBAS-…`
- Contabilidad: `GRAPH_ACCOUNTING_SITE_HOSTNAME` vacío
- `UI_NOTIFY_SANDBOX_TO` conservado
- jobs **19 → 19**
- `.env` sha256 pre/post: `f571e084…e76d35` (mismo)
- bootstrap: `ui_enabled=true`, `active_environment=sandbox`, `display_label=Entorno de validación`, recipients configurados
- SPA: frases de fases + «Sincronizando resultados» + «Volver al panel»; sin «Destinatarios de prueba»

## Validación operador pendiente (manual)

En `/app/` (login operador): proceso activo visible, Retomar proceso, stepper 5 fases.  
Sin Generate/Notify/Merge/Apply hasta autorización adicional.

## Rollback (no ejecutado)

- Previo: `azure-deploy-u4-rc-sandbox-ui-enabled-docs-phases.zip` SHA `FC5B98D6…0950CD47` build `u4-rc-sandbox-ui-enabled-docs-phases`
