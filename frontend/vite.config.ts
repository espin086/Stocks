import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

// Built assets land inside the Python package so the wheel ships them and
// `pip install sobres[web]` needs no Node toolchain.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../src/sobres/api/static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Charts and animation are code-split so the initial bundle stays under budget.
        manualChunks: {
          echarts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
          motion: ["motion/react"],
        },
      },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8787" } },
});
