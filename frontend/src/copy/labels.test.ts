import { describe, expect, it } from "vitest";
import {
  actionLabels,
  confirmTitles,
  operationalStatusLabel,
  stageLabel,
  statusLabel,
} from "./labels";

describe("catálogo de textos operativos (labels)", () => {
  it("traduce etapas técnicas / tipos de job a lenguaje operativo", () => {
    expect(stageLabel("generate")).toBe("Preparación de la revisión");
    expect(stageLabel("finalize")).toBe("Cierre de la revisión");
    expect(stageLabel("notify_validar_extractos")).toBe("Envío de la validación");
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
    expect(operationalStatusLabel("ESPERANDO_SOPORTES")).toBe("Esperando documentos contables");
    expect(operationalStatusLabel("PENDIENTE_ASIENTOS")).toBe("Esperando documentos contables");
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

  it("los títulos de confirmación no usan jerga técnica en inglés", () => {
    for (const title of Object.values(confirmTitles)) {
      expect(title).not.toMatch(/Generate|Finalize|Notify|Merge/i);
    }
  });

  it("las acciones tienen una etiqueta operativa en español", () => {
    expect(actionLabels.finalize).toBe("Finalizar revisión");
    expect(actionLabels.notify).toBe("Enviar validación");
    expect(actionLabels.merge).toBe("Generar PDF consolidado");
    expect(actionLabels.amortization).toBe("Procesar amortización");
    expect(actionLabels.resume).toBe("Retomar proceso");
    expect(actionLabels.retry_read).toBe("Volver a intentar");
    expect(actionLabels.refresh_documents).toBe("Actualizar documentos");
  });
});
