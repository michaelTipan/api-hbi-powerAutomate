import { describe, expect, it } from "vitest";
import { recoveryKindForError } from "../components/BusinessErrorsPanel";
import type { UiError } from "../types/contract";

function err(partial: Partial<UiError>): UiError {
  return {
    error_code: null,
    stage: null,
    severity: "business",
    user_message: "",
    next_action: null,
    payment_id: null,
    client_name: null,
    credit: null,
    link: null,
    ...partial,
  };
}

describe("recoveryKindForError", () => {
  it("sugiere regenerar ante hoja Errores / review_has_open_errors", () => {
    expect(
      recoveryKindForError(err({ error_code: "review_has_open_errors" })),
    ).toBe("regenerate");
  });

  it("sugiere merge ante asientos incompletos", () => {
    expect(
      recoveryKindForError(
        err({
          error_code: "merge_readiness_incomplete",
          user_message: "Falta un asiento en la carpeta",
        }),
      ),
    ).toBe("merge");
  });

  it("sugiere abrir excel ante Procesar≠SI o montos faltantes", () => {
    expect(
      recoveryKindForError(err({ error_code: "process_not_approved" })),
    ).toBe("open_excel");
    expect(
      recoveryKindForError(err({ error_code: "missing_mora_a_aplicar" })),
    ).toBe("open_excel");
  });

  it("sugiere reintentar ante Excel bloqueado", () => {
    expect(
      recoveryKindForError(err({ error_code: "sharepoint_file_locked" })),
    ).toBe("retry");
  });
});
