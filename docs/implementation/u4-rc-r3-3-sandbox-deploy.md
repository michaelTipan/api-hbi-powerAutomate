# U4-RC-R3.3 — Deploy sandbox + gate continuidad (RO)

**Fecha:** 2026-08-01  
**Decisión:** R3.3 DESPLEGADO EN SANDBOX — listo para validación manual controlada  
**Push/merge:** cero · **Producción:** cero · **Mutable Graph / Merge / Apply / Notify / Generate:** cero en esta fase

## Artefacto

| Campo | Valor |
|---|---|
| HEAD | `125bd33ad49502f2597af1b3c046ec4e4fedc153` |
| Commit | `feat(ui): continuidad de procesos, lenguaje humano y tema claro (R3.3)` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-r33-continuity.zip` |
| SHA-256 | `72D7F884D7633E5E3D0206A221190451B594146E85DD2596A0296E2382D160F3` |
| EnvSource | live `.env` predeploy (flags UI + `UI_NOTIFY_SANDBOX_TO` preservados) |
| Build live | `u4-rc-sandbox-ui-enabled-r33-125bd33` |
| Bundle | `index-DONiLLTw.js` / `index-CVEikifc.css` |
| Deploy | OneDeploy `cb5f5259-…` status=4 complete; `clean=false&restart=true` |
| Evidencia | `D:\CMC\HBI_Capital\_work\u4_rc_r33_continuity\` |

## Preservado

- `ACTIVE_ENVIRONMENT=sandbox`
- `GRAPH_CLIENTS_BASE_PATH=…/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- Contabilidad **disabled** (`accounting_site.status=disabled`)
- Credenciales / flags write·finalize·notify·merge·amort = **true** (enabled)
- CSRF R3.1 incluido en el mismo código
- Jobs: **15 → 15** (sin wipe)

## Gate post-deploy

| Check | Resultado |
|---|---|
| `/health` build + sandbox + ui_enabled | OK |
| bootstrap `SANDBOX / PRUEBAS` + `local_session` + writes/merge true | OK |
| paths-probe 16/16 · PRUEBAS · Contabilidad disabled · read_only | OK |
| `/app/` bundle R3.3 200 | OK |
| Tema claro (`--bg: #f4f6f8`, `--ink: #1a2332`) | OK |
| Jobs preservados | OK |

## Continuidad RO (API, sin POST mutables)

Login `operador_hbi` + CSRF OK · `mutable_posts=0`.

| Criterio | Resultado |
|---|---|
| Bancolombia visible tras login (`/banks`) | **OK** — `dashboard_primary_action=resume` |
| CTA **Retomar proceso** (no Iniciar validación) | **OK** — Generate `allowed=false` con mensaje humano |
| Acceso histórico / correo / archivos | **OK** — links histórico, asientos, correo PDF, control (webUrl) |
| **Actualizar documentos** | **OK** — `refresh_documents` enabled (re-GET) |
| **Generar PDF consolidado** solo si Merge allowed | **OK** — `retry_merge` presente, `enabled=false` («Faltan soportes contables») |
| Cero mensajes técnicos / pipes / códigos en copy humano | **OK** — `tech_hits=0` en campos label/message/action |
| Estado **Esperando documentos contables** | **Parcial** — ver residual abajo |

ProcessKey validado:

`payment-validation|banco_bancolombia|2026-07-31|c217f87c-38cf-4853-a7e4-27304f2dca22`

## Residual conocido (no bloquea el deploy)

Control = `PENDIENTE_ASIENTOS` y paso `merge=blocked` con summary «Esperando documentos contables», pero
`derive_operational_status` prioriza `generate.failed_business`
(«Control indica revisión pero el archivo no existe») → API
`operational_status=CORRECCION_REQUERIDA` / título «Requiere corrección».

La SPA muestra ese título; el bucket del dashboard puede caer en «Requieren atención»
aunque las **acciones** de continuidad (Retomar, docs, PDF deshabilitado) son correctas.
Corrección de prioridad de proyección: **fuera de alcance de este deploy**; candidata a R3.4.

## Rollback (no ejecutado)

- Primario CSRF: `azure-deploy-u4-rc-sandbox-ui-enabled-csrf-fix.zip` SHA `834A13F8…`
- Enabled E2E: `…\u4_rc_enabled_e2e\azure-deploy-u4-rc-sandbox-ui-enabled-credrot.zip` SHA `A4856049…`

## Validación manual pendiente (operador)

En `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net/app/`:

1. Login → Bancolombia + **Retomar proceso**
2. Detalle → links histórico/correo/archivos; **Actualizar documentos** (solo lectura)
3. Confirmar **Generar PDF consolidado** no ejecutable mientras falten soportes
4. Tema claro; sin pipes/códigos en UI
5. **No** ejecutar Merge, Apply, Notify ni Generate nuevo
