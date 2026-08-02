# Layout fechado de artefactos SharePoint (YYYY/MM/día + id8)

**Fecha:** 2026-08-02  
**Deploy:** no incluido en esta entrega

## Objetivo

Organizar artefactos acumulativos por fecha operativa y evitar colisiones de nombre en el mismo día, sin tocar Control ni `01 REVISION`.

## Convención

```
{root_folder}/YYYY/MM/YYYY-MM-DD/{filename}
```

- **Id corto (8 hex):** prefijo del `process_id` sin guiones (p. ej. UUID → `4df53868`).
- El UUID completo sigue en Control (`ProcessKey` / `process_id`) y en el cuerpo JSON del archivo.

## Aplica a

| Artefacto | Root típico | Nombre |
|---|---|---|
| HISTORICO (2 Excels) | `03 HISTORICO` | `cartera_validada_*_{id8}.xlsx`, `soporte_asientos_*_{id8}.xlsx` |
| PDF correo Notify | `04 CORREOS ENVIADOS` | `{plantilla}_{id8}.pdf` |
| Manifiesto merge | trazabilidad / LOGS merge | `merge_manifest_{banco}_{fecha}_{id8}.json` |
| Archivo de procesos | `90…/04 ARCHIVO PROCESOS` | `proceso_{banco}_{fecha}_{id8}.json` |
| Bitácora ejecución | `90…/02 LOGS` (o `06 LOGS`) | `execution_log_*_{id8}.json` |

## No reorganiza

- Control técnico (fila 2 / single-slot)
- `01 REVISION` (sigue plano + UUID completo en filename)
- `CORREOS.xlsx` / IBR / adelantados
- PDFs consolidados Contabilidad / Merge output

## Helper

`app/application/services/dated_artifact_layout.py`

- `short_process_id`, `dated_folder_relative`, `join_dated_artifact_path`
- `ensure_parent_folders` (crea año/mes/día)
- `list_files_under_dated_or_flat` (lectura layout nuevo + día plano legacy)

## Lectura legacy

- Paths guardados en Control se usan tal cual (nuevos o antiguos).
- Listados de archivo/manifiestos recorren jerarquía nueva y carpeta plana.
- `load_process_archive_snapshot` prueba path nuevo, plano con UUID completo, y listado.

## Verificación

- `pytest tests/test_dated_artifact_layout.py tests/test_process_archive.py tests/test_execution_run_log.py`
- Suite completa FE + BE al cerrar.
