import { test, expect } from "../../fixtures/test";
import { DashboardPageObject } from "../../pages/operatorPages";

/** P0-11: navegación sidebar Panel ↔ Historial. */
test.describe("P0 navegación", () => {
  test("alterna Panel e Historial por sidebar", async ({ page }) => {
    const dashboard = new DashboardPageObject(page);
    await dashboard.goto();
    await expect(dashboard.title()).toBeVisible();
    await dashboard.sidebarLink("Historial").click();
    await expect(page.getByRole("heading", { name: "Historial" })).toBeVisible();
    await dashboard.sidebarLink("Panel").click();
    await expect(dashboard.title()).toBeVisible();
  });
});
