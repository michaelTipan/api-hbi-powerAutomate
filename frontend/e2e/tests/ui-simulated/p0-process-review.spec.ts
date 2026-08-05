import { test, expect } from "../../fixtures/test";
import { reviewProcessKey } from "../../mocks/fixtures";
import { ProcessDetailPageObject } from "../../pages/operatorPages";

/** P0-05: detalle en fase revisión muestra checklist y acción finalizar. */
test.describe("P0 proceso revisión", () => {
  test("muestra fase revisión y botón Finalizar revisión", async ({ page }) => {
    const detail = new ProcessDetailPageObject(page);
    await detail.goto(reviewProcessKey, "phase=review");
    await expect(page.locator("#current-phase-title")).toHaveText("Revisión de archivo");
    await expect(detail.actionButton("Finalizar revisión")).toBeVisible();
  });
});
