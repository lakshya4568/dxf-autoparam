import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The workspace is served by the Python server under /app/ (the engine stays the authority: geometry, formulas and
// regeneration live there; this app draws, selects and asks). `bun run dev` proxies /api to a running `dxf-autoparam serve`.
export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/dxf_autoparam/static/app", emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
