import { expect, test } from "@playwright/test";

test("375 px: no horizontal overflow; the guide bubble docks to an edge", async ({ page }) => {
  await page.goto("./");
  for (const hash of ["#/", "#/budgets", "#/incidents/RSV-1042"]) {
    await page.goto("./" + hash);
    await page.waitForTimeout(800);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow on ${hash}`).toBe(true);
  }
  await page.goto("./#/");
  await page.getByTestId("guide-invite").getByRole("button", { name: "Start" }).click();
  const bubble = page.getByTestId("guide-bubble");
  await expect(bubble).toHaveClass(/side-dock/);
  const box = await bubble.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(15);
  expect(box!.x + box!.width).toBeLessThanOrEqual(375 - 15);
  await page.keyboard.press("Escape");
  await expect(bubble).toHaveCount(0);
});
