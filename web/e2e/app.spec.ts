import { expect, test } from "@playwright/test";
import { guideSeen } from "./helpers";

test.beforeEach(async ({ page }) => guideSeen(page));

test("? opens the flight manual from anywhere; tour this screen starts a scoped tour", async ({ page }) => {
  await page.goto("./#/budgets");
  await expect(page.locator('[data-guide="controls"]')).toBeVisible();
  await page.keyboard.press("?");
  const drawer = page.getByRole("dialog", { name: "Flight manual" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Burn rate", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);

  await page.getByRole("button", { name: /Guide/ }).click();
  await page.getByRole("dialog", { name: "Flight manual" }).getByRole("button", { name: "Tour this screen" }).click();
  await expect(page.getByTestId("guide-bubble")).toContainText("Check 1 / 5");
  await expect(page.getByTestId("guide-bubble")).toContainText("Replay a real morning");
});

test("status strip reads a day on hover and with arrow keys", async ({ page }) => {
  await page.goto("./");
  const strip = page.getByRole("group", { name: /RepoLens: last 91 days/ });
  await strip.focus();
  await page.keyboard.press("End");
  const scale = page.locator(".ticks-cell", { has: strip }).locator(".strip-scale");
  await expect(scale).toContainText("8 Nov");
  await page.keyboard.press("ArrowLeft");
  await expect(scale).toContainText("7 Nov");
  await strip.locator(".tick").first().hover();
  await expect(scale).toContainText("Aug");
});

test("budget replay reaches the incident strip and links to the incident", async ({ page }) => {
  await page.goto("./#/budgets");
  const strip = page.locator('[data-guide="strip"]');
  await expect(strip.getByText("RSV-1042", { exact: true })).toBeVisible({ timeout: 30_000 });
  await strip.getByRole("link", { name: /Open incident/ }).click();
  expect(page.url()).toContain("#/incidents/RSV-1042");
  await expect(page.locator('[data-guide="trace"]')).toBeVisible();
  await expect(page.locator('[data-guide="postmortem"]')).toBeVisible();
});

test("deploy gate override needs the cover lifted first", async ({ page }) => {
  await page.goto("./#/budgets");
  const gate = page.locator('[data-guide="gate"]');
  const toggle = gate.getByRole("button", { name: "Emergency-fix" });
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  await expect(toggle).toBeDisabled();
  await gate.getByRole("button", { name: "Lift cover" }).click();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
});

test("unknown routes show the loss-of-signal page", async ({ page }) => {
  await page.goto("./#/nowhere");
  await expect(page.getByRole("heading", { name: /Loss of signal/ })).toBeVisible();
});
