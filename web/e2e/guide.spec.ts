import { expect, test } from "@playwright/test";
import { STEPS } from "../src/guideSteps";
import { bubbleGeometry } from "./helpers";

test("first visit: invite, bubble tour across all screens, Esc, never offered again", async ({ page }) => {
  await page.goto("./");
  const invite = page.getByTestId("guide-invite");
  await expect(invite).toBeVisible();
  await expect(invite).toContainText(`${STEPS.length}-step`);
  await invite.getByRole("button", { name: "Start" }).click();

  const bubble = page.getByTestId("guide-bubble");
  for (let i = 0; i < STEPS.length; i++) {
    const s = STEPS[i];
    await expect(bubble.getByText(`Check ${i + 1} / ${STEPS.length}`)).toBeVisible();
    await expect(bubble.getByRole("heading", { name: s.title })).toBeVisible();
    if (s.hash && s.hash !== "#/") expect(page.url()).toContain(s.hash);
    await expect(page.locator(`[data-guide="${s.target}"]`).first()).toBeVisible();
    await expect(page.locator(".veil-ring")).toBeVisible();
    await page.waitForTimeout(500); // let the smooth scroll settle so geometry is final
    const g = await bubbleGeometry(page, s.target);
    expect(g.b.l).toBeGreaterThanOrEqual(0);
    expect(g.b.r).toBeLessThanOrEqual(g.vw);
    expect(g.b.btm).toBeLessThanOrEqual(g.vh + 1);
    if (g.side !== "side-inside") expect(g.overlap, `step ${i + 1} (${s.target}) bubble covers its panel`).toBe(0);
    await expect(bubble.locator(".gcaret")).toHaveCount(["side-below", "side-above", "side-right", "side-left"].includes(g.side ?? "") ? 1 : 0);
    if (i === STEPS.length - 1) break;
    // Keyboard and button both advance; alternate them.
    if (i % 2) await page.keyboard.press("ArrowRight");
    else await bubble.getByRole("button", { name: "Next" }).click();
  }
  await expect(bubble.getByRole("button", { name: "Finish" })).toBeVisible();
  // Back with the left arrow, then Esc closes.
  await page.keyboard.press("ArrowLeft");
  await expect(bubble.getByText(`Check ${STEPS.length - 1} / ${STEPS.length}`)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(bubble).toHaveCount(0);

  await page.goto("./#/");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("guide-invite")).toHaveCount(0);
});

test("focus is trapped in the bubble and the spotlit panel stays clickable", async ({ page }) => {
  await page.goto("./");
  await page.getByTestId("guide-invite").getByRole("button", { name: "Start" }).click();
  const bubble = page.getByTestId("guide-bubble");
  await expect(bubble.getByRole("button", { name: "Next" })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest('[data-testid="guide-bubble"]'))).toBe(true);
  // Step 1 spotlights the nav: a link under the spotlight still works.
  await page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: "Budgets" }).click();
  expect(page.url()).toContain("#/budgets");
});

test("Not now dismisses the invite for good", async ({ page }) => {
  await page.goto("./");
  await page.getByTestId("guide-invite").getByRole("button", { name: "Not now" }).click();
  await expect(page.getByTestId("guide-invite")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("guide-invite")).toHaveCount(0);
});
