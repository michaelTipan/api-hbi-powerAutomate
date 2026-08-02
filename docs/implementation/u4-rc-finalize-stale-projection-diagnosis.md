# Diagnóstico: UI stale tras Finalizar (hasta recargar)

**Fecha:** 2026-08-01  
**Síntoma:** Tras «Finalizar revisión» OK, la pantalla muestra «Requiere corrección», stepper en «Revisar archivo» y aún «Finalizar»; el mensaje del job dice que finalizó bien. Al recargar, queda «Validación finalizada» + fase «Enviar validación».

## Causa (verificada en código)

1. Finalize termina y el **job** queda `completed` con `user_message` / URLs de histórico (el panel de intento lo muestra vía `resolveDisplayedAttempt` → job polled).
2. El detalle hace **un** `GET /processes/{key}` en cuanto el job es terminal.
3. En ese instante el **Control Excel** en SharePoint a menudo **aún no** tiene `EstadoProceso=FINALIZADO` ni `HistoricalFilePath`.
4. La proyección (`process_projection.py`) entonces:
   - `review` sigue `in_progress` (`REVISION_CREADA`);
   - `jm_status("finalize") == "completed"` y `not has_historical` → paso finalize = **`failed_business`** («Job Finalize completed sin histórico persistente»);
   - `derive_operational_status` prioriza `failed_business` → **`CORRECCION_REQUERIDA`** («Requiere corrección»).
5. Recargar segundos después ya ve Control actualizado → `PENDIENTE_NOTIFICACION` / «Validación finalizada».

No es que Finalize haya fallado: es **carrera job JSON vs Control**.

## Corrección FE (local)

- Poll de job con **tick inmediato** (como el dashboard).
- Tras job terminal: **reintentos de GET** con backoff hasta que la proyección refleje el job (`projectionReflectsTerminalJob`) o se agoten los intentos.

Archivos: `frontend/src/domain/jobProjectionSync.ts`, `ProcessDetailPage.tsx`.
