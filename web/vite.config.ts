import { existsSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const engine = process.env.CONTROLROOM_ENGINE ?? "http://127.0.0.1:8000";

// `--mode static` builds the public demo for GitHub Pages: no engine, the frozen replay is
// copied from .static/ (written by `python -m controlroom.export web/.static/api`).
export default defineConfig(({ mode }) => {
  const isStatic = mode === "static";
  if (isStatic && !existsSync(".static/api/status.json")) {
    throw new Error("No frozen replay. Run from engine/: python -m controlroom.export ../web/.static/api");
  }
  return {
    plugins: [react()],
    base: isStatic ? (process.env.VITE_BASE ?? "/control-room/") : "/",
    publicDir: isStatic ? ".static" : "public",
    server: {
      port: 5173,
      proxy: { "/api": engine, "/budget": engine },
    },
  };
});
