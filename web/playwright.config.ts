import { defineConfig, devices } from "@playwright/test";

/** e2e runs against the static demo build (vite preview), exactly what GitHub Pages serves.
 *  Needs the frozen replay first: from engine/, `python -m controlroom.export ../web/.static/api`. */
const BASE = "http://localhost:4174/control-room/";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: BASE, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, hasTouch: true }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: {
    command: "npm run build:static && npx vite preview --mode static --port 4174 --strictPort",
    url: BASE,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
