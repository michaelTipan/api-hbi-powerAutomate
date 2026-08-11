import { test, expect } from "@playwright/test";
import { loginOperator } from "../helpers/auth";

test.describe("CAPA A — smoke sandbox UI", () => {
  test("E34-ish login + panel sin copy legacy Distribucion_Pagos", async ({ page }) => {
    await loginOperator(page);
    await expect(page.locator("body")).not.toContainText("Distribucion_Pagos");
    await expect(page.locator("body")).not.toContainText("Procesar = SI");
    // Shell operativo visible
    await expect(page.getByText(/sandbox|pruebas|producción|produccion/i).first()).toBeVisible();
  });
});
