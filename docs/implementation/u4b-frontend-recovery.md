# U4-B — Recuperación de errores en el frontend

**Alcance:** solo local, solo `frontend/`. Sin deploy, sin llamadas reales a la
API, sin push/merge.
**Rama:** `integration/performance-and-ui`
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`

## Causa raíz atendida

`ProcessDetailPage.load()` limpiaba el job local (`setJob(null)`) cada vez que
`active_job` no venía en la respuesta, sin importar si el job local ya había
terminado en error. Como `active_job` solo existe para `queued`/`running`
(contrato backend), cualquier poll posterior a un Finalize fallido borraba el
mensaje de error de la pantalla aunque el backend ya proyectara `last_attempt`
/ `operational_issues` con la evidencia.

## Cambios de código

| Archivo | Cambio |
|---|---|
| `frontend/src/domain/resolveDisplayedAttempt.ts` | Helper puro que decide qué intento mostrar: `active_job` en `queued`/`running` gana; si no, un job local sondeado que quedó **terminal** se conserva; si no, se usa `last_attempt` (o el más reciente de `latest_attempts_by_stage`). Nunca vacía un terminal solo porque `active_job` desapareció. Vive fuera de `lib/` porque ese nombre está en `.gitignore` (artefacto Python). |
| `frontend/src/api/errors.ts` | `UiApiError` (status, errorCode, userMessage, nextAction, severity, issues, technicalReference) + `buildUiApiError` que parsea el `detail` de FastAPI de forma defensiva. |
| `frontend/src/api/client.ts` | `apiFetch` ahora lanza `UiApiError` en vez de un `Error` genérico con propiedades sueltas. |
| `frontend/src/types/contract.ts` | Tipos aditivos `UiLastAttempt`, `UiIssueLocation`, `UiIssueRetry`, `UiOperationalIssue`, `ErrorSeverity`; `UiProcessDetail` gana `last_attempt`, `latest_attempts_by_stage`, `operational_issues` (reflejan `app/application/ui/schemas.py`). |
| `frontend/src/components/OperationalIssuePanel.tsx` | Panel de un `UiOperationalIssue`: título, mensaje, ubicación (hoja/fila/columna), valor encontrado/esperado, siguiente acción, enlace de revisión y botón de reintento (según `issue.retry`). |
| `frontend/src/pages/ProcessDetailPage.tsx` | `load()` ya no limpia el job local si es terminal; usa `resolveDisplayedAttempt` para el resumen de "Job:"/mensaje/siguiente acción; renderiza `OperationalIssuePanel` por cada `operational_issues`; el poll por intervalo (`startJobPoll`) cuenta fallos consecutivos y muestra un aviso a partir del tercero en vez de fallar en silencio indefinidamente. |
| `frontend/src/pages/DashboardPage.tsx` | `classifyProcessBucket` (antes `bucket`, no exportado) prioriza `error_count > 0` **antes** que el estado operacional, así un proceso que sigue en `EN_REVISION` con avisos pendientes (p. ej. Finalize fallido) cae en "Requieren atención" y no en "Activos". Columna renombrada de "Errores recuperables" a "Requieren atención". |
| `frontend/src/mocks/data.ts` | Ajustado a los campos nuevos y obligatorios de `UiProcessDetail`. |

## Test tooling (nuevo)

- Dev deps: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`,
  `@testing-library/user-event`, `jsdom`, `vitest-axe`.
- `frontend/package.json`: script `"test": "vitest run"`.
- `frontend/vite.config.ts`: bloque `test` (`environment: "jsdom"`,
  `setupFiles: ["./src/setupTests.ts"]`).
- `frontend/src/setupTests.ts`: `@testing-library/jest-dom/vitest` + `cleanup()`
  tras cada test.

## Pruebas añadidas

- `frontend/src/domain/resolveDisplayedAttempt.test.ts` — reglas de precedencia
  (activo gana, terminal sondeado se conserva, fallback a `last_attempt` /
  `latest_attempts_by_stage`, caso `kind=none`).
- `frontend/src/pages/ProcessDetailPage.test.tsx` — reproduce el bug: tras un
  segundo `load()` sin `active_job` ni `last_attempt` en el backend, el
  mensaje del job terminal sondeado localmente sigue visible; y renderizado
  del panel de `operational_issues`.
- `frontend/src/pages/DashboardPage.bucket.test.ts` — `CORRECCION_REQUERIDA`,
  `ERROR_RECUPERABLE` y `error_count > 0` (incluso con `EN_REVISION`) →
  `"atencion"`; resto de buckets sin regresión.
- `frontend/src/components/OperationalIssuePanel.test.tsx` — contenido,
  interacción del botón de reintento y verificación `vitest-axe` (regla
  `color-contrast` deshabilitada: requiere canvas real, no soportado por
  jsdom).

## Resultado

```
npm test          → 4 test files, 21 tests, todos en verde
npx tsc --noEmit  → sin errores
npm run build     → build de producción OK (dist/ generado)
```

Sin cambios en `app/` (Python). Sin deploy, sin llamadas reales, sin push.
