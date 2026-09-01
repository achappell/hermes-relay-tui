import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  build: {
    outDir: "../static",
    emptyOutDir: true,
    minify: false,
  },
  test: {
    environment: "jsdom",
  },
});
