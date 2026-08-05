import { test, expect } from "../../fixtures/test";
import { notifyProcessKey } from "../../mocks/fixtures";
import { ProcessDetailPageObject } from "../../pages/operatorPages";

/** P0-07: fase notify envía correo con confirmación. */
test.describe("P0 proceso notify", () => {
  test("confirma Enviar correo y acepta job notify", async ({ page }) => {
    const detail = new ProcessDetailPageObject(page);
    await detail.goto(notifyProcessKey, "phase=notify");
    await expect(page.locator("#current-phase-title")).toHaveText("Enviar correo");
    await detail.actionButton("Enviar correo").click();
    const notifyRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().includes("/api/ui/v1/processes/notify"),
    );
    await detail
      .confirmDialog("Enviar correo")
      .getByRole("button", { name: "Confirmar envío" })
      .click();
    await notifyRequest;
  });
});
