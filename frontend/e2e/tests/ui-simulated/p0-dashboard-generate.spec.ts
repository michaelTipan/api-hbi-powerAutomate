import { test, expect } from "../../fixtures/test";
import { DashboardPageObject } from "../../pages/operatorPages";

/** P0-04: flujo generate con confirmación y panel de job. */
test.describe("P0 dashboard generate", () => {
  test("confirma Iniciar validación y muestra seguimiento", async ({ page }) => {
    const dashboard = new DashboardPageObject(page);
    await dashboard.goto();
    await dashboard.bankSelect().selectOption("banco_bogota");
    await dashboard.generateButton().click();
    await expect(page.getByRole("dialog")).toContainText("Iniciar validación");
    const generateRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().includes("/api/ui/v1/processes/generate"),
    );
    await page.getByRole("button", { name: "Confirmar" }).click();
    await generateRequest;
    await expect(page.getByText(/Seguimiento —/)).toBeVisible({ timeout: 10000 });
  });
});
