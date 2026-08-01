# U4-UX — UI empresarial HBI Capital (implementación local)

**Fecha:** 2026-07-31  
**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`

## HEAD

| Rol | Commit |
|-----|--------|
| HEAD inicial | `740ae13bbfd3798cc1af082a3ca5a42d063de2c1` |
| HEAD código previo U4 | `781f273` (amortización) |
| Tip al cierre docs U4 | ver `git rev-parse HEAD` tras commits documentales |

## Causa raíz (pérdida del error Finalize)

1. Finalize fallido deja Control en `REVISION_CREADA` (correcto).
2. `FinalizeJobId` solo se escribe en éxito → la query UI no cargaba el job fallido.
3. `derive_steps_from_control` ignoraba `status=failed` → step `not_started`.
4. `derive_operational_status` priorizaba `review.in_progress` → `EN_REVISION`.
5. Frontend `load()` hacía `setJob(null)` sin `active_job` → el error desaparecía tras el poll.

## Modelo `last_attempt` / issues

- `UiLastAttempt`, `latest_attempts_by_stage`, `operational_issues` en contrato.
- `JobManager.find_latest_job_by_process_and_types` (lectura pura).
- Tipos reales: `generate`, `finalize`, `notify_validar_extractos`,
  `merge_composite_validado_pdfs`, `amortization_process` (+ PA dry_run/apply).
- Prioridad operativa: corrección → temporal → parcial → activo → pendiente → completado.

## Finalize multi-error (U4-A3)

- Collector puro `_collect_distribucion_pago_issues`.
- 1 issue → `codigo|JSON`; 2+ → `multiple_review_errors` expandido a N `UiOperationalIssue`.
- Sin escrituras mientras hay bloqueos; reglas financieras intactas.

## Frontend

- `resolveDisplayedAttempt` + panel de recuperación + `UiApiError`.
- Copy centralizado (`copy/labels.ts`); ProcessKey solo en Detalles técnicos.
- Dashboard con filtros y «Requieren atención».
- Loading: Spinner, skeletons, ProgressIndicator, PollingStatus.
- Modal accesible (foco, Escape, aria).
- Tokens HBI verde/dorado; contraste texto normal ≥ 4.5:1 medido.

## ZIP candidato

Ver cierre: `azure-deploy-u4-ux-candidate.zip` + SHA-256.
Runtime sandbox; flags Generate/Finalize/Notify/Merge/Amortization true.
**No desplegado.**

## Limitaciones pendientes

- axe página completa Login/Dashboard (sí en Modal / OperationalIssuePanel).
- Progreso incremental solo donde el job emite `progress`.
- `amount_mismatch` / abonos siguen fail-fast (fuera del collector Distribucion_Pagos).
- Despliegue sandbox U4 pendiente de autorización explícita.

## Validaciones locales

- pytest enfocado UI/Finalize/JobManager + suite completa.
- `npm test` / `npm run build`.
- Cero deploy / producción / push / merge / llamadas reales de mutación.
