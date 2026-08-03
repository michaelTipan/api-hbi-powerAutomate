# U4-RC — Catálogo de documentos (drawer) para links N

Fecha: 2026-08-02  
Rama: `integration/performance-and-ui`

## Problema

Con lotes grandes (p. ej. 15–50 pagos), listar todos los PDFs consolidados,
carpetas ASIENTOS o tablas de amortización como botones en «Documentos por fase»
satura la página y obliga a scroll excesivo.

## Decisión de producto

| Artefacto | UI |
|---|---|
| Excel revisión, histórico, secretaría, **PDF correo** | Botón 1:1 (se mantiene) |
| PDFs consolidados (N≥2) | Resumen + catálogo modal |
| Carpetas ASIENTOS | Solo mientras Merge está activo (carga); N≥2 → catálogo |
| Asientos individuales en PROCESADOS | **No** en UI (van dentro del consolidado) |
| Tablas de amortización | Grupo en «Archivos del proceso» + catálogo |

## Contrato (aditivo, no rompe clientes viejos)

- `UiProcessDetail.document_groups[]` y `UiHistoryDetail.document_groups[]`
  (`id`, `title`, `count`, `links[]`).
- `links` 1:1 del lote **no se eliminan**.
- Job Apply `result_summary` incluye `tables_updated_links` + `tables_uploaded_count`.
- Snapshot de archivo JSON puede incluir `document_groups` (ausente = legacy OK).

## Archivos clave

| Capa | Path |
|---|---|
| Catálogo BE | `app/application/ui/document_catalog.py` |
| Schemas | `app/application/ui/schemas.py` (`UiDocumentGroup`) |
| Proyección | `app/application/ui/process_projection.py` |
| Archivo | `app/application/ui/process_archive.py` |
| Apply → archive | `app/application/use_cases/amortization_fill_apply.py` |
| History GET | `app/adapters/primary/http/ui/router_v1.py` |
| FE dominio | `frontend/src/domain/documentCatalog.ts` |
| FE drawer | `frontend/src/components/LinkCatalogDrawer.tsx` |
| Detalle | `frontend/src/pages/ProcessDetailPage.tsx` |
| Historial | `frontend/src/pages/HistoryDetailPage.tsx` |

## Compatibilidad / riesgos

- Archivos históricos **sin** `document_groups`: siguen mostrando links del lote
  (revisión/histórico/correo); tablas amort. solo en procesos archivados **después**
  de este cambio.
- Si el job Apply se perdió por reciclaje App Service, el grupo amort en proceso
  activo puede quedar vacío hasta que exista en el JSON de archivo.
- Carpetas ASIENTOS ocultas en COMPLETADO: comportamiento intencional.

## Tests

- `tests/test_document_catalog.py`
- `frontend/src/domain/documentCatalog.test.ts`

## Rollback

Revertir el commit; el campo `document_groups` es opcional y los clients antiguos
ignoran campos desconocidos.
