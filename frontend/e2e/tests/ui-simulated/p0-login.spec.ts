import { test, expect } from "@playwright/test";
import { installUiApiMocks } from "../../fixtures/apiMocks";
import { E2E_PASSWORD, E2E_USERNAME } from "../../mocks/fixtures";
import { LoginPageObject } from "../../pages/operatorPages";

/** P0-01: login local_session rechaza credenciales inválidas y acepta operador. */
test.describe("P0 login local_session", () => {
  test("muestra error con credenciales inválidas", async ({ page }) => {
    await installUiApiMocks(page);
    const login = new LoginPageObject(page);
    await login.goto();
    await expect(login.heading()).toBeVisible();
    await login.login("mal.usuario", "mala-clave");
    await expect(login.errorMessage()).toContainText("Credenciales");
  });

  test("entra al panel con credenciales válidas", async ({ page }) => {
    await installUiApiMocks(page);
    const login = new LoginPageObject(page);
    await login.goto();
    await login.login(E2E_USERNAME, E2E_PASSWORD);
    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible();
  });
});
