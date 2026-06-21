import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  // browser conditions are only needed under Vitest (so @testing-library/svelte
  // imports the browser build of Svelte 5); keep them out of dev/prod builds.
  resolve: process.env.VITEST ? { conditions: ["browser"] } : {},
  plugins: [sveltekit()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, "")
      }
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest-setup.ts"],
    conditions: ["browser"]
  }
});
