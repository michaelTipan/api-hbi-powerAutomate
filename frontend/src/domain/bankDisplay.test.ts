import { describe, expect, it } from "vitest";
import { bankDisplayName, normalizeBankDisplayName } from "./bankDisplay";

describe("bankDisplayName", () => {
  it("muestra Bogotá sin prefijo Banco (select del Panel)", () => {
    expect(bankDisplayName("banco_bogota")).toBe("Bogotá");
    expect(bankDisplayName("banco_bogota", "Banco Bogotá")).toBe("Bogotá");
    expect(bankDisplayName("banco_bogota", "Banco de Bogotá")).toBe("Bogotá");
  });

  it("deja Bancolombia sin cambios", () => {
    expect(bankDisplayName("banco_bancolombia")).toBe("Bancolombia");
    expect(bankDisplayName("banco_bancolombia", "Bancolombia")).toBe("Bancolombia");
  });

  it("normaliza nombres crudos de Bogotá y conserva el resto", () => {
    expect(normalizeBankDisplayName("Banco Bogotá")).toBe("Bogotá");
    expect(normalizeBankDisplayName("Banco de Bogotá")).toBe("Bogotá");
    expect(normalizeBankDisplayName("Bancolombia")).toBe("Bancolombia");
    expect(normalizeBankDisplayName("Otro Banco")).toBe("Otro Banco");
  });
});
