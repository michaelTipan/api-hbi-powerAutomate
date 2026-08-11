# Implementación — U3-C2 Merge / Consolidar soportes (UI)

**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD código:** `2f76754`  
**Estado:** **Cerrado en sandbox** (2026-07-31). Deploy Paso 1+2 + Merge real OK.  
**Prohibido aún:** producción, Dry-run, Apply, push, merge git.

Plan: `docs/plans/u3c2-merge-from-ui.md`

---

## Runtime final (sandbox)

```text
ACTIVE_ENVIRONMENT=sandbox
UI_ENABLED=true
UI_WRITE_ENABLED=true
UI_FINALIZE_ENABLED=true
UI_NOTIFY_ENABLED=true
UI_MERGE_ENABLED=true
UI_AUTH_MODE=local_session
# Extract-index eliminado del runtime (refactor v3); no hay EXTRACT_INDEX_*
# Contabilidad off · mocks off
```

---

## Paquetes

| ZIP | SHA-256 |
|-----|---------|
| `azure-deploy-u3c2-merge-off.zip` | `67B949F11452E6D4412DD963924EE344B3AA50BC82B660572C70E6A08ADE8399` |
| `azure-deploy-u3c2-merge-enabled.zip` | `93F1A3C65035BF6FF86DEC7054EEB495D4AF5B7D8CEC98E73C1E3451D35A0537` |

Diferencia off→enabled: **solo** `UI_MERGE_ENABLED` (`app/` idéntico).

Deploy: Kudu VFS + OneDeploy `static restart=true`.

---

## Etapa 1 (Merge off)

- Bootstrap: `merge_allowed=false`, `notify_allowed=true`, sandbox.
- POST Merge UI → **403** `ui_merge_disabled` (sin job/Graph/control).
- Jobs: 56 total / 2 Notify / 0 Merge (sin cambio).
- PA: diagnostics 200 / sin key 401 / paths-probe sandbox read_only; contratos Merge presentes (sin POST real).
- Código wwwroot: MergeQueueService + JobManager merge + readiness; PA sin `_validation_jobs`.

---

## Etapa 2 — readiness y soportes

ProcessKey:
`payment-validation|banco_bogota|2026-07-30|8a5c7ad3-faae-412f-928d-5878442c700d`

| Fase | Resultado |
|------|-----------|
| Readiness inicial | `incomplete` — faltaban asientos CRED 215 (PAGO) y 320 (ABONO) |
| Generador | reportlab (estructura `_generate_asientos_prueba.py`) |
| Archivos | `SANDBOX_U3C2_*_CRED_215_abe432d6.pdf`, `…_CRED_320_c4d43ca3.pdf` |
| Trazabilidad | `D:\CMC\HBI_Capital\_work\u3c2_merge_supports\trace.json` |
| Readiness final | `ready` (2/2), `available_actions.merge.allowed=true` |

---

## Smoke Merge real

| Check | Resultado |
|-------|-----------|
| POST 1 | **202** job `28e3c05e-0fcc-4185-8f81-78d9d4c59a1c` |
| Doble clic | **409** `merge_busy` |
| Poll | `completed` (~23 s) |
| Control | `CONSOLIDADO`, `IsActive=true`, mismo ProcessKey |
| MergeIdempotencyKey | = ProcessKey |
| Email/histórico/NotifyIdem | intactos |
| Step merge | `completed` |
| Reintento UI | **409** `already_merged` |
| Jobs | 57 / 2 Notify / **1** Merge |
| Correos nuevos | 0 |
| Dry-run / Apply | 0 |
| Rollback | no usado |

Evidencia smoke: `D:\CMC\HBI_Capital\_work\u3c2_merge_supports\smoke_result.json`

---

## Rollback específico (si hiciera falta)

```text
UI_MERGE_ENABLED=false
```

No apaga Generate / Finalize / Notify.
