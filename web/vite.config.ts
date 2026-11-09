import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const engine = process.env.CONTROLROOM_ENGINE ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": engine, "/budget": engine },
  },
});
