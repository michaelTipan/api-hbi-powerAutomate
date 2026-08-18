import { describe, expect, it } from "vitest";
import { formatOperatorDateTime } from "./operatorDateTime";

describe("formatOperatorDateTime", () => {
  it("convierte Graph UTC a hora Colombia", () => {
    expect(formatOperatorDateTime("2026-08-18T17:52:00Z")).toBe(
      "18 ago 2026, 12:52 p. m.",
    );
  });

  it("deja un texto ya formateado", () => {
    expect(formatOperatorDateTime("18 ago 2026, 12:52 p. m.")).toBe(
      "18 ago 2026, 12:52 p. m.",
    );
  });

  it("vacío queda vacío", () => {
    expect(formatOperatorDateTime(null)).toBe("");
    expect(formatOperatorDateTime("")).toBe("");
  });
});
