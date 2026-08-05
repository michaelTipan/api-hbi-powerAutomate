import { test, expect } from "../../fixtures/test";
import { reviewProcessKey } from "../../mocks/fixtures";
import { DashboardPageObject } from "../../pages/operatorPages";

/** P0-03: panel lista procesos activos mockeados. */
test.describe("P0 dashboard lista procesos", () => {
  test("muestra tarjetas de procesos activos", async ({ page }) => {
    const dashboard = new DashboardPageObject(page);
    await dashboard.goto();
    await expect(dashboard.title()).toBeVisible();
    await expect(page.getByRole("article").filter({ hasText: "Bancolombia" })).toHaveCount(2);
    await expect(page.getByRole("article").filter({ hasText: "Bogotá" })).toHaveCount(2);
    await expect(page.getByRole("heading", { name: "Procesos activos" })).toBeVisible();
  });

  test("navega al detalle desde tarjeta", async ({ page }) => {
    const dashboard = new DashboardPageObject(page);
    await dashboard.goto();
    await page
      .getByRole("link", { name: /Continuar proceso — Bancolombia/i })
      .first()
      .click();
    await expect(page).toHaveURL(/e2e-review/);
    await expect(page.locator("#current-phase-title")).toHaveText("Revisión de archivo");
  });
});
