# Extract index performance — plan de implementación

**Tronco producto:** `ui-main` (worktree `D:\CMC\HBI_Capital\wt-ui-main`)  
**Checkpoint UI limpia:** `ui-stable`  
**Rama feature (histórica):** `feature/extract-index-performance`  
**Base histórica:** `develop` / integración `integration/performance-and-ui`  
**Estado:** Fase 3A3 **cerrada** en el tronco; schema SharePoint incompatible (stop manual antes de 3A4)  
**Fecha:** 2026-07-29 / 2026-08-03

> `DECISIONES_TECNICAS_CERRADAS.md` es solo lectura. Este archivo es el diario de extract-index.
> No actualizar `PROJECT_CONTEXT.md` con estado de fases extract-index.
> Continuidad de implementación: **`ui-main`**. No desplegar desde `feature/extract-index-performance`.

---

## Absorción en `ui-main` (2026-08-03)

### Hallazgo

`ui-main` (nacida de `ui-stable`) **ya contiene** todo el extract-index útil:

- Fases 1 → 2B2 → 3A1 → 3A2 → **3A3** (`c1f9e2a`, `b2ccf4e`, router montado, preflight RO).
- Ancestry: `c61ba5a` (3A2) y `c1f9e2a` (3A3) son ancestros de `ui-main`.
- Suites `extract_index`: **145 passed** en `ui-main`.

El único commit de `feature/extract-index-performance` que no está en `ui-main` es
`b71bef5` (*ultimo commit - implementacion pausada*): **solo** `frontend/node_modules`
(0 archivos de producto). **No se mergeó** a propósito.

### Conclusión

No hace falta merge adicional de la feature para “traer” la mejora: el tronco
`ui-main` = UI estable + extract-index hasta 3A3. Siguiente trabajo autorizado:
columnas SharePoint manuales → Fase 3A4 (sin ejecutar aún).

---

## Fase 3A3 — cerrada (2026-07-29/30)

### Alcance ejecutado

- Worktree: `D:\CMC\HBI_Capital\wt-integration-performance-and-ui`
- Rama: `integration/performance-and-ui` (merge FF de `feature/extract-index-performance` @ `c61ba5a`)
- Commit montaje: `c1f9e2a` — `feat: montar admin extract-index y preflight remoto RO (Fase 3A3)`
- `app_factory.py`: wiring lazy + `ExtractIndexAdminState` + `extract_index_admin.router`
- Preflight remoto RO (`remote_preflight.py`): schema + muestra; **0 escrituras**
- `EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED=false` (campañas/chunks bloqueadas)
- Auth: `/extract-index/admin/*` exige `X-API-Key` siempre (deps + middleware)
- Overlay sandbox: flags extract-index + UI off

### Archivos tocados (commit `c1f9e2a`)

- `app/adapters/primary/http/app_factory.py`
- `app/adapters/primary/http/extract_index_admin_deps.py`
- `app/adapters/primary/http/extract_index_admin_wiring.py` (nuevo)
- `app/adapters/primary/http/routers/extract_index_admin.py`
- `app/application/services/extract_index/empty_bootstrap_scope.py` (nuevo)
- `app/application/services/extract_index/remote_preflight.py` (nuevo)
- `config/environments/sandbox.env`
- `tests/test_extract_index_phase3a2_admin_wiring.py`
- `tests/test_extract_index_phase3a3_remote_preflight.py` (nuevo)
- `docs/implementation/extract-index-performance.md`

### Tests

- Auth/gates 3A2+3A3: **25 passed**
- Suite integración completa (previa al deploy): **976 passed, 1 skipped**

### Ventana operativa (preflight)

```
ACTIVE_ENVIRONMENT=sandbox
EXTRACT_INDEX_MODE=off
EXTRACT_INDEX_BOOTSTRAP_ENABLED=true   # solo durante preflight
EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED=false
EXTRACT_INDEX_REMOTE_PREFLIGHT=true
UI_ENABLED=false
UI_WRITE_ENABLED=false
EXTRACT_INDEX_SANDBOX_PATH_MARKER=COMWARE PRUEBAS
```

Al terminar (confirmado en vivo):

```
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false
```

Preflight con clave → **403 `bootstrap_disabled`**.

### Deploy sandbox

- ZipDeploy API: HTTP 400 (conocido / flaky)
- **Kudu VFS** + OneDeploy `type=static&restart=true`: OK
- App URL: `https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net`
- Build marker health: `list-item-probe-20260729` (sin bump)

### Smoke Power Automate (antes y después)

| Check | Resultado |
|---|---|
| `GET /health` | 200 `{"status":"ok",...}` |
| `GET /graph/diagnostics` + key | 200 |
| `GET /graph/diagnostics` sin key | 401 |
| `GET /graph/diagnostics/paths-probe` | `active=sandbox`, `read_only=true`, 16/16 ok |
| Admin sin key | 401 |
| Admin key inválida | 401 |
| `POST .../campaigns/start` | 403 `bootstrap_disabled` (post-ventana) |

### Informe preflight remoto (ventana abierta)

Evidencia: `docs/implementation/preflight-3a3-result.json`

- HTTP 200, `ok: false` — **schema incompatible** (stop esperado; sin auto-fix)
- Listas localizadas:
  - `INDICE_EXTRACTOS` list_id `f096a65b-a643-4127-b193-72ebe51a3cee`
  - `CONTROL_INDICE_EXTRACTOS` list_id `63981e8a-d993-4dfc-9a0d-5d2cf80c45df`
- Site/drive sandbox resueltos; `production_path_used: false`
- Clients base: `INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES`
- Muestra metadata (solo lectura): carpetas bajo raíz sandbox
- **Mutaciones:** `list_item_writes=0`, `drive_mutations=0`, `pdf_downloads=0`, `campaigns_created=0`, `checkpoints_written=0`, `graph_gets=7`

Columnas requeridas faltantes (índice): `ENVIRONMENT`, `CREDIT_KEY`, `DOC_KEY`, `DRIVE_ID`, `ITEM_ID`, `CREDIT_FOLDER_ITEM_ID` (+ opcionales).  
Control: `ENVIRONMENT`, `CAMPAIGN_ID`, `STATUS` (+ opcionales).  
→ **Creación manual por administrador SharePoint antes de 3A4.**

### Rollback

1. `EXTRACT_INDEX_BOOTSTRAP_ENABLED=false` (estado actual).
2. Redeploy desde commit previo a `c1f9e2a` si hay que desmontar el router.
3. Overlay: `.\scripts\switch-env.ps1 -Target sandbox` y verificar `-Status`.
4. No reactivar chunks ni shadow/active/UI sin fase autorizada.

### Propuesta Fase 3A4 (NO ejecutar)

1. Admin SharePoint crea columnas/índice `CREDIT_KEY` según specs.
2. Re-ejecutar preflight RO hasta `ok: true`.
3. Ventana: `BOOTSTRAP_ENABLED=true`, `CHUNKS_ENABLED=true`, `MODE=off`, sandbox.
4. Un solo chunk pequeño (pocos clientes); sin producción; sin UI; sin shadow/active.
5. Verificar escrituras solo en listas técnicas; PA smoke intacto; bootstrap off al cerrar.

---

## Fase 3A2 — cerrada (2026-07-29)

### Alcance

- `GraphDocumentTreeReadOnlyAdapter` (existente) + composición
- `build_allowlisted_extract_index_lists` — MutationGuard + repos índice/control
- `compose_bootstrap_wiring` / `compose_bootstrap_wiring_from_graph`
- Router `extract_index_admin.py` (**no montado** en `app_factory`)
- Gates: `EXTRACT_INDEX_BOOTSTRAP_ENABLED`, `EXTRACT_INDEX_MODE=off`, environment
- Protección `X-API-Key` vía middleware existente (verificada en tests)
- Tests con fakes; cero Graph real; Generate intacto

### Contratos de endpoints

| Método | Ruta | Rol |
|---|---|---|
| POST | `/extract-index/admin/preflight` | Preflight lógico |
| POST | `/extract-index/admin/campaigns/start` | Iniciar / reutilizar campaña |
| POST | `/extract-index/admin/campaigns/{id}/chunks` | Exactamente un chunk |
| GET | `/extract-index/admin/campaigns/{id}?environment=` | Estado |
| POST | `/extract-index/admin/campaigns/{id}/pause` | Pausar |
| POST | `/extract-index/admin/campaigns/{id}/resume` | Reanudar |
| POST | `/extract-index/admin/campaigns/{id}/cancel` | Cancelación limpia |

Respuesta tipada: `campaign_id`, `chunk_id`, `checkpoint`, `continuation_required`,
`status`, `error_summary` sanitizado, métricas agregadas. Sin secretos/tokens.

### Patch exacto pendiente para `app_factory.py` (NO aplicar en esta rama)

```python
# En create_app(), tras los include_router existentes:
from app.adapters.primary.http.routers import extract_index_admin
from app.adapters.primary.http.extract_index_admin_deps import ExtractIndexAdminState
from app.application.services.extract_index.bootstrap_wiring import (
    compose_bootstrap_wiring_from_graph,
)
# + construir scope real, resolver site_id / list_ids, settings

# Solo si EXTRACT_INDEX_BOOTSTRAP_ENABLED y wiring disponible:
# wiring = compose_bootstrap_wiring_from_graph(graph_client, site_id=..., ...)
# app.state.extract_index_admin = ExtractIndexAdminState(wiring=wiring)
# app.include_router(extract_index_admin.router)
```

La composición real (list IDs, scope Graph) y el montaje quedan para
`integration/performance-and-ui` o Fase 3A3/3A4 autorizadas.

### Plan Fase 3A3 (sin implementar)

Preflight remoto sandbox solo lectura: `validate_schema` de ambas listas vía
Graph sandbox; sin mutaciones documentales; sin chunk real.

### Plan Fase 3A4 (sin implementar)

Primer chunk real sandbox (pocos clientes), `EXTRACT_INDEX_MODE=off`,
`EXTRACT_INDEX_BOOTSTRAP_ENABLED=true`, escritura solo en listas técnicas,
checkpoint verificable, abort fail-closed si hay mutación documental.

---

## Fase 3A1 — cerrada (2026-07-29)

### Alcance

Motor bootstrap técnico **desacoplado** (solo fakes/datos locales):

- Modelos: `CampaignScopeKey`, `BootstrapCheckpoint`, `CampaignTotals`, `ChunkResult`
- `BootstrapCampaignService`: start / process_one_chunk / status / pause / resume / cancel
- Puertos: `CreditLockPort`, `BootstrapScopePort`, `ClockPort`
- `InMemoryCreditLock`, reloj inyectable (`FakeClock`)
- Orden por crédito: lock → read → reconcile/parse → upsert → confirm → checkpoint → metrics → unlock
- Presupuesto cooperativo (`max_credits` / `max_seconds`); sin `asyncio.create_task`
- Fail-closed ante `DocumentMutationForbidden`
- Preflight lógico (`extract_index_preflight.py`) sin Graph
- Use cases: `bootstrap_extract_index_chunk`, `extract_index_campaign_status`

### Secuencia de un chunk

```text
start_campaign (idempotente por scope key)
        │
        ▼
process_one_chunk
  ├─ check cancel/pause
  ├─ para cada crédito (si presupuesto OK):
  │    lock.try_acquire ──ocupado (Generate)──► omitir
  │    read candidatos (scope/fake + tree RO)
  │    reconcile/parse
  │    upserts idempotentes ──fallo──► stop; checkpoint NO avanza
  │    checkpoint ──fallo──► stop; crédito NO confirmado; retry OK
  │    metrics + heartbeat
  │    lock.release
  │    check cancel/pause
  └─ continuation_required | completed | paused | cancelled | security
```

### No incluido (diferido)

Graph sandbox real, montaje `app_factory`, bootstrap productivo, `active`,
scheduler, auto-encadenado de chunks. Ver **Fase 3A2** (wiring preparado).

---

## Fase 2B2 — cerrada (2026-07-29)

### Alcance

- Hook único `maybe_evaluate_shadow_after_v2` (`generate_shadow_hook.py`)
- Cableado mínimo en `_load_credit_candidates` y `_load_credit_candidates_for_abono_mora`
  (tras V2 oficial; no muta `statement_*` / `fecha_limite_pdf`)
- `generate_payment_validation(..., shadow_index_evaluator=None)`
- Contexto por job: `evaluated_credit_keys`, presupuesto total
  `EXTRACT_INDEX_SHADOW_TOTAL_BUDGET_SECONDS`
- `mode=off` → `shadow_job_ctx=None` → cero efecto
- `CancelledError` / `KeyboardInterrupt` / `SystemExit` no absorbidos

### Patch exacto pendiente para `integration/performance-and-ui`

No aplicar en esta feature branch. Ejemplo de cableado en el job runner / router
(sin tocar `app_factory.py` aquí):

```python
# En el punto que hoy llama generate_payment_validation(client, process_date, ...):
from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    get_extract_index_settings,
)
from app.application.services.extract_index.index_select_adapter import IndexSelectAdapter
from app.application.services.extract_index.shadow_evaluator import ShadowIndexEvaluator
# + construir list loader, GraphDocumentTreeReadOnlyAdapter, content_endpoint_builder

cfg = get_extract_index_settings()
shadow_evaluator = None
if cfg.mode == ExtractIndexMode.SHADOW:
    adapter = IndexSelectAdapter(
        loader=indice_list_loader,          # Graph list repo read-only
        document_tree=doc_tree_ro,         # GraphDocumentTreeReadOnlyAdapter
        default_fecha_limite_fn=extract_fecha_limite_pago_from_pdf,
    )
    shadow_evaluator = ShadowIndexEvaluator(settings=cfg, adapter=adapter)

result = await generate_payment_validation(
    client,
    process_date,
    bank_code=bank_code,
    job_id=job_id,
    shadow_index_evaluator=shadow_evaluator,  # None si mode=off
)
```

**Reservado (diff vacío en esta rama):** `app_factory.py`, `application.py`,
`requirements.txt`, `startup.sh`, `build-azure-package.ps1`,
`config/environments/*.env`.

### Próxima fase (propuesta, sin implementar)

**Fase 3A2+** cerradas en secciones superiores. Ver plan 3A3/3A4. **No** `active`.


---

## Fase 2B1 — cerrada (2026-07-29)


### Alcance

- `shadow_models.py` — DTOs outcome/skip/divergence/comparison
- `shadow_sampling.py` — muestreo determinista (`env|bank|date|credit_key`)
- `index_select_adapter.py` — selección vía índice (read-only + reconcile + select pura)
- `shadow_evaluator.py` — orquestador aislado (timeout, gates, nunca propaga)
- Settings shadow: banks/dates/timeout/max credits/sample %
- Tests fakes; Generate intacta en 2B1; cero Graph real
- Cableado Generate → **Fase 2B2** (cerrada; ver arriba)

---

## Fase 2A — cerrada (2026-07-29)


### Verificaciones previas

| Check | Resultado |
|---|---|
| `python -m pytest -q` (pre-2A) | **852 passed, 1 skipped** |
| `git diff d9e28b7..3fafe86 --name-only` | Solo archivos Fase 1 (índice/docs/tests); sin Generate |
| `exceptions.py` | Solo **añade** clases nuevas bajo `ExtractIndex*`; `GraphConfigError` intacto; sin status codes ni `/graph/*` |

### Alcance entregado

- `extract_selection_v2.py`: pool + selección V2 **pura** (réplica; **no cableada**)
- `reconcile.py`: motor puro hit/refresh/retry/deleted/fallback
- Tests de paridad vs `_select_extract_by_max_fecha_limite_v2` original
- `payment_validation_generate.py` **intacta** (Generate sigue con V2 original)

### Diferencias históricas observadas (no corregidas)

- `extract_fecha_limite_pago_from_pdf` puede lanzar `PdfStreamError` en PDF truncado
  (no solo devolver `None`). La selección original tampoco lo absorbe; la extraída igual.

### Matriz de paridad (resumen)

Ver tests `test_extract_index_phase2a_parity.py`: solo EXTRACTOS / solo raíz / ambos /
más nuevo en cada lado / sin fecha / empate / rename mismo hash → EXTRACTOS /
vacío / duplicados / NORMAL·ATRASADO·ADELANTADO no alteran selección.

---

## Fase 1 — cerrada (2026-07-29)


### Alcance entregado

- Settings `EXTRACT_INDEX_*` / bootstrap flags
- Modelos + `CREDIT_KEY` / `DOC_KEY`
- Schema validator (sin `create_list`; reporta diffs; exige `CREDIT_KEY` indexada)
- Repos Graph: `INDICE_EXTRACTOS` + `CONTROL_INDICE_EXTRACTOS`
- `DocumentTreeReadOnlyPort` + adapter (sin métodos de escritura)
- `GraphMutationGuard` fail-closed (allowlist por list_id)
- Tests unitarios + `FakeMsGraph` (21 passed)
- **No** se modificó `payment_validation_generate.py`
- **No** wiring en `app_factory.py` / deploy / producción

### Tests

```text
python -m pytest tests/test_extract_index_phase1.py -q
→ 21 passed
```

### Evidencia mutation guard

- GET `/drives/...` permitido
- POST/PUT/PATCH/DELETE `/drives/...` → `DocumentMutationForbidden`
- Escritura a list_id no allowlisted → `UnauthorizedListWriteError`
- Upsert vía guard a list allowlisted → 0 mutaciones documentales

### Pendiente / riesgos Fase 2+

- Columnas reales en SharePoint pueden no existir aún → schema fallará hasta que admin las cree con nombres internos acordados (`column_specs.py`)
- Wiring Generate / extract V2 / bootstrap / router → fases siguientes
- `pytest-cov` no está en el entorno local; cobertura validada por suite dedicada Fase 1

### Diff archivos reservados integración

Vacío (ningún cambio en `application.py`, `app_factory.py`, `requirements.txt`, `startup.sh`, `build-azure-package.ps1`, `config/environments/*`).

---

## 1. Rama y worktree confirmados

| Ítem | Valor |
|---|---|
| Repo | `api-hbi-powerAutomate` |
| Rama | `feature/extract-index-performance` |
| Worktree | `D:\CMC\HBI_Capital\wt-extract-index-performance` |
| Principal | `D:\CMC\HBI_Capital\api-hbi-powerAutomate` → `develop` |
| Independiente de | `feature/operator-web-ui` (aún no creada en este agente) |

---

## 2. Archivos nuevos que se crearán

### Dominio / puertos

| Archivo | Rol |
|---|---|
| `app/domain/ports/extract_index.py` | Puerto de lectura/escritura de ítems de listas (índice + control) |
| `app/domain/ports/document_tree_readonly.py` | Puerto documental **solo lectura** (list/get/download; sin mutaciones) |
| `app/domain/models/extract_index.py` | `CreditKey`, `DocKey`, candidatos, estados de parse, campaign checkpoint |

### Application — índice

| Archivo | Rol |
|---|---|
| `app/application/config/extract_index_settings.py` | `EXTRACT_INDEX_MODE`, bootstrap flags, límites chunk/shadow |
| `app/application/services/extract_index/keys.py` | Construcción `CREDIT_KEY` / `DOC_KEY` + filtro `ENVIRONMENT` |
| `app/application/services/extract_index/schema_validator.py` | Validar columnas/índices de listas existentes (no create_list) |
| `app/application/services/extract_index/list_repository.py` | CRUD ítems vía Graph sobre las 2 listas |
| `app/application/services/extract_index/change_detection.py` | Reglas cTag/eTag/size → download/parse o reutilizar |
| `app/application/services/extract_index/reconcile_credit.py` | Reconciliar candidatos V2 vs índice por crédito |
| `app/application/services/extract_index/select_via_index.py` | Cargar candidatos indexados + aplicar misma selección V2 |
| `app/application/services/extract_index/metrics.py` | Contadores Graph/PDF/hits/misses/fallback |
| `app/application/services/extract_index/credit_lock.py` | Lock lógico por crédito (bootstrap vs Generate) |
| `app/application/services/extract_index/mutation_guard.py` | Fail-closed: abortar POST/PUT/PATCH/DELETE sobre `/drives/...` docs |
| `app/application/services/extract_index/bootstrap_campaign.py` | Campaña por chunks + checkpoint + continuation |
| `app/application/use_cases/bootstrap_extract_index_chunk.py` | Use case admin: un chunk |
| `app/application/use_cases/extract_index_campaign_status.py` | Estado de campaña |
| `app/application/use_cases/extract_index_preflight.py` | Preflight read-only (sandbox o production) |

### Adapters

| Archivo | Rol |
|---|---|
| `app/adapters/secondary/graph_document_tree_readonly.py` | Implementación puerto read-only (solo `get` / `get_bytes`) |
| `app/adapters/secondary/graph_extract_index_lists.py` | Implementación repositorio listas |
| `app/adapters/primary/http/routers/extract_index_admin.py` | Endpoints admin bootstrap/status/preflight (`X-API-Key`) |

### Extracción compartida V2 (sin cambiar reglas)

| Archivo | Rol |
|---|---|
| `app/application/services/extract_selection_v2.py` | Extraer pool + selección `_resolve_extract_pdf_pool` / `_select_extract_by_max_fecha_limite_v2` desde Generate para reutilizar desde índice y bootstrap |

### Docs / tests

| Archivo | Rol |
|---|---|
| `docs/implementation/extract-index-performance.md` | Este diario |
| `tests/test_extract_index_*.py` | Unit/integration por entrega (ver §7) |
| `tests/fakes/fake_readonly_graph.py` | Fake Graph sin métodos de escritura documental |

---

## 3. Archivos existentes que se modificarán

| Archivo | Cambio previsto |
|---|---|
| `app/application/use_cases/payment_validation_generate.py` | Punto de integración: si `mode=off` → igual; `shadow` → V2 oficial + compare; `active` → índice + fallback. Extraer helpers V2 al módulo compartido (comportamiento idéntico). |
| `app/application/services/payment_helpers.py` | Solo si hace falta exportar helpers de parse ya existentes (mínimo). |
| `app/adapters/primary/http/routers/diagnostics.py` | Opcional: endpoint schema-validate de listas (read-only schema check); **no** create_list. |
| `tests/test_generate_validation.py` | Extender con modos off/shadow/active y fallback. |

**No** tocar lógica financiera de Finalize/Notify/Merge/Amortización.

---

## 4. Archivos reservados para integración

Documentar diff propuesto; **no editar en esta rama:**

- `application.py`
- `app_factory.py` → **nota:** el router admin necesita `include_router`; se documentará el patch exacto para `integration/performance-and-ui` (o se pedirá excepción mínima si el usuario autoriza un wiring local detrás de flag).
- `requirements.txt` (solo si hace falta dep nueva — preferible no)
- `startup.sh`
- `build-azure-package.ps1`
- `config/environments/*.env` → variables nuevas documentadas; overlay real en integración

Variables a documentar para overlays:

```text
EXTRACT_INDEX_MODE=off|shadow|active
EXTRACT_INDEX_BOOTSTRAP_ENABLED=false|true
BOOTSTRAP_MAX_CLIENTS_PER_CHUNK=3
BOOTSTRAP_MAX_SECONDS_PER_CHUNK=180
EXTRACT_INDEX_SHADOW_MAX_CREDITS=
EXTRACT_INDEX_SHADOW_SAMPLE_PCT=
EXTRACT_INDEX_LIST_NAME=INDICE_EXTRACTOS
EXTRACT_INDEX_CONTROL_LIST_NAME=CONTROL_INDICE_EXTRACTOS
```

---

## 5. Contratos que permanecerán intactos

- Todas las rutas `/graph/*` usadas por Power Automate
- Auth `X-API-Key`
- Bodies/respuestas de Generate (job_id, polling, estados)
- Parse JSON / correos / botones PA
- Selección V2: ganador por `fecha_limite` + reglas actuales (pool combinado raíz+EXTRACTOS, SHA-256 dedupe, preferencia EXTRACTOS)
- `scripts/switch-env.ps1` y semántica `ACTIVE_ENVIRONMENT`

Endpoints **nuevos** solo admin bajo prefijo tipo `/graph/diagnostics/extract-index/*` o `/graph/admin/extract-index/*` (no usados por PA).

---

## 6. Orden propuesto de commits

1. `docs:` plan + mapa de archivos (este documento)
2. `feat:` settings + keys + modelos + schema_validator (sin wiring Generate)
3. `feat:` list_repository + tests CRUD fake / contract
4. `feat:` document_tree_readonly + mutation_guard + tests fail-closed
5. `refactor:` extraer `extract_selection_v2` desde Generate (paridad tests existentes)
6. `feat:` reconcile + select_via_index + metrics + mode `off` cableado (noop path)
7. `feat:` mode `shadow` muestreado + logs de divergencia
8. `feat:` mode `active` + fallback por crédito
9. `feat:` credit_lock + bootstrap_campaign + chunk use case + status
10. `feat:` preflight read-only + admin router (wiring documentado para integración)
11. `test:` suite seguridad cero mutaciones + paridad sandbox
12. `docs:` checklist Etapas A–E y rollback

---

## 7. Tests por entrega

| Entrega | Tests |
|---|---|
| Schema/listas | Listas existentes; rechazo create_list; columnas requeridas |
| Keys | CREDIT_KEY/DOC_KEY; filtro ENVIRONMENT; no mezcla sandbox/prod |
| Change detection | nuevo / mismo cTag / cTag distinto / ausente / eliminado / parse_error |
| Fail-closed | Intento POST/PUT/PATCH/DELETE a `/drives/...` → abort + violación logueada |
| Read-only port | Interfaz sin métodos de escritura; fake Graph |
| V2 extract | Tests Generate existentes siguen verdes tras extracción de módulo |
| off | Generate idéntico a baseline |
| shadow | Resultado = V2; métricas de divergencia; límite de muestra |
| active | Hit índice; miss → fallback V2; índice caído → V2 |
| Bootstrap técnico | Chunk termina; checkpoint; continuation; cancel/pause; recycle resume |
| Lock | Generate gana; bootstrap omite crédito |
| Preflight | Cero escrituras a listas ni drive en preflight |
| Métricas | Contadores presentes en resultado/job enrichment |

**Garantía de mutación cero (productivo):** tests de espía sobre Graph que fallen si aparece mutación documental.

---

## 8. Riesgos de integración

| Riesgo | Mitigación |
|---|---|
| `app_factory.py` reservado → router admin no montado | Patch documentado; merge solo en `integration/performance-and-ui` |
| Generate es monolito (~3.8k líneas) | Extraer V2 con tests de paridad antes de cablear índice |
| Columnas de listas aún no definidas en SharePoint | Schema validator + doc de columnas; admin crea columnas a mano si faltan |
| Un solo worker: bootstrap vs PA | Chunks cortos; lock; bootstrap `false` por defecto |
| Un App Service = un ambiente | Ventanas de overlay; no bootstrap prod + UI sandbox simultáneos |
| Confundir bootstrap sandbox con índice real | Etapas A vs C explícitas; `ENVIRONMENT` obligatorio |
| Wiring Generate rompe PA | Default `EXTRACT_INDEX_MODE=off`; shadow antes de active |
| Conflicto con rama UI | No tocar frontend/ui; locks documentados para integración |

---

## 9. Estrategia de rollback

1. `EXTRACT_INDEX_MODE=off` → comportamiento previo inmediato (sin redeploy de lógica si flag ya desplegado).
2. `EXTRACT_INDEX_BOOTSTRAP_ENABLED=false` → corta campañas.
3. Redeploy commit pre-feature desde `develop` / integración anterior.
4. Filas de índice son caché: se pueden vaciar/filtrar por ENVIRONMENT sin tocar Documentos.
5. Nunca “rollback” borrando carpetas de clientes.

---

## 10. Diseño de la barrera fail-closed

```text
Bootstrap / refresh productivo
        │
        ▼
DocumentTreeReadOnlyPort  ──►  solo graph.get / graph.get_bytes
        │                        paths: /drives/{id}/root:..., /items/{id}/content
        │
        ✗  NO recibe GraphApiPort completo
        │
MutationGuard (wrapper opcional en tests/prod bootstrap)
        │  si método ∈ {POST,PUT,PATCH,DELETE} y path match /drives/... (no /lists/...)
        │  → raise DocumentMutationForbidden
        │  → abort chunk, security_violation=true, continuation_required=false o paused
        ▼
ExtractIndexListRepository
        │  SOLO /sites/{id}/lists/{listId}/items...
        └── POST/PATCH/DELETE ítems permitidos
```

Confirmación: **cero mutaciones documentales productivas** por diseño + tests de espía.

---

## 11. Distinción bootstrap técnico vs productivo

| | Técnico (sandbox) | Productivo |
|---|---|---|
| Objetivo | Probar mecanismo | Poblar índice útil |
| `ACTIVE_ENVIRONMENT` | `sandbox` | `production` |
| Datos | Carpetas 03 COMWARE PRUEBAS (pueden estar atrasadas) | Árbol real `INFORMACION CREDITOS-CLIENTES` |
| Escrituras | Ítems listas con `ENVIRONMENT=sandbox` | Ítems con `ENVIRONMENT=production` |
| `EXTRACT_INDEX_MODE` durante | `off` (salvo pruebas shadow locales) | **`off`** mientras se llena |
| Representa prod? | **No** | **Sí** (caché del árbol real) |

---

## 12. Confirmaciones explícitas

- [x] No se crearán contenedores de listas (`create_list` prohibido).
- [x] No se modificará el árbol documental productivo (solo lectura + download).
- [x] Únicas escrituras: ítems en `INDICE_EXTRACTOS` y `CONTROL_INDICE_EXTRACTOS`.
- [x] No se desplegará esta rama sola al App Service.
- [x] Fase 1 / 2A / 2B1 / 2B2 / 3A1 / 3A2 cerradas (`active` no; Graph real no; router no montado).

---

## Próximo paso

Esperar autorización para **Fase 3A3** (preflight remoto sandbox RO) o
**Fase 3A4** (primer chunk real sandbox). **No** montar `app_factory` ni
modificar `PROJECT_CONTEXT.md` sin autorización.
