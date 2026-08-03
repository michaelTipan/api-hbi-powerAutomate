# U4 — R0 lectura UI del Excel de revisión

**Rama:** `feat/ui-in-app-review-and-asientos`  
**Alcance:** solo lectura. Sin PATCH, preflight, Finalize nuevo, upload ni deploy.

## Endpoint

`GET /api/ui/v1/processes/{process_key}/review`

Respuesta `UiReviewResponse`:

| Campo | Uso |
|---|---|
| `etag` | Concurrencia futura (R1 If-Match) |
| `pagos[]` / `abonos[]` | Filas tipadas; `row_key` = `{sheet}\|{id_pago}\|{credito}` |
| `links[]` por fila | `extract` / `folder` / `tabla` (web_url desde hiperlinks Excel) |
| `errors[]` | Hoja Errores; `requires_regeneration`; links extract/folder |
| `read_only` | siempre `true` en R0 |
| `summary` | conteos pagos/abonos/errors |

No acepta `?path` / `?web_url` del cliente.

## Archivos

- `app/application/ui/review_read.py`
- `app/application/ui/schemas.py` (`UiReview*`)
- `app/adapters/primary/http/ui/router_v1.py` (`get_process_review`)
- `frontend/src/components/ReviewReadPanel.tsx`
- `frontend/src/pages/ProcessDetailPage.tsx` (panel)
- `frontend/src/api/client.ts` (`fetchProcessReview`)
- `tests/test_ui_review_read_r0.py`

## Comportamiento UI

Panel «Revisión del lote» en el detalle cuando hay Excel de revisión o fase review/finalize. Tabs Pagos/Abonos, errores con «Ir al crédito» + abrir extracto/carpeta. Sin controles de edición.
