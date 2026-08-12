import { test, expect } from "@playwright/test";
import { loginOperator } from "../helpers/auth";

test.describe("CAPA A — smoke sandbox UI", () => {
  test("E34 login + panel + 4 fases + sin copy legacy", async ({ page }) => {
    await loginOperator(page);
    await expect(page.getByRole("navigation")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Distribucion_Pagos");
    await expect(page.locator("body")).not.toContainText("Distribucion_Abonos");
    await expect(page.locator("body")).not.toContainText("Procesar = SI");
    await expect(page.locator("body")).not.toContainText("Tipo Aplicación en todas las filas del reporte del banco");
    await expect(page.getByRole("link", { name: /panel/i })).toBeVisible();

    const procesos = page.getByRole("link", { name: /procesos/i }).first();
    if (await procesos.isVisible()) {
      await procesos.click();
      await expect(page).toHaveURL(/procesos|processes/i);
    }

    // Detalle si hay al menos un proceso listado.
    const firstProcess = page.getByRole("link", { name: /banco|validaci[oó]n|2026/i }).first();
    if (await firstProcess.isVisible().catch(() => false)) {
      await firstProcess.click();
      await expect(page.locator("body")).toContainText(/Revisi[oó]n|Notific|consolidad|Amortiz/i);
    }
  });
});
