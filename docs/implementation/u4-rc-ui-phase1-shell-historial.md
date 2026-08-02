# UI Fase 1 — Shell, Panel inline e Historial (Control)

**Fecha:** 2026-08-02  
**Alcance:** frontend + campos aditivos mínimos en API UI  
**Deploy:** no incluido (pendiente fases posteriores)

## Objetivo

Mejorar la UX operativa sin romper el flujo vivo (Generate → Finalize → …) ni el modelo de **1 proceso activo por banco** en Control (fila 2).

## Decisiones de producto

| Tema | Decisión |
|---|---|
| Bancos | Solo Bogotá y Bancolombia (lista genérica por `bank_code` para escalar después) |
| Panel | Bloque **Nuevo proceso** inline (banco → Abrir archivo del banco → Iniciar validación) |
| Chips de filtro en Panel | **Eliminados** (máx. 2 activos; estado en pastilla de tarjeta) |
| Historial | Pestaña de **consulta**; tabla solo con `GET /processes` (Control, 0–2 filas) |
| Nuevo proceso en Historial | **No** |
| Shell | Sidebar Panel / Historial; **Cerrar sesión** abajo; **Operador HBI** arriba a la derecha |
| Snapshot JSON (`04 ARCHIVO PROCESOS`) | **Fase 2** (no en esta entrega) |

## Cambios frontend

- `AppShell.tsx`: layout con sidebar + topbar (entorno + Operador HBI).
- `main.tsx`: ruta `/historial`.
- `DashboardPage.tsx`: Panel sin `tabbar`; bloque Nuevo proceso; tarjetas activas con badge, «Abrir archivo de revisión» (si hay URL) y «Continuar proceso».
- `HistoryPage.tsx`: tabla Control; sin crear proceso.
- `styles.css`: estilos shell, panel nuevo proceso, tabla historial.
- `labels.ts`: textos `view_detail`, `open_bank_template`, `open_review_excel`, `continue_process`; mensajes vacíos Panel/Historial.

## Cambios API (aditivos, no rompen clientes)

- `UiBankCapabilities.bank_input_web_url`: webUrl del Excel de entrada (`BANCO_*.xlsx`) vía Graph/reader.
- `UiProcessSummary.review_excel_web_url`: webUrl del Excel de revisión desde links de proyección.
- `GET /banks` y `summarize()` rellenan esos campos best-effort (fallo → `null`).

No se modifica la escritura de Control ni Generate/Finalize/Notify/Merge/Apply.

## Comportamiento del operador (Panel)

1. Elegir banco.  
2. Opcional: **Abrir archivo del banco** (plantilla/entrada SharePoint).  
3. **Iniciar validación** (mismo POST Generate + confirmación).  
4. En **Procesos activos**: abrir revisión y/o continuar al detalle.  
5. Si el banco ya tiene lote: Retomar desde el selector; la tarjeta muestra Continuar.

## Fuera de alcance (siguientes fases)

- Snapshot JSON en `90…/04 ARCHIVO PROCESOS`.
- Filtros fecha/banco/estado sobre historial largo.
- Detalle histórico solo lectura desde archivo.
- Deploy Azure.

## Verificación

- Frontend: `npm test` (vitest) en `frontend/`.
- Backend: `pytest` (suite UI/API relevante o completa según CI local).
