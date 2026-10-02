import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "styles.css"), "utf8").replace(/\r\n/g, "\n");

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match?.[2] ?? "";
}

describe("estilos de enlaces en tarjetas", () => {
  it("«Revisar» y demás decision-link usan azul de marca (contraste sobre blanco), no el amarillo", () => {
    const body = rule(".decision-link");
    expect(body).toContain("color: var(--brand-blue-secondary)");
    expect(body).not.toContain("--accent");
  });

  it("card-link se ve como enlace: azul, subrayado y foco por subrayado más grueso", () => {
    expect(rule("a.card-link")).toContain("color: var(--brand-blue-secondary)");
    expect(rule("a.card-link")).toContain("text-decoration: underline");
    expect(rule("a.card-link:hover")).toContain("var(--brand-blue-secondary-hover)");
    expect(rule("a.card-link:focus-visible")).toContain("text-decoration-thickness: 2px");
  });

  it("no reactiva anillos de foco globales", () => {
    expect(rule(":focus-visible")).toContain("outline: none");
    expect(rule("a.card-link:focus-visible")).not.toContain("outline:");
  });
});
