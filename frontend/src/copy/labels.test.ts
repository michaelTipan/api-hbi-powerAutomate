import { describe, expect, it } from "vitest";
import {
  actionExplanations,
  actionLabels,
  confirmTitles,
  jobSuccessCopy,
  isOperationalStatusBusy,
  operationalStatusLabel,
  stageLabel,
  statusLabel,
} from "./labels";

describe("catálogo de textos operativos (labels)", () => {
  it("traduce etapas técnicas / tipos de job a lenguaje operativo", () => {
    expect(stageLabel("generate")).toBe("Preparación de la revisión");
    expect(stageLabel("finalize")).toBe("Cierre de la revisión");
    expect(stageLabel("notify_validar_extractos")).toBe("Envío del correo");
    expect(stageLabel("merge_composite_validado_pdfs")).toBe("Generación del PDF consolidado");
    expect(stageLabel("amortization_process")).toBe("Procesamiento financiero");
  });

  it("una etapa desconocida usa respaldo humano, nunca el código crudo", () => {
    expect(stageLabel("etapa_futura_no_mapeada")).toBe("Etapa del proceso");
    expect(stageLabel(null)).toBe("Proceso");
    expect(stageLabel(undefined)).toBe("Proceso");
  });

  it("traduce estados operativos de negocio y de control técnico", () => {
    expect(operationalStatusLabel("EN_REVISION")).toBe("Revisión pendiente");
    expect(operationalStatusLabel("REVISION_CREADA")).toBe("Archivo de revisión disponible");
    expect(operationalStatusLabel("PENDIENTE_NOTIFICACION")).toBe("Pendiente de envío");
    expect(operationalStatusLabel("ESPERANDO_SOPORTES")).toBe("Esperando asientos contables");
    expect(operationalStatusLabel("PENDIENTE_ASIENTOS")).toBe("Esperando asientos contables");
    expect(operationalStatusLabel("CORRECCION_REQUERIDA")).toBe("Requiere corrección");
    expect(operationalStatusLabel("COMPLETADO")).toBe("Completado");
    expect(operationalStatusLabel("DESCONOCIDO")).toBe("No se pudo determinar el estado");
    expect(operationalStatusLabel("CODIGO_DESCONOCIDO_XYZ")).toBe("Estado en revisión");
  });

  it("traduce estados de job/etapa", () => {
    expect(statusLabel("queued")).toBe("En cola");
    expect(statusLabel("running")).toBe("En curso");
    expect(statusLabel("completed")).toBe("Completado");
    expect(statusLabel("failed")).toBe("Con problemas");
    expect(statusLabel("not_started")).toBe("Sin iniciar");
    expect(statusLabel("in_progress")).toBe("En curso");
  });

  it("marca estados operativos con trabajo en curso", () => {
    expect(isOperationalStatusBusy("GENERANDO")).toBe(true);
    expect(isOperationalStatusBusy("FINALIZANDO")).toBe(true);
    expect(isOperationalStatusBusy("NOTIFICANDO")).toBe(true);
    expect(isOperationalStatusBusy("CONSOLIDANDO")).toBe(true);
    expect(isOperationalStatusBusy("APLICANDO")).toBe(true);
    expect(isOperationalStatusBusy("SINCRONIZANDO")).toBe(true);
    expect(isOperationalStatusBusy("EN_REVISION")).toBe(false);
    expect(isOperationalStatusBusy("COMPLETADO")).toBe(false);
    expect(isOperationalStatusBusy(null)).toBe(false);
  });

  it("los títulos de confirmación no usan jerga técnica en inglés", () => {
    for (const title of Object.values(confirmTitles)) {
      expect(title).not.toMatch(/Generate|Finalize|Notify|Merge/i);
    }
  });

  it("las acciones tienen una etiqueta operativa en español", () => {
    expect(actionLabels.finalize).toBe("Finalizar revisión");
    expect(actionLabels.notify).toBe("Enviar correo");
    expect(actionLabels.back_to_dashboard).toBe("Volver al panel");
    expect(actionLabels.merge).toBe("Generar PDF consolidado");
    expect(actionLabels.amortization).toBe("Procesar amortización");
    expect(actionLabels.regenerate).toBe("Regenerar archivo de revisión");
    expect(actionLabels.resume).toBe("Retomar proceso");
    expect(actionLabels.view_detail).toBe("Ver detalle");
    expect(actionLabels.open_bank_template).toBe("Abrir archivo del banco");
    expect(actionLabels.open_review_excel).toBe("Abrir archivo de revisión");
    expect(actionLabels.continue_process).toBe("Continuar proceso");
    expect(actionLabels.retry_read).toBe("Volver a intentar");
    expect(actionLabels.refresh_documents).toBe("Actualizar documentos");
    expect(actionLabels.refresh_documents_hint).toMatch(/SharePoint/);
    expect(actionLabels.cancel_lote).toBe("Cancelar proceso");
    expect(actionLabels.soft_close).toBe("Cerrar sin amortizar");
    expect(confirmTitles.regenerate).toMatch(/Regenerar/);
    expect(confirmTitles.cancel_lote).toBe("Cancelar proceso");
    expect(confirmTitles.soft_close).toBe("Cerrar sin amortizar");
    expect(actionExplanations.soft_close).toMatch(/Procesados/i);
    expect(actionExplanations.soft_close).toMatch(/ASIENTOS/i);
    expect(actionExplanations.soft_close).not.toMatch(/\bprocessed\b/i);
    expect(jobSuccessCopy.soft_close.message).toMatch(/Procesados/i);
    expect(actionExplanations.regenerate.length).toBeLessThan(140);
    expect(actionExplanations.regenerate).toMatch(/Excel nuevo|misma fecha|banco actual/i);
    expect(jobSuccessCopy.amortization.title).toBe("Proceso completado");
    expect(jobSuccessCopy.amortization.message).toMatch(/finalizado/i);
    expect(jobSuccessCopy.finalize.title).toMatch(/Revisión finalizada/i);
    expect(jobSuccessCopy.finalize.message).toMatch(/histórico|asientos/i);
    expect(jobSuccessCopy.generate.title).toMatch(/revisión listo/i);
    expect(jobSuccessCopy.regenerate.title).toMatch(/regenerado/i);
    expect(jobSuccessCopy.regenerate.message).toBe(
      "Se generó un archivo de revisión nuevo.",
    );
    expect(jobSuccessCopy.notify.title).toMatch(/Correo enviado/i);
    expect(jobSuccessCopy.notify.message).toMatch(/PDF del correo|asientos/i);
    expect(jobSuccessCopy.merge.title).toMatch(/PDF consolidado/i);
    expect(jobSuccessCopy.merge.message).toMatch(/amortizaci/i);
  });
});
