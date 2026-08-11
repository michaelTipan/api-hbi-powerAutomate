# RC §47 — borrador (fase LOCAL / batching ON)

## Estado

**RELEASE CANDIDATE: BLOCKED**

Motivo: paquete de fixes locales en curso; **deploy sandbox UI HEAD aplazado**
hasta cerrar el batch (política: no redeploy por cada fix). E2E sandbox
contra tip desplegado aún no re-ejecutado sobre el HEAD del paquete.

## A. GIT (parcial)

- Branch: `ui-develop`
- Worktree: `D:\CMC\HBI_Capital\wt-ui-develop`
- START_HEAD (turno): `10e74d6`
- Commits del batch (hasta ahora):
  - `099b990` fix: E15 payoff en dry-run, no en Finalize
  - _(pendiente)_ harden can_apply + operational_issues en dry-run + fixtures catalog + handlers E16/E23/E30/E31/E38
- FINAL_HEAD: TBD al cerrar batch + deploy

## B. FIXES (E15 / Pago total)

| Gap | Estado | Archivo/función |
|---|---|---|
| E15 harness esperaba Finalize FAIL | PASS (contrato corregido) | `scripts/e2e_rc/run_matrix.py` `run_e15` |
| Payoff falso | PASS local | `amortization_fill_dry_run._verify_payoff_expected` + `PAYOFF_NOT_ACHIEVED` |
| Tests A/B §36 | PASS local | `tests/test_amortization_fill_dry_run.py` |
| Copy UI operational issue | PASS local | `amortization_operational_issues` `PAYOFF_NOT_ACHIEVED` |
| Dry-run proyecta operational_issues | PASS local (en batch) | `run_amortization_fill_dry_run` si `can_apply=false` |
| can_apply ignora error_code en PAGO | PASS local (en batch) | harden `payment_applicable` |

## G. E2E SANDBOX

Pendiente post-deploy del paquete. Última corrida conocida (tip `10e74d6`):
5 PASS · E15 FAIL (contrato harness) · 34 BLOCKED fixtures.

## E. LOCAL TESTS (batch)

- Backend payoff/dry-run/fixtures/policies/finalize: PASS (43 + 113 focused)
- Frontend vitest: **254 passed** (excluye `e2e/` de vitest; Playwright vía `npm run test:e2e`)
- Deploy: **NO** (batching ON)

## O. RELEASE DECISION

**RELEASE CANDIDATE: BLOCKED**

Gaps restantes explícitos:
1. Deploy sandbox UI HEAD del paquete batch (aún no — política batching).
2. Re-E2E E15 (+ smoke E01) y matriz ampliada post-deploy.
3. Fixtures SharePoint PRUEBAS aún faltantes para extractos espaciales / amort dual / asientos (catálogo en `scripts/e2e_rc/fixtures_catalog.py`).
4. Notify live: rewrite `CORREOS.xlsx` sandbox antes de E31 real.

Prod: PROHIBIDA. Merge main: no.
