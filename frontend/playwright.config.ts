import { defineConfig, devices } from "@playwright/test";

const previewPort = 4173;
const previewHost = "127.0.0.1";
const previewBase = `http://${previewHost}:${previewPort}/app/`;

export default defineConfig({
  testDir: "./e2e/tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "./e2e/test-results",
  use: {
    baseURL: previewBase,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `npm run preview -- --port ${previewPort} --strictPort --host ${previewHost}`,
    url: previewBase,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
