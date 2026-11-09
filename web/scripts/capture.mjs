// Screenshots of the guide bubble and every screen, for review and docs/design/.
//   npm run build:static && npx vite preview --mode static --port 4174
//   node scripts/capture.mjs ../docs/design
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const out = process.argv[2] ?? "shots";
const BASE = process.env.BASE ?? "http://localhost:4174/control-room/";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();

async function page(w, h, lights, guide = "off") {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: "no-preference" });
  const p = await ctx.newPage();
  await p.addInitScript(([l, g]) => {
    localStorage.setItem("cr.lights", l);
    if (g === "off") localStorage.setItem("cr.guide.seen", "1");
  }, [lights, guide]);
  return p;
}

async function tourShot(name, w, h, lights, step) {
  const p = await page(w, h, lights, "on");
  await p.goto(BASE);
  await p.getByTestId("guide-invite").getByRole("button", { name: "Start" }).click();
  for (let i = 1; i < step; i++) { await p.keyboard.press("ArrowRight"); await p.waitForTimeout(150); }
  await p.waitForTimeout(1600);
  await p.screenshot({ path: `${out}/${name}.png` });
  await p.context().close();
}

const shots = (process.env.SHOTS ?? "tour,invite").split(",");
if (shots.includes("tour")) {
  await tourShot("10-guide-bubble-light", 1440, 900, "up", 3);
  await tourShot("11-guide-bubble-dark", 1440, 900, "down", 9);
  await tourShot("12-guide-bubble-mobile", 375, 812, "up", 6);
}
if (shots.includes("invite")) {
  const p = await page(1440, 900, "up", "on");
  await p.goto(BASE);
  await p.waitForTimeout(1200);
  await p.screenshot({ path: `${out}/09-guide-invite.png` });
  await p.context().close();
}
await browser.close();
console.log("saved to", out);
