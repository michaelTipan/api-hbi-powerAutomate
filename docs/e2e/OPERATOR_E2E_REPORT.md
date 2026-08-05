# Reporte E2E operador — Playwright ui-simulated v1

Fecha del reporte: **2026-08-05** (America/Bogota).  
Worktree: `D:\CMC\HBI_Capital\wt-ui-stable` · rama E2E: `test/e2e-playwright-operator`.

---

## 1. Resumen ejecutivo

| Área | Estado | Detalle |
|------|--------|---------|
| Deploy sandbox UI HEAD | **OK** | Worker en Azure con `u4-rc-sandbox-ui-enabled-e0454df`; paths PRUEBAS confirmados |
| Amort recovery MVP (`dfea55f`) | **Commit local, no desplegado** | Persistencia `last_amortization_attempt` en `ui-stable`; el ZIP desplegado es `e0454df` |
| Playwright ui-simulated P0 | **VERDE** | 14/14 tests (`npm run test:e2e`) |
| Vitest frontend | **VERDE** | 244/244 (`npm test -- --run`) |
| pytest amort projection | **VERDE** | 5/5 (`tests/test_amortization_attempt_projection.py`) |

**Alcance v1:** mocks `page.route` sobre `/api/ui/v1/*`, SPA servida con `vite preview` en `:4173/app/`. **Sin** sandbox-real, **sin** Schemathesis, **sin** cambios de producción salvo harness de prueba.

---

## 2. Deploy sandbox UI HEAD

### 2.1 Metadatos

| Campo | Valor |
|-------|--------|
| Fecha/hora deploy (UTC) | `2026-08-04T23:15:58.807Z` |
| Commit desplegado | `e0454df7ab56aafb6f89c2ad1789c08613fa6c11` |
| BUILD_ID | `u4-rc-sandbox-ui-enabled-e0454df` |
| ZIP | `D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-enabled.zip` |
| ZIP SHA256 | `89243903A491100B51954DA23F545E0D1C8030BF15C5E7F7E6C7F105DB5C8CF9` |
| ZIP size | 56 662 691 bytes · modificado local `2026-08-05 03:23:07` |
| Overlay activo | `sandbox-ui-enabled` (`.env.active`) |
| `ACTIVE_ENVIRONMENT` | `sandbox` |
| `GRAPH_CLIENTS_BASE` | `…/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES` |

**Nota:** otro agente completó verify + ZipDeploy (`723384.txt`); este reporte **no** relanzó deploy duplicado.

### 2.2 URLs canónicas

| Recurso | URL |
|---------|-----|
| App base | `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net` |
| UI operador | `{base}/app/` |
| Health | `{base}/health` |
| Bootstrap | `{base}/api/ui/v1/bootstrap` |
| Paths probe | `{base}/graph/diagnostics/paths-probe` (requiere `X-API-Key`) |

### 2.3 Health (post-deploy)

```json
{
  "status": "ok",
  "build": "u4-rc-sandbox-ui-enabled-e0454df",
  "commit": "e0454df7ab56aafb6f89c2ad1789c08613fa6c11",
  "environment": "sandbox",
  "ui_enabled": true
}
```

### 2.4 Bootstrap (ops allowed)

```json
{
  "ui_enabled": true,
  "writes_allowed": true,
  "finalize_allowed": true,
  "notify_allowed": true,
  "merge_allowed": true,
  "amortization_allowed": true,
  "notify_test_recipients_configured": true,
  "active_environment": "sandbox",
  "auth_mode": "local_session",
  "login_required": true
}
```

### 2.5 paths-probe (resumen)

- `active_environment`: **sandbox**
- `clients_base`: `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- `payment_validation_base`, `control`, `review`, `historical`, bancos PRUEBAS, `merge_output_operations` → **99 SOPORTES… PRUEBAS**
- Contabilidad: paths sandbox vacíos en overlay (esperado PRUEBAS)

---

## 3. Inventario de cambios en código

### 3.1 Amort recovery MVP (`dfea55f` — `ui-stable`, no en ZIP desplegado)

| Archivo | Qué hace | Por qué |
|---------|----------|---------|
| `app/application/ui/amortization_attempt.py` | Proyección `last_amortization_attempt` desde job/control | Recovery UI tras amort fallida |
| `app/application/ui/schemas.py` | Tipos Pydantic `UiLastAmortizationAttempt` | Contrato API |
| `app/application/ui/process_projection.py` | Enriquece GET proceso con último intento | Banner/modal amort en detalle |
| `app/application/services/amortization_queue_service.py` | Persiste snapshot al cerrar job amort | Fuente de verdad post-job |
| `app/application/use_cases/amortization_fill_apply.py` | Hook persistencia | Integración pipeline |
| `app/application/use_cases/payment_validation_process_control.py` | Control estado recovery | Coherencia control |
| `app/application/use_cases/setup_merge_control_workbook.py` | Columna/soporte control | Trazabilidad |
| `frontend/src/types/contract.ts` | `UiLastAmortizationAttempt` TS | Tipado SPA |
| `frontend/src/domain/amortizationOperationalIssues.ts` | Resolución issues persistidos + familia formato | Banner reconsolidar |
| `frontend/src/domain/mergeReadinessCopy.ts` | Copy recovery merge | UX fase 4 |
| `frontend/src/pages/ProcessDetailPage.tsx` | Banner recovery + modal issues | Operador corrige y reintenta |
| `frontend/src/pages/ProcessDetailPage.copy.test.tsx` | Tests copy recovery | Regresión copy |
| `tests/test_amortization_attempt_projection.py` | pytest proyección | Backend |
| `PROJECT_CONTEXT.md` | Nota recovery | Contexto proyecto |

### 3.2 Playwright harness (`test/e2e-playwright-operator`)

| Archivo | Qué hace | Por qué |
|---------|----------|---------|
| `frontend/package.json` | `@playwright/test`, scripts `test:e2e` | Entrada npm |
| `frontend/playwright.config.ts` | Preview `:4173`, trace on failure, `--host 127.0.0.1` | Runner estable Windows |
| `frontend/vite.config.ts` | `test.exclude: e2e/**` | Vitest no pisa Playwright |
| `frontend/e2e/fixtures/apiMocks.ts` | Router `page.route` `/api/ui/v1/**` | API simulada determinista |
| `frontend/e2e/fixtures/test.ts` | Fixture `authenticatedPage` auto-login | DRY specs autenticados |
| `frontend/e2e/mocks/fixtures.ts` | Procesos P0 (review, notify, merge, amort recovery) | Datos contrato UI |
| `frontend/e2e/pages/operatorPages.ts` | Page objects (login, panel, detalle, historial) | Selectores estables (`#login-password`, `#new-process-bank`, `#current-phase-title`) |
| `frontend/e2e/tests/ui-simulated/p0-*.spec.ts` | 12 specs P0 (+2 casos login) = **14 tests** | Cobertura operador |
| `frontend/e2e/README.md` | Puntero + comandos | Onboarding |
| `.gitignore` | `playwright-report/`, `e2e/test-results/` | Artefactos locales |

---

## 4. Arquitectura E2E

```
npm run build  →  dist/
       ↓
vite preview --host 127.0.0.1 --port 4173  (base /app/)
       ↓
Chromium (Playwright)  →  SPA React Router basename /app
       ↓
page.route('**/api/ui/v1/**')  →  JSON mock (sin backend real)
```

### Fixtures auth / CSRF

1. `GET /bootstrap` → `local_session`, `login_required: true`
2. `POST /auth/login` → ok; luego `GET /auth/csrf` → `{ csrf_token: "e2e-csrf-token-fixed" }`
3. `GET /auth/me`, `/environment`, `/banks`, `/processes`…
4. Mutaciones POST incluyen header **`X-CSRF-Token`** (verificado en `p0-csrf-gate.spec.ts`)

### Page objects — estrategia de selectores

| Preferencia | Uso |
|-------------|-----|
| `#login-username`, `#login-password` | Evita colisión label “Contraseña” + botón “Mostrar contraseña” |
| `#new-process-bank` | Evita colisión aria-label “Continuar proceso — Banco…” |
| `#current-phase-title` | Fase activa única (evita h2/h3 duplicados) |
| `getByRole('button', { name, exact: true })` | CTAs operador (`Finalizar revisión`, etc.) |
| `getByRole('link'/'heading')` | Navegación shell e historial |

**Navegación:** rutas **relativas** a `baseURL` (`./processes/...`) porque `baseURL` termina en `/app/`; `/processes` absoluto cae fuera de la SPA.

---

## 5. Catálogo escenarios P0

| ID | Nombre | Spec | Mock principal | Assert clave | Bug que detectaría | Trace |
|----|--------|------|----------------|--------------|-------------------|-------|
| P0-01a | Login rechaza credenciales | `p0-login.spec.ts` | POST login 401 | `.login-error` visible | Mensaje auth roto | `e2e/test-results/.../trace.zip` |
| P0-01b | Login OK | `p0-login.spec.ts` | POST login 200 | heading “Panel” | Regresión login local | idem |
| P0-02 | CSRF en POST generate | `p0-csrf-gate.spec.ts` | csrf + generate | header `x-csrf-token` | Mutaciones sin CSRF | idem |
| P0-03a | Lista procesos activos | `p0-dashboard-list.spec.ts` | GET `/processes` | 2× Bancolombia, 2× Bogotá | Panel vacío erróneo | idem |
| P0-03b | Navegar a detalle | `p0-dashboard-list.spec.ts` | idem | URL contiene `e2e-review` | Links tarjeta rotos | idem |
| P0-04 | Generate + seguimiento | `p0-dashboard-generate.spec.ts` | POST generate 202 + job | “Seguimiento —” | Flujo nuevo proceso roto | idem |
| P0-05 | Fase revisión | `p0-process-review.spec.ts` | GET proceso review | `#current-phase-title`, botón Finalizar | Detalle fase 1 roto | idem |
| P0-06 | Finalize | `p0-process-finalize.spec.ts` | POST finalize | request + modal | Cierre revisión roto | idem |
| P0-07 | Notify | `p0-process-notify.spec.ts` | POST notify | request aceptado | Envío correo roto | idem |
| P0-08 | Merge | `p0-process-merge.spec.ts` | POST merge | request aceptado | Consolidación rota | idem |
| P0-09 | Amort recovery banner | `p0-process-amort-recovery.spec.ts` | `last_amortization_attempt` + `ACCOUNTING_PARSE_FAILED` | banner + modal issues | Recovery amort no visible | idem |
| P0-10 | Historial archivado | `p0-history.spec.ts` | GET `/process-history` | fila “Archivo” | Historial vacío | idem |
| P0-11 | Nav sidebar | `p0-navigation.spec.ts` | — | Panel ↔ Historial | Routing shell roto | idem |
| P0-12 | Logout | `p0-logout.spec.ts` | POST logout | “Acceso operativo” | Sesión no cierra | idem |

Depuración trace: `cd frontend && npx playwright show-trace e2e/test-results/<carpeta>/trace.zip`

---

## 6. Matriz de cobertura

| Capacidad | Playwright P0 | Vitest | pytest |
|-----------|---------------|--------|--------|
| Login / logout local_session | ✅ | parcial (`client.csrf`) | — |
| CSRF header mutaciones | ✅ | ✅ gate dashboard | — |
| Panel list/generate | ✅ | ✅ muchos dashboard tests | — |
| Detalle fases finalize/notify/merge | ✅ POST | ✅ ProcessDetailPage.* | — |
| Amort recovery persistido | ✅ banner (mock) | ✅ copy tests | ✅ projection |
| Historial | ✅ tabla | ✅ HistoryPage | — |
| Job polling real multi-min | — | mocks | jobs API |
| SharePoint / Graph real | — | — | dobles memoria |
| Bootstrap gates prod/sandbox | — | parcial | health tests |
| Schemathesis OpenAPI | — | — | — (no alcance v1) |

**Gaps explícitos:** sandbox-real E2E, CI GitHub Actions, `data-testid` sistemáticos, polling largo, Contabilidad prod.

---

## 7. Comandos de reproducción

```powershell
cd D:\CMC\HBI_Capital\wt-ui-stable\frontend

# Unitarios SPA
npm test -- --run

# E2E (build + preview + 14 tests)
npm run test:e2e

# Un spec
npm run test:e2e -- e2e/tests/ui-simulated/p0-process-amort-recovery.spec.ts

# UI mode
npm run test:e2e:ui

# Backend amort projection
cd D:\CMC\HBI_Capital\wt-ui-stable
python -m pytest tests/test_amortization_attempt_projection.py -q
```

---

## 8. Troubleshooting quirúrgico

| Síntoma test | Revisar | Mock / componente |
|--------------|---------|-------------------|
| “did you mean `/app/processes/…`” | `ProcessDetailPageObject.goto` | Usar `./processes/` no `/processes/` |
| strict mode `getByLabel('Contraseña')` | `operatorPages.ts`, `apiMocks.loginViaUi` | `#login-password` |
| strict mode `getByLabel('Banco')` | dashboard specs | `#new-process-bank` |
| Fase notify/merge no abre con `?phase=` | `e2e/mocks/fixtures.ts` steps | Completar `review`+`finalize` previos |
| Banner amort recovery ausente | mock `technical_reference` | Debe ser `ACCOUNTING_PARSE_FAILED` |
| POST no capturado | spec | `waitForRequest` **antes** de click Confirmar |
| Vitest ejecuta specs e2e | `vite.config.ts` | `test.exclude: **/e2e/**` |
| Preview timeout Playwright | `playwright.config.ts` | `--host 127.0.0.1` (no solo localhost IPv6) |

---

## 9. Riesgos y no-alcance

- **WIP no desplegado:** `dfea55f` (amort recovery) no está en Azure; E2E amort recovery prueba **mock**, no worker real.
- **sandbox-real pendiente** (P1): requiere credenciales, datos PRUEBAS estables, idempotencia jobs.
- **Paralelismo:** 8 workers OK en mocks; sandbox-real probablemente 1 worker.
- **Flaky potencial:** modales job completan instantáneo en mock; specs assert solo POST aceptado en notify/merge.

---

## 10. Próximos pasos

1. **P1 sandbox-real:** subset smoke login + list processes contra Azure PRUEBAS (sin mutaciones destructivas).
2. **`data-testid`** en CTAs críticos (`finalize`, `merge`, `amortization`) para selectores inmunes a copy.
3. **CI:** job `npm run test:e2e` en PR con cache `playwright` + artefacto trace on failure.
4. **Deploy** `dfea55f` cuando operador valide recovery en sandbox UI HEAD.
5. **Schemathesis** opcional contra OpenAPI (fuera v1).

---

*Generado como parte del harness Playwright ui-simulated v1 · HBI Capital wt-ui-stable.*
