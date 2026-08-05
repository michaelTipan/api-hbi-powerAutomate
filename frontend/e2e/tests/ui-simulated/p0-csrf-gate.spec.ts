import { test, expect } from "@playwright/test";
import { installAndLogin } from "../../fixtures/apiMocks";
import { E2E_CSRF } from "../../mocks/fixtures";

/** P0-02: mutaciones POST exigen header CSRF tras sesión local. */
test.describe("P0 gate CSRF", () => {
  test("POST generate incluye X-CSRF-Token", async ({ page }) => {
    await installAndLogin(page);
    await page.locator("#new-process-bank").selectOption("banco_bogota");
    await page.getByRole("button", { name: "Iniciar validación" }).click();
    const generateRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().includes("/api/ui/v1/processes/generate"),
    );
    await page.getByRole("button", { name: "Confirmar" }).click();
    const req = await generateRequest;
    expect(req.headers()["x-csrf-token"]).toBe(E2E_CSRF);
  });
});
