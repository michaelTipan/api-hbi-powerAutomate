import { test as base, expect } from "@playwright/test";
import { installAndLogin, installUiApiMocks, type MockApiOptions } from "./apiMocks";

type OperatorFixtures = {
  mockApi: MockApiOptions;
  authenticatedPage: void;
};

export const test = base.extend<OperatorFixtures>({
  mockApi: [{}, { option: true }],
  authenticatedPage: [
    async ({ page, mockApi }, use) => {
      await installAndLogin(page, mockApi);
      await use();
    },
    { auto: true },
  ],
});

export { expect, installUiApiMocks, installAndLogin };
