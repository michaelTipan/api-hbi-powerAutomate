# Plan U4-UX — UI empresarial HBI Capital

**Rama:** `integration/performance-and-ui`  
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`  
**HEAD inicial:** `740ae13bbfd3798cc1af082a3ca5a42d063de2c1`  
**Último código (no-docs):** `781f273` (amortización)  
**Alcance:** solo local. Sin deploy, sin llamadas reales, sin push/merge.

## Objetivo

Convertir la Web UI en una app operativa comprensible, recuperable y accesible.
Prioridad: recuperación de errores → persistencia → lenguaje → carga → IA → visual → a11y.

## Causa raíz (defecto crítico)

1. Finalize fallido deja Control en `REVISION_CREADA` (correcto).
2. `FinalizeJobId` solo se escribe en éxito → query UI no carga el job fallido por ID de control.
3. `derive_steps_from_control` ignora `status=failed` de Finalize → step queda `not_started`.
4. `derive_operational_status` prioriza `review.in_progress` → `EN_REVISION` antes de evaluar fallo.
5. `derive_errors` no proyecta fallos de Finalize desde jobs.
6. Frontend `load()` hace `setJob(null)` si no hay `active_job` → el error desaparece tras el poll.

## Mapping de tipos JobManager (reales)

| Etapa UI | Tipos `type` en job |
|----------|---------------------|
| generate | `generate` |
| finalize | `finalize` |
| notify | `notify_validar_extractos` (+ alias lectura `notify`) |
| merge | `merge_composite_validado_pdfs` (+ alias `merge`) |
| amortization | `amortization_process` (UI); `amortization_dry_run` / `amortization_apply` (PA) |

## Fases

- **U4-A0** Tests que reproducen la pérdida del error.
- **U4-A1** `last_attempt` + `find_latest_job_by_process_and_types` + proyección.
- **U4-A2** `UiOperationalIssue` + parseo seguro `codigo|JSON`.
- **U4-A3** ✅ Acumulación múltiple de errores Finalize (commit aparte).
  Local, sin deploy. Detalle en `PROJECT_CONTEXT.md`.
- **U4-B** ✅ Frontend: no borrar terminal; panel recuperación; `UiApiError`.
  Local, sin deploy. Docs: `docs/implementation/u4b-frontend-recovery.md`.
- **U4-C** Copy operativo + jerarquía detalle + dashboard.
- **U4-D** Loading / polling / skeletons.
- **U4-E** Modales a11y + tokens + login + contraste.
- Docs + ZIP candidato.

## Reglas

- Control = verdad de negocio; último intento = evidencia de acción.
- No cambiar reglas financieras, idempotencia, ProcessKey ni contratos PA.
- Tests con fixtures/dobles únicamente.
