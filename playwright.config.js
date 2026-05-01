import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests-ui",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10_000,
  },
  webServer: {
    command: process.platform === "win32" ? "npm.cmd run dev" : "npm run dev",
    url: "http://127.0.0.1:1420",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        browserName: "chromium",
      },
    },
  ],
});
