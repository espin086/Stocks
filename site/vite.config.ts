import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

// A static build for GitHub Pages under /sobres/. Animation and charting are
// dynamic imports, so the initial bundle is the page's own script only.
export default defineConfig({
  base: "/sobres/",
  plugins: [tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
          motion: ["gsap", "gsap/ScrollTrigger", "lenis"],
        },
      },
    },
  },
});
