# RC §47 — borrador (fase RELEASE / 1× deploy+E2E)

## Estado

**RELEASE CANDIDATE: BATCH LOCAL LISTO → 1× deploy sandbox UI HEAD**

Motivo previo: E15 crítico FAIL post-deploy `421d348` — dry-run
`ACCOUNTING_PARSE_FAILED` enmascaraba `PAYOFF_NOT_ACHIEVED`. Prod PROHIBIDA.
Sin ZipDeploy en este turno (política batching).

## A. GIT

- Branch: `ui-develop`
- Worktree: `D:\CMC\HBI_Capital\wt-ui-develop`
- Tip desplegado (Azure): `421d348`
- Tip batch local (pendiente 1× deploy): `d9b7b07`
  - `d2f754d` test: E15 asiento parseable y orden parse→payoff
  - `2183d1f` fix: endurecer harness Graph ante timeouts
  - `5c37c20` fix: E15 provision asiento y E31 rewrite CORREOS
  - `d9b7b07` docs: RC §47 batch local E15 CORREOS timeouts

## B. DEPLOY (pendiente — NO ejecutado en este turno)

| Check | Resultado |
|---|---|
| Overlay objetivo | `sandbox-ui-enabled` |
| Acción | `.\scripts\switch-env.ps1 -Target sandbox-ui-enabled` + deploy tip HEAD |
| Prod | **PROHIBIDA** |

## C. FIXES del paquete LOCAL (post re-E2E)

| Gap | Estado local | Nota |
|---|---|---|
| E15 asiento parseable GEOEXCON/231 | **listo** | `parseable_asiento_pdf` + provision harness + cuarentena `_RC_CUARENTENA` |
| Orden parse → payoff | **PASS unit** | ilegible ≠ PAYOFF; legible → `PAYOFF_NOT_ACHIEVED` |
| Merge score CANCELACIÓN/PAGO TOTAL | **listo** | prefiere PDF con «PAGO TOTAL» en nombre |
| CORREOS.xlsx sandbox | **listo** | path documentado + rewrite allowlist (sin @hbi.com.co) |
| Harness timeouts E16/E23/E30/E38 | **listo** | retries httpx + timeouts connect/read |
| E31 notify live | **desbloqueado en harness** | rewrite CORREOS → notify×2 |

### Paths sandbox (solo PRUEBAS)

- Clientes: `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- Asientos E15: `…/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/`
  - Fixture: `Asiento RC-E15 PAGO TOTAL GEOEXCON CRED 231.pdf`
  - Cuarentena ilegibles: `…/ASIENTOS…/_RC_CUARENTENA/`
- CORREOS E31: `…/02 VALIDACION PAGOS/02 CONTROL OPERATIVO/CORREOS.xlsx`
  - Allowlist: `herramientas.jsakedev@gmail.com` (nunca `@hbi.com.co`)

## G. E2E SANDBOX (post `421d348` — referencia)

Fuente: `D:\CMC\HBI_Capital\_work\rc_e2e\matrix_results.json` + Playwright E34.

| ID | Status | Evidencia |
|---|---|---|
| E01 | **PASS** | finalize=completed |
| E02 | **PASS** | finalize blocked amount_mismatch (esperado) |
| E15 | **FAIL** | dry-run `ACCOUNTING_PARSE_FAILED` (motivo de este batch) |
| E29 | **PASS** | retry generate |
| E34 | **PASS** | Playwright CAPA A |
| E37 | **PASS** | cancel post-generate |
| E16/E23/E30/E38 | FAIL | timeouts/conexión harness (mitigado local) |
| E31 | BLOCKED | CORREOS rewrite (mitigado local) |

## E. LOCAL TESTS (este batch)

Correr enfocados:

```text
pytest tests/test_amortization_fill_dry_run.py -k "payoff or parse_failed" -q
pytest tests/test_e2e_rc_fixtures_catalog.py -q
pytest tests/test_merge_credit_items.py -k "pago_total_for_cancelacion" -q
```

## O. RELEASE DECISION

**Paquete listo para 1× `deploy sandbox UI HEAD`** (no ejecutado aquí).

Condiciones post-deploy:

1. Re-E2E E15: evidencia `payoff_block=true` / `PAYOFF_NOT_ACHIEVED` (no solo parse failed).
2. Smoke E01 + E31 (CORREOS allowlist) + reintento E16/E23/E30/E38.
3. `GET /health` + bootstrap writes + paths-probe PRUEBAS.

Prod: PROHIBIDA. Merge main: no.
