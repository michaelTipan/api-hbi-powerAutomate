# RC §47 — borrador (fase RELEASE / 1× deploy+E2E)

## Estado

**RELEASE CANDIDATE: PASS**

Motivo: 1× `deploy sandbox UI HEAD` tip `ee993de` OK; E15 crítico
desbloqueado (`payoff_block=true` / `PAYOFF_NOT_ACHIEVED`, ya no
`ACCOUNTING_PARSE_FAILED`). Smoke E01 + E31 CORREOS + timeouts E23/E30/E38
PASS. 0 FAIL de producto. Prod PROHIBIDA. Sin redeploy en bucle.

Residual no bloqueante: E16 **BLOCKED** por fixture multi-crédito
(231+254; `applied=1`) — gap de datos sandbox, no bug de producto.

## A. GIT

- Branch: `ui-develop`
- Worktree: `D:\CMC\HBI_Capital\wt-ui-develop`
- Tip desplegado (Azure): `ee993de`
- Build: `u4-rc-sandbox-ui-enabled-ee993de`
- ZIP SHA256: `5CC29FF926227EE4D0B25C9154CC0501B28CC36938C864A01C8E2492F2B52242`
- Base batch local sobre `421d348` (E15 asiento + CORREOS + harness retries)

## B. DEPLOY (ejecutado — 1×)

| Check | Resultado |
|---|---|
| Overlay | `sandbox-ui-enabled` (`ACTIVE_ENVIRONMENT=sandbox`) |
| `GET /health` | `ok` · `environment=sandbox` · `ui_enabled=true` · tip `ee993de` |
| Bootstrap | `writes/finalize/notify/merge/amortization_allowed=true` · `history_allowed=false` |
| `paths-probe` | **16/16** · base **COMWARE PRUEBAS** · Contabilidad off (esperado sandbox) |
| Prod | **PROHIBIDA** (no tocada) |

## C. FIXES del paquete LOCAL (verificados en vivo)

| Gap | Post-deploy | Nota |
|---|---|---|
| E15 asiento parseable GEOEXCON/231 | **PASS** | fixture subida + cuarentena `asiento_banco_bogota_credito-231.pdf` → `_RC_CUARENTENA` |
| Orden parse → payoff | **PASS E2E** | `items_errors: [PAYOFF_NOT_ACHIEVED]` · `can_apply=false` · `payoff_block=true` |
| CORREOS.xlsx sandbox | **PASS E31** | allowlist `herramientas.jsakedev@gmail.com` · n1=completed · n2=http_error (aceptado retry) |
| Harness timeouts | **mitigado** | retries Graph vistos; E23/E30/E38 PASS |

### Paths sandbox (solo PRUEBAS)

- Clientes: `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- Asientos E15: `…/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/`
  - Fixture: `Asiento RC-E15 PAGO TOTAL GEOEXCON CRED 231.pdf`
  - Cuarentena: `…/ASIENTOS…/_RC_CUARENTENA/`
- CORREOS E31: `…/02 VALIDACION PAGOS/02 CONTROL OPERATIVO/CORREOS.xlsx`

## G. E2E SANDBOX (post `ee993de`)

Fuente: `_work/rc_e2e/matrix_results_combined_ee993de.json` + Playwright CAPA A.

| ID | Status | Evidencia |
|---|---|---|
| E15 | **PASS** | `finalize=completed; dry_run=completed; can_apply=False; payoff_block=True` · `PAYOFF_NOT_ACHIEVED` |
| E01 | **PASS** | `finalize=completed; edited=1` |
| E31 | **PASS** | CORREOS rewrite allowlist · `n1=completed; n2=http_error` |
| E16 | **BLOCKED** | `need_two_credit_rows; applied=1` (fixture 231+254) |
| E23 | **PASS** | `finalize=completed; rows=2` |
| E30 | **PASS** | `f1=completed; f2=completed` |
| E38 | **PASS** | cancel bloqueado post-FINALIZADO (esperado) |
| E34 | **PASS** | Playwright CAPA A login + panel sin copy legacy |

Conteos ciclo: **PASS=6 (+E34)** · **FAIL=0** · **BLOCKED=1 (E16 fixture)**.

## O. RELEASE DECISION

**RELEASE CANDIDATE: PASS**

Criterios cumplidos:

1. Health tip `ee993de` + bootstrap writes ON + paths-probe 16/16 PRUEBAS.
2. E15 evidencia `payoff_block=true` / `PAYOFF_NOT_ACHIEVED` (no solo parse failed).
3. Smoke E01 + E31 CORREOS + reintento E23/E30/E38 PASS.
4. Sin FAIL de producto → sin segundo deploy.

Siguiente batch local (opcional, no bloquea RC): fixture E16 multi-crédito
GEOEXCON 231+254 reconciliables.

Prod: PROHIBIDA. Merge main: no en este ciclo.
