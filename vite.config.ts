import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  root: "frontend",
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 1420,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
