import { test, expect } from "../../fixtures/test";
import { mergeProcessKey } from "../../mocks/fixtures";
import { ProcessDetailPageObject } from "../../pages/operatorPages";

/** P0-08: fase merge consolida PDF cuando readiness=ready. */
test.describe("P0 proceso merge", () => {
  test("confirma Generar PDF consolidado", async ({ page }) => {
    const detail = new ProcessDetailPageObject(page);
    await detail.goto(mergeProcessKey, "phase=merge");
    await expect(page.locator("#current-phase-title")).toHaveText("Generar PDF consolidado");
    await expect(page.getByText(/Todos los soportes están listos/)).toBeVisible();
    await detail.actionButton("Generar PDF consolidado").click();
    const mergeRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().includes("/api/ui/v1/processes/merge"),
    );
    await detail
      .confirmDialog("Generar PDF consolidado")
      .getByRole("button", { name: "Generar PDF consolidado" })
      .click();
    await mergeRequest;
  });
});
