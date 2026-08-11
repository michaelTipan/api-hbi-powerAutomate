import { expect, type Page } from "@playwright/test";

export async function loginOperator(page: Page): Promise<void> {
  const user = process.env.E2E_USER || "operador_hbi";
  const password = process.env.E2E_PASSWORD;
  if (!password) {
    throw new Error("E2E_PASSWORD missing (frontend/e2e/.env.local)");
  }
  await page.goto("/app/");
  await page.getByLabel(/usuario|user/i).fill(user);
  await page.getByLabel(/contraseña|password/i).fill(password);
  await page.getByRole("button", { name: /iniciar|entrar|login/i }).click();
  await expect(page.getByRole("navigation").or(page.getByText(/panel|procesos|banco/i).first())).toBeVisible({
    timeout: 60_000,
  });
}
