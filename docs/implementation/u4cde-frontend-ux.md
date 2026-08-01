# U4-C/D/E — Lenguaje operativo, carga/polling y accesibilidad del frontend

**Alcance:** solo local, solo `frontend/`. Sin deploy, sin llamadas reales a la
API, sin push/merge.
**Rama:** `integration/performance-and-ui`
**Worktree:** `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`

## U4-C — Lenguaje operativo + arquitectura de información

- **`frontend/src/copy/labels.ts`**: catálogo único de textos. Traduce:
  - `stageLabels` — etapas/tipos de job (`generate`→«Preparación de la
    revisión», `finalize`→«Cierre de la revisión»,
    `notify`/`notify_validar_extractos`→«Envío de la validación»,
    `merge`/`merge_composite_validado_pdfs`→«Consolidación de soportes»,
    `amortization*`→«Procesamiento financiero»/«Verificación de
    amortización»/«Aplicación de amortización»).
  - `statusLabels` — estados de job/etapa (`queued`, `running`, `completed`,
    `failed`, `not_started`, `in_progress`, `failed_retryable`, etc.).
  - `operationalStatusLabels` — `OperationalStatus` de negocio y
    `control_estado_proceso` técnico en un solo lugar (p. ej.
    `EN_REVISION`→«Revisión pendiente», `REVISION_CREADA`→«Archivo de
    revisión disponible», `CORRECCION_REQUERIDA`→«Requiere corrección»).
  - `actionLabels` / `confirmTitles` / `busyLabels` para botones y modales.
- **`ProcessDetailPage`** reestructurada: encabezado (banco, fecha, estado
  operativo, ambiente, volver) → panel "Siguiente paso recomendado" (usa
  `next_actions` del backend, antes sin usar en la UI) → "Problemas
  operativos" (`OperationalIssuePanel`, ya existía) → progreso compacto por
  etapa con la acción correspondiente **en línea** dentro de cada fila
  (reemplaza las cuatro tarjetas siempre expandidas de
  Finalize/Notify/Merge/Amortización) → "Documentos del proceso" → "Ayuda
  para completar la revisión" (plegada) → historial de intentos (plegado,
  `AttemptHistory`) → Detalles técnicos (plegado, `aria-expanded`,
  `ProcessKey`/`EstadoProceso`/ids de job/claves de idempotencia).
- **`DashboardPage`**: subtítulo sin "Generate/JobManager"
  («Inicie la validación del archivo bancario cargado…»); tabs Todos /
  Requieren atención / En curso / Esperando soportes / Parciales /
  Completados con contador y mensaje vacío estándar («No hay procesos en
  esta categoría.»); tarjetas sin `process_key` visible.
- `operator_checklist` pasa de lista siempre visible a `Disclosure`
  "Ayuda para completar la revisión", cerrada por defecto.
- `LoginPage`: ver U4-E (mostrar/ocultar contraseña, Bloq Mayús, spinner).

## U4-D — Carga y polling

Componentes nuevos en `frontend/src/components/`:

| Componente | Uso |
|---|---|
| `Spinner` | Indicador mínimo (`role="status"` + texto oculto). |
| `LoadingButton` | Botón con `aria-busy`, deshabilitado mientras `busy`, texto operativo (`busyLabel`) en vez de solo un ícono. |
| `Skeleton` (`CardSkeleton`, `PageSkeleton`) | Reemplaza "Cargando…" desnudo en la carga inicial del dashboard y el detalle. |
| `ProgressIndicator` | Fase (`validating`/`applying`) + `current`/`total` de `job.progress`; el porcentaje **solo** se calcula si `total` es numérico — nunca se inventa. Usado en Generate (Dashboard, `bank_rows_done/total`) y en amortización (`ProcessDetailPage`). |
| `PollingStatus` | Aviso persistente cuando el sondeo de un job falla repetidas veces (ya existía el conteo de fallos en U4-B; aquí se estandariza el render). |

## U4-E — Modal, tokens de diseño y accesibilidad

- **`Modal` / `ConfirmDialog`** (`frontend/src/components/`): diálogo
  accesible reutilizable — `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby`/`aria-describedby`, trampa de foco (Tab/Shift+Tab
  cíclico), cierre con Escape, restauración del foco anterior al cerrar y
  `inert`/`aria-hidden` sobre `#root` mientras está abierto. Reemplaza los
  `<div role="dialog">` manuales de Dashboard/ProcessDetailPage. Títulos:
  «Iniciar validación», «Finalizar revisión», «Enviar validación»,
  «Consolidar soportes», «Procesar amortización».
- **`styles.css`**: variables de superficies (`--bg*`), marca
  (`--brand-green`, `--brand-gold`), semántica (`--success/--info/--warning
  /--error` + `*-soft`), foco (`--focus`), espaciado (`--space-1..6`),
  radios (`--radius-sm/md/lg`) y escala tipográfica (`--text-xs..xl`) sobre
  la base verde/dorado ya existente (no púrpura, no crema/terracota).
  Estilos nuevos: spinner, skeleton (shimmer), barra de progreso,
  disclosure, tabs, botones con `min-height: 44px` y jerarquía
  primaria/secundaria, `:focus-visible`, `.skip-link`, `.sr-only`.
- **`statusClass` (`AppShell.tsx`)**: `EN_REVISION` deja de mapear a `"ok"`
  (verde de éxito) — pasa a `"info"` (estado neutral de espera de acción
  humana). `in_progress` y `CORRECCION_REQUERIDA` se confirman fuera de
  `"ok"` (ya estaban correctos, cubiertos por test de regresión).
- **`AppShell`**: enlace "Saltar al contenido principal" + `<main
  id="main-content" tabIndex={-1}>` envolviendo las páginas.
- **`LoginPage`**: botón accesible para mostrar/ocultar contraseña
  (`aria-pressed`, `aria-label`), aviso de Bloq Mayús
  (`getModifierState("CapsLock")`), envío con `LoadingButton`
  (`aria-busy` + "Validando…"). Autenticación/cookies sin cambios.

## Pruebas añadidas

- `frontend/src/copy/labels.test.ts` — mapeo de etapas/estados/acciones.
- `frontend/src/components/Modal.test.tsx` — `role=dialog`, foco inicial,
  Escape (con y sin `closeDisabled`), trampa de foco (Tab cíclico), axe.
- `frontend/src/components/AppShell.statusClass.test.ts` — semántica de
  color: `EN_REVISION`/`in_progress` no son `"ok"`, `CORRECCION_REQUERIDA`
  es `"danger"`.
- `frontend/src/pages/DashboardPage.copy.test.tsx` — sin
  Generate/Finalize/JobManager/ProcessKey en el copy visible; copy
  operativo del subtítulo; mensaje vacío estándar; sin `process_key` en
  tarjetas.
- `frontend/src/pages/ProcessDetailPage.copy.test.tsx` — sin
  ProcessKey/Generate/Finalize fuera de Detalles técnicos; ProcessKey
  visible solo al expandir Detalles técnicos (`aria-expanded`).

## Resultado

```
npm test          → 9 test files, 45 tests, todos en verde
npx tsc --noEmit  → sin errores
npm run build     → build de producción OK (dist/ generado)
```

## Gaps conocidos vs. el spec completo de U4

- El panel "Siguiente paso recomendado" usa `next_actions` tal como lo
  proyecta el backend (antes no se consumía en la UI); no se implementó
  lógica adicional de priorización en el frontend cuando `next_actions`
  viene vacío (caso no cubierto por los mocks actuales).
- No se agregó un test de `vitest-axe` dedicado para `LoginPage` ni para
  `DashboardPage`/`ProcessDetailPage` completos (sí existe para
  `OperationalIssuePanel` y `Modal`); el árbol completo de esas páginas
  tiene más superficie (enlaces externos, banners) que puede requerir
  ajuste de reglas de axe para evitar falsos positivos.
- `ProgressIndicator` con `current`/`total` solo está cableado para
  Generate (`bank_rows_done/total`) y amortización (`job.progress`
  genérico); Finalize/Notify/Merge no emiten progreso incremental hoy.
- No se tocó el backend (`app/`); los catálogos de `labels.ts` son un
  mapeo de presentación, no reemplazan los mensajes `user_message` /
  `next_action` que ya vienen del backend (que siguen siendo la fuente de
  verdad para variantes no cubiertas por el mapeo estático).
