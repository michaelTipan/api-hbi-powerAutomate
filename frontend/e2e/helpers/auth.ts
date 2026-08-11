import { expect, type Page } from "@playwright/test";

export async function loginOperator(page: Page): Promise<void> {
  const user = process.env.E2E_USER || "operador_hbi";
  const password = process.env.E2E_PASSWORD;
  if (!password) {
    throw new Error("E2E_PASSWORD missing (frontend/e2e/.env.local)");
  }
  await page.goto("/app/");
  await page.locator("#login-username, input[name='username']").first().fill(user);
  await page.locator("#login-password, input[name='password'][type='password']").first().fill(password);
  await page.getByRole("button", { name: /iniciar|entrar|login/i }).click();
  await expect(page.getByRole("navigation")).toBeVisible({ timeout: 60_000 });
}
