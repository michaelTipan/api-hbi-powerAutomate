import { test, expect } from "../../fixtures/test";
import { amortRecoveryProcessKey } from "../../mocks/fixtures";
import { ProcessDetailPageObject } from "../../pages/operatorPages";

/** P0-09: recovery amortización — banner formato + modal issues persistidos. */
test.describe("P0 amort recovery", () => {
  test("muestra banner de formato y abre problemas de amortización", async ({ page }) => {
    const detail = new ProcessDetailPageObject(page);
    await detail.goto(amortRecoveryProcessKey, "phase=amortization");
    await expect(page.locator("#current-phase-title")).toHaveText("Procesar amortización");
    await expect(
      page.getByRole("button", { name: "Ver problemas de amortización" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Ir a reconsolidar (fase 4)" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Ver problemas de amortización" }).click();
    await expect(page.getByText(/Formato de asiento incorrecto/)).toBeVisible();
    await expect(page.getByText(/12345/)).toBeVisible();
  });
});
