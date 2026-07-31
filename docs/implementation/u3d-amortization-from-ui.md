# U3-D — Procesar amortización desde la UI

**Fecha cierre sandbox:** 2026-07-31  
**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`

## HEAD (reconciliación)

| Rol | Commit | Notas |
|-----|--------|-------|
| HEAD real / documental | `0b3bfbd0923c4abc014b6643993ae6f252c5c87e` | tip actual |
| HEAD de código (+ tests) | `781f2735f37387d95a67f9e5bbc6213b7919237a` | último commit no-docs |
| Docs-only tras código | `1883e78` → `0b3bfbd` | +1 línea en este doc; **sin** cambios `app/`/`frontend/` |

ZIP off se conservó: `app/` del ZIP == worktree (hashes idénticos). `startup.sh` texto idéntico (solo CRLF en disco local).

## ZIP

| Paquete | SHA-256 |
|---------|---------|
| `azure-deploy-u3d-amortization-off.zip` | `A89EC695249EA16285504603E88CE9403028FB8F04E24A8E3B432FBBF9870B64` |
| `azure-deploy-u3d-amortization-enabled.zip` | `CAE1DADDB5B12ED962B81D300BF72D930C42DBBB6C45A16814C9451D8F5A7D2C` |

**Diff off→enabled:** única línea funcional `UI_AMORTIZATION_ENABLED=false` → `true`. `app/` idéntico (0 diffs).

## Etapa 1 (flag off)

- Deploy: Kudu VFS + OneDeploy static restart.
- Bootstrap: `amortization_allowed=false`; Merge/Notify/Finalize/writes true; `active_environment=sandbox`.
- POST UI amortización → **403** `ui_amortization_disabled` (antes de lock/job/Graph).
- Jobs 57→57; `amortization_process=0`.
- Control: `CONSOLIDADO`, ProcessKey intacto.
- PA: sin key → 401 dry-run/apply; GET jobs fake + API key → 404 (ruta montada). **Sin** POST Dry-run/Apply reales.

## Etapa 2 (flag on) + smoke

- Deploy enabled ZIP; tras recycle `amortization_allowed=true`.
- Readiness: `ready`, expected/ready items=2.
- Backup Graph `path-content` GET → 404 (endpoint no sirve descarga); evidencia post vía job Kudu.
- POST UI → **202** job `97c40f18-53b3-4d29-859f-0fbcaa962c2b`.
- Doble clic → **409** `amortization_busy`.
- Fases: `validating` → `applying` → `completed`.
- Outcome: **`applied`** (`AMORTIZACION_APLICADA`).
- `ApplyIdempotencyKey` = ProcessKey.
- Tablas (2) sandbox: CRED 215 (PAGO, ADOPTED, IBR escrito) + CRED 320 (ABONO, ADOPTED, IBR no).
- `formula_fill_columns` vacío / rows=0 → O:P no tocadas.
- Excel revisión eliminado (`review_validation_file_cleanup.deleted=true`).
- PDFs moved count=0 (eventos ADOPTED).
- Reintento UI → **409** `already_applied`; jobs 58 total / **1** `amortization_process` (sin segundo job).
- Rollback: **no**.
- Flag final sandbox: `UI_AMORTIZATION_ENABLED=true`.
- Producción / push / merge git: **cero**.
- POST PA Dry-run/Apply reales: **cero**.

## Arquitectura (resumen)

Prepare canónico una vez → freshness → execute sin re-dry-run.  
`AmortizationQueueService` + mutex JobManager. PA contratos intactos (+409 busy).  
UI acción única “Procesar amortización”.

Evidencia: `D:\CMC\HBI_Capital\_work\u3d_amortization_smoke\` (`etapa1_trace.json`, `etapa2_smoke_trace.json`, `job_full_97c40f18.json`).
