import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
  },
  webServer: {
    command: "pnpm dev --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173/sessions/11111111-1111-4111-8111-111111111111",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      TUTOR_API_MODE: "fixture",
    },
  },
});
