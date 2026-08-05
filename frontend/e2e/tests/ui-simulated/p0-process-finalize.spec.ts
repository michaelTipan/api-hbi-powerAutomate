import { test, expect } from "../../fixtures/test";
import { reviewProcessKey } from "../../mocks/fixtures";
import { ProcessDetailPageObject } from "../../pages/operatorPages";

/** P0-06: modal finalize dispara POST /processes/finalize mockeado. */
test.describe("P0 proceso finalize", () => {
  test("confirma Finalizar revisión y acepta job", async ({ page }) => {
    const detail = new ProcessDetailPageObject(page);
    await detail.goto(reviewProcessKey, "phase=review");
    await detail.actionButton("Finalizar revisión").click();
    await expect(detail.confirmDialog("Finalizar revisión")).toBeVisible();
    const finalizeRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().includes("/api/ui/v1/processes/finalize"),
    );
    await detail
      .confirmDialog("Finalizar revisión")
      .getByRole("button", { name: "Confirmar finalización" })
      .click();
    await finalizeRequest;
    await expect(page.getByText(/Verificando revisión|En curso|Completado/)).toBeVisible({
      timeout: 15000,
    });
  });
});
