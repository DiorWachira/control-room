// Live board screenshots (status in light, dark and 375 px) for review and docs/design/.
import { chromium } from "@playwright/test";
const out = process.argv[2] ?? "shots";
const BASE = process.env.BASE ?? "http://localhost:4174/control-room/";
const b = await chromium.launch();
for (const [name, w, h, lights, full] of [["13-status-live-light", 1440, 900, "up", true], ["14-status-live-dark", 1440, 900, "down", false], ["15-status-live-mobile", 375, 812, "up", false]]) {
  const ctx = await b.newContext({ viewport: { width: w, height: h } });
  const p = await ctx.newPage();
  await p.addInitScript((l) => { localStorage.setItem("cr.lights", l); localStorage.setItem("cr.guide.seen", "1"); }, lights);
  await p.goto(BASE);
  await p.waitForTimeout(1200);
  await p.screenshot({ path: `${out}/${name}.png`, fullPage: full });
  await ctx.close();
}
await b.close();
console.log("saved to", out);
