# UI Fase 2 — Archivo de procesos (snapshots JSON)

**Fecha:** 2026-08-02  
**Deploy:** no incluido en esta entrega

## Objetivo

Persistir un **snapshot de solo lectura** al cerrar un proceso (o antes de que Generate limpie el Control), sin convertir el Excel de Control en multi-fila.

## Carpeta

```
{PAYMENT_VALIDATION_BASE_FOLDER}/90 ACCESO RESTRINGIDO/04 ARCHIVO PROCESOS/
  proceso_{bank_code}_{YYYY-MM-DD}_{process_id}.json
```

Variable: `PAYMENT_VALIDATION_ARCHIVE_FOLDER` (sandbox y production overlays).

## Cuándo se escribe

1. **Principal:** Apply con `status == ok` → `AMORTIZACION_APLICADA` (antes de limpiar `ValidationFilePath`).
2. **Red de seguridad:** Generate cuando el `ProcessKey` anterior ≠ nuevo (p. ej. tras completado).

Cancel → VACIO **no** archiva (aborto pre-Finalize).

Escritura **best-effort**: fallo de Graph no tumba Apply/Generate.

## API

| Endpoint | Uso |
|---|---|
| `GET /api/ui/v1/process-history` | Activos (Control) + archivados; `?bank_code=` opcional |
| `GET /api/ui/v1/process-history/{process_key}` | Detalle solo lectura del snapshot |

`GET /api/ui/v1/processes` sigue siendo **solo Control** (Panel sin cambios de contrato).

## Frontend

- Historial: filtros banco/origen; filas activas → `/processes/...`; archivadas → `/historial/...`.
- Detalle histórico: documentos con `web_url` resueltos; sin acciones de escritura.

## Módulo

`app/application/ui/process_archive.py` — build/upload/list/load.

## Verificación

- `pytest tests/test_process_archive.py tests/test_environment_overlays.py`
- Suite completa FE + BE al cerrar la fase.
