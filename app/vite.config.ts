import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), reactRouter()],
  // The dependency scan misses these: they are reached only through `~/`
  // component imports. Discovered on first request instead, they make Vite
  // re-optimise and reload every open page, which destroys the execution
  // context an axe scan is running in (tests/e2e/accessibility.spec.ts).
  optimizeDeps: {
    include: ["class-variance-authority", "cn", "lucide-react", "radix-ui"],
  },
  resolve: {
    tsconfigPaths: true,
  },
});
