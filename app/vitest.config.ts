import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    // `**` skips dot-directories, so `.server/` is listed on its own.
    include: ["app/**/*.test.{ts,tsx}", "app/.server/**/*.test.{ts,tsx}"],
  },
});
