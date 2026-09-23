import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from a project page at /longstop/, so asset and data URLs are built
// from BASE_URL rather than assumed to sit at the root. VITE_BASE lets a local
// preview or a different host override it.
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? "/longstop/",
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: true },
});
