# U4-RC-R3.1 — Hotfix CSRF desplegado en sandbox

**Fecha:** 2026-08-01  
**Decisión:** HOTFIX CSRF DESPLEGADO Y VALIDADO EN SANDBOX  
**Push/merge:** cero · **Producción:** cero · **Rollback:** no requerido

## Causa

El cliente SPA solo adjuntaba `X-CSRF-Token` cuando `authMode() === "local_session"`,
y `authMode` dependía de `bootstrapCache`. Tras un 401 se limpiaba el bootstrap →
modo `"mock"` → POST mutables sin header CSRF aunque la cookie `__Host-hbi_session`
siguiera válida. Backend correcto (`invalid_csrf_token`).

## Corrección

- `csrfManager` centralizado (memoria, sticky `localSessionMode`, single-flight)
- máximo 1 retry ante 403 `invalid_csrf_token`
- gate UI “Preparando sesión segura…”
- sin localStorage/sessionStorage; middleware CSRF intacto

## Commit / build / artefacto

| Campo | Valor |
|---|---|
| HEAD | `1e75f03312781316488de5a5c4c4519d7a95bbc9` |
| Commit | `fix(ui): renovar CSRF después de reinicios de sesión` |
| Build live | `u4-rc-sandbox-ui-enabled-csrf-1e75f03` |
| Bundle | `index-BAxcI8BG.js` |
| CSS | `index-CEYMIQaf.css` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled-csrf-fix.zip` |
| SHA-256 | `834A13F83A7BEAD49D51A39BD144ACE7C0335CBF8F14ACA71019C1A1D6AF1883` |
| Deploy | OneDeploy `9bfac671…` status=4 complete; `clean=false&restart=true` |

## Preflight (antes)

- environment=sandbox; UI enabled; flags write/finalize/notify/merge/amort=true
- clients path PRUEBAS; Contabilidad disabled
- bundle previo `index-DyDwMASQ.js`; build `…-c100e02`
- jobs 13 / running 0
- ProcessKey Bogotá R3 intacto

## Post-deploy

- `/health` 200 build `u4-rc-sandbox-ui-enabled-csrf-1e75f03` sandbox ui_enabled
- bootstrap SANDBOX / PRUEBAS + local_session + writes/finalize/notify/merge/amort true
- paths-probe read_only sandbox; Contabilidad disabled; clients PRUEBAS
- `/app/` → `index-BAxcI8BG.js` 200; CSS 200
- jobs totales: 13 (sin jobs nuevos por el deploy)

## Validación CSRF live (API)

Sin Generate nuevo ni correo nuevo:

1. login → CSRF presente
2. refresh (re-GET csrf) → renovación
3. logout/login → CSRF nuevo
4. 2× POST Notify idempotente sobre ProcessKey Bogotá R3

Resultado de los POST:

- header `X-CSRF-Token` presente (valor no registrado)
- **nunca** `invalid_csrf_token` / `missing_csrf_token`
- HTTP 409 `process_not_active` (proceso ya COMPLETADO/amortizado; gate de negocio
  antes de mutación/correo — equivalente seguro a already_* para este smoke)
- renovaciones CSRF: 4 · retries CSRF: 0 · correos nuevos: 0

Nota: el GET detalle del ProcessKey respondió 500 en el probe (ajeno al gate CSRF);
el POST Notify alcanzó la lógica de negocio, lo que confirma el header.

## Retry CSRF

Cubierto solo por tests locales (no forzado en live):

- `client.csrf.test.ts` (403→retry 1×, no loop, sticky tras clearBootstrap)
- `csrfManager.test.ts` (single-flight, clear, ready gate)
- `DashboardPage.csrf.test.tsx` (botones bloqueados)
- `test_ui_csrf_write_gate.py` (token sesión anterior, logout invalida)

## Suites

- vitest 71 · tsc OK · build OK
- pytest 1314 passed, 1 skipped

## Evidencia

`D:\CMC\HBI_Capital\_work\u4_rc_csrf_hotfix\`

## Rollback (no ejecutado)

- Primario: `…\u4_rc_enabled_e2e\azure-deploy-u4-rc-sandbox-ui-enabled-credrot.zip`
  SHA `A485604953D4A2B77D0D3E027466FC0675BE4E3B88F5324DF15985247D78463D`
- Secundario readonly: SHA `B56A9ACD9EB0D5B84B20082BA593CC1B8833E03ED9257AA8CD71A85398918548`
