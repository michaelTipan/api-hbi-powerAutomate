import { test, expect } from "@playwright/test";
import { loginOperator } from "../helpers/auth";

const PANEL_CACHE_KEY = "ui-read-cache:panel";
const detailCacheKey = (processKey: string) => `ui-read-cache:detail:${processKey}`;

function processKeyFromUrl(url: string): string {
  const path = new URL(url).pathname;
  const raw = path.split("/processes/")[1] ?? "";
  return decodeURIComponent(raw.split("/")[0] ?? "").trim();
}

test.describe("Read cache — panel y detalle", () => {
  test("panel reopen: cache pinta y luego revalida dashboard", async ({ page }) => {
    await loginOperator(page);
    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible({ timeout: 60_000 });

    await expect
      .poll(async () =>
        page.evaluate((key) => sessionStorage.getItem(key) !== null, PANEL_CACHE_KEY),
      )
      .toBe(true);

    let dashboardFetches = 0;
    await page.route("**/api/ui/v1/dashboard", async (route) => {
      dashboardFetches += 1;
      await route.continue();
    });

    await page.goto("/app/login");
    await page.goto("/app/");

    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(async () => dashboardFetches, { timeout: 15_000 })
      .toBeGreaterThan(0);
  });

  test("process detail reopen: cache pinta y luego revalida GET proceso", async ({ page }) => {
    await loginOperator(page);
    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible({ timeout: 60_000 });

    const processLink = page
      .getByRole("link", { name: /continuar|ver detalle/i })
      .first();
    const hasProcess = await processLink.isVisible().catch(() => false);
    test.skip(!hasProcess, "No hay procesos listados en sandbox para abrir detalle");

    await processLink.click();
    await page.waitForURL(/\/processes\//, { timeout: 60_000 });
    const processKey = processKeyFromUrl(page.url());
    expect(processKey.length).toBeGreaterThan(0);

    await expect
      .poll(async () =>
        page.evaluate(
          (detailKey) => sessionStorage.getItem(detailKey) !== null,
          detailCacheKey(processKey),
        ),
      )
      .toBe(true);

    let processFetches = 0;
    const encodedKey = encodeURIComponent(processKey);
    await page.route(`**/api/ui/v1/processes/${encodedKey}`, async (route) => {
      if (route.request().method() === "GET") {
        processFetches += 1;
      }
      await route.continue();
    });

    await page.goto("/app/");
    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible({ timeout: 30_000 });
    await page.goto(`/app/processes/${encodedKey}`);

    await expect(page.getByRole("navigation", { name: "Progreso del proceso" })).toBeVisible({
      timeout: 30_000,
    });
    await expect.poll(async () => processFetches, { timeout: 15_000 }).toBeGreaterThan(0);
  });

  test("POST invalidation: tras aceptar mutación se limpia sessionStorage cache", async ({
    page,
  }) => {
    await loginOperator(page);
    await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible({ timeout: 60_000 });

    const processLink = page
      .getByRole("link", { name: /continuar|ver detalle/i })
      .first();
    const hasProcess = await processLink.isVisible().catch(() => false);
    test.skip(!hasProcess, "No hay procesos listados en sandbox para probar invalidación");

    await processLink.click();
    await page.waitForURL(/\/processes\//, { timeout: 60_000 });
    const processKey = processKeyFromUrl(page.url());
    const encodedKey = encodeURIComponent(processKey);

    await expect
      .poll(async () =>
        page.evaluate(
          ([panelKey, detailKey]) => ({
            panel: sessionStorage.getItem(panelKey) !== null,
            detail: sessionStorage.getItem(detailKey) !== null,
          }),
          [PANEL_CACHE_KEY, detailCacheKey(processKey)] as const,
        ),
      )
      .toEqual({ panel: true, detail: true });

    const finalizeBtn = page.getByRole("button", { name: /finalizar revisión/i });
    const canFinalize =
      (await finalizeBtn.isVisible().catch(() => false)) &&
      !(await finalizeBtn.isDisabled().catch(() => true));
    test.skip(!canFinalize, "Finalize no disponible en este proceso sandbox");

    await page.route(`**/api/ui/v1/processes/${encodedKey}/finalize`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ job_id: "e2e-cache-invalidate", status: "queued" }),
        });
        return;
      }
      await route.continue();
    });

    await finalizeBtn.click();
    const confirmBtn = page.getByRole("button", { name: /confirmar finalización/i });
    await expect(confirmBtn).toBeVisible({ timeout: 10_000 });
    await confirmBtn.click();

    await expect
      .poll(async () =>
        page.evaluate(
          ([panelKey, detailKey]) => ({
            panel: sessionStorage.getItem(panelKey),
            detail: sessionStorage.getItem(detailKey),
          }),
          [PANEL_CACHE_KEY, detailCacheKey(processKey)] as const,
        ),
        { timeout: 15_000 },
      )
      .toEqual({ panel: null, detail: null });
  });
});
