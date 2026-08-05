import { test, expect } from "../../fixtures/test";
import { HistoryPageObject } from "../../pages/operatorPages";

/** P0-10: historial lista ítems archivados mockeados. */
test.describe("P0 historial", () => {
  test("muestra tabla con proceso archivado", async ({ page }) => {
    const history = new HistoryPageObject(page);
    await history.goto();
    await expect(history.title()).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Archivo" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Bancolombia" })).toBeVisible();
  });
});
