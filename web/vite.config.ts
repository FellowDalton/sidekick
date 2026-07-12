import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";
import { SvelteKitPWA } from "@vite-pwa/sveltekit";

export default defineConfig({
  // browser conditions are only needed under Vitest (so @testing-library/svelte
  // imports the browser build of Svelte 5); keep them out of dev/prod builds.
  resolve: process.env.VITEST ? { conditions: ["browser"] } : {},
  plugins: [
    sveltekit(),
    SvelteKitPWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Sidekick",
        short_name: "Sidekick",
        description: "Your ADHD execution sidekick",
        theme_color: "#15171F",
        background_color: "#15171F",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      },
      workbox: {
        // static/push-sw.js carries the push + notificationclick handlers; importScripts
        // keeps us in generateSW mode (precache + NetworkFirst config stay generated).
        importScripts: ["push-sw.js"],
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
        runtimeCaching: [
          {
            urlPattern: ({ url }: { url: URL }) => url.pathname === "/api/feed",
            handler: "NetworkFirst",
            options: { cacheName: "sidekick-feed", expiration: { maxEntries: 1 } }
          }
        ]
      }
    })
  ],
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
    conditions: ["browser"],
    // only unit/component tests under src/ — keep Vitest from collecting the
    // Playwright e2e specs in e2e/ (which would error under Vitest's runner).
    include: ["src/**/*.{test,spec}.{js,ts}"]
  }
});
