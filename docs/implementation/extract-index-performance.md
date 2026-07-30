# Extract index performance — plan de implementación

**Rama:** `feature/extract-index-performance`  
**Worktree:** `D:\CMC\HBI_Capital\wt-extract-index-performance`  
**Base:** `d9e28b7` (`develop` — Estado estable antes de mejoras con UI e Indices)  
**Estado:** Fase 1 implementada (sin cablear Generate)  
**Fecha:** 2026-07-29

> `DECISIONES_TECNICAS_CERRADAS.md` es solo lectura. Este archivo es el diario de la rama.

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
- [x] No se escribe código de producto hasta autorización explícita por fase.

---

## Próximo paso (espera autorización)

Autorizar **Fase 0/1:** commits de settings + keys + schema_validator + list_repository + fail-closed port (sin cablear Generate todavía).
