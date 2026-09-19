import { defineConfig } from "@playwright/test";

// Port 3100 (not 3000) so a running `next dev` doesn't get tested by mistake.
const LOCAL_PORT = 3100;
const baseURL = process.env.BASE_URL || `http://localhost:${LOCAL_PORT}`;
const usingExternalTarget = Boolean(process.env.BASE_URL);

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  use: {
    baseURL,
    extraHTTPHeaders: {
      "user-agent": "confessio-seo-tests/1.0",
    },
  },
  webServer: usingExternalTarget
    ? undefined
    : {
        command: `pnpm next start -p ${LOCAL_PORT}`,
        url: baseURL,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
      },
});
