import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "5173";
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: origin,
  },
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port}`,
    url: `${origin}/sessions/11111111-1111-4111-8111-111111111111`,
    reuseExistingServer:
      !process.env.CI && process.env.CAPTURE_EVIDENCE !== "1",
    timeout: 120_000,
    env: {
      TUTOR_API_MODE: "fixture",
      TUTOR_MODE: process.env.TUTOR_MODE ?? "prototype",
    },
  },
});
