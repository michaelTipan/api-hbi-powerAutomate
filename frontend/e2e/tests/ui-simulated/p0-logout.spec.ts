import { test, expect } from "../../fixtures/test";

/** P0-12: logout local_session vuelve a pantalla de login. */
test.describe("P0 logout", () => {
  test("cierra sesión y muestra Acceso operativo", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Cerrar sesión" }).click();
    await expect(page.getByRole("heading", { name: "Acceso operativo" })).toBeVisible();
  });
});
