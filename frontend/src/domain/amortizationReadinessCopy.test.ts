import { describe, expect, it } from "vitest";
import {
  amortMissingItemMessage,
  amortWarningMessage,
  parseAmortMissingItems,
} from "./amortizationReadinessCopy";

describe("amortizationReadinessCopy", () => {
  it("humaniza faltantes por missing_creditos y códigos", () => {
    expect(
      amortMissingItemMessage({
        missing_creditos: ["265", "310"],
        error_code: null,
      }),
    ).toMatch(/crédito\(s\): 265, 310/);
    expect(
      amortMissingItemMessage({ error_code: "asiento_contable_not_found" }),
    ).toMatch(/documentos contables/i);
  });

  it("humaniza warnings técnicos del manifiesto", () => {
    expect(amortWarningMessage("manifest_status=partial")).toMatch(/manifiesto/i);
    expect(amortWarningMessage("manifest_status=complete")).toBeNull();
    expect(amortWarningMessage("eligible_for_dry_run=false")).toMatch(/incompleta/i);
  });

  it("parsea missing_items sin any", () => {
    const items = parseAmortMissingItems([
      { id_pago: "G1", missing_creditos: ["258"], error_code: "MERGE_GROUP_PENDING_INPUTS" },
    ]);
    expect(items[0]?.credito).toBe("258");
    expect(items[0]?.id_pago).toBe("G1");
  });
});
