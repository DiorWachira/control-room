import { expect, test } from "@playwright/test";
import { guideSeen } from "./helpers";

test.beforeEach(async ({ page }) => guideSeen(page));

// The e2e build ships the deterministic replay. To exercise the live board, this rewrites the
// status payload into what probe mode serves: seven-ish apps, empty days before probing, one
// app gone quiet, a stale reading, links to each app.
test("live board: no-data days, no-signal lamp, stale banner, app links, empty history", async ({ page }) => {
  await page.route("**/api/status.json", async (route) => {
    const res = await route.fetch();
    const st = await res.json();
    const old = new Date(Date.now() - 3 * 3600_000).toISOString();
    st.mode = "probes";
    st.at = old;
    st.since = new Date(Date.now() - 2 * 86400_000).toISOString();
    st.interval = "15m";
    st.active = [];
    st.history = [];
    st.services = st.services.map((s: Record<string, unknown>, k: number) => ({
      ...s,
      state: k === 2 ? "nosignal" : "nominal",
      url: `https://example.test/${s.id}/`,
      last_probe: old,
      days: (s.days as { date: string }[]).map((d, i, all) => (i < all.length - 3 ? { ...d, status: "nodata", note: "No probes this day" } : d)),
    }));
    await route.fulfill({ response: res, json: st });
  });
  await page.goto("./");
  await expect(page.getByText("live probes every 15m", { exact: false })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Signal lost" })).toContainText("3 h ago");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Two of three systems nominal/i);
  await expect(page.getByText("No signal", { exact: true })).toBeVisible();
  await expect(page.locator(".tick.is-nodata").first()).toBeVisible();
  await expect(page.getByText("No probes yet")).toBeVisible();
  const link = page.getByRole("link", { name: /example\.test/ }).first();
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(page.getByText(/No page-level incidents since probing began/)).toBeVisible();
  await page.getByRole("link", { name: "Open the RSV-1042 replay →" }).click();
  await expect(page.getByText("Replay · 8 Nov", { exact: false })).toHaveCount(0); // the e2e build is replay mode
  await expect(page.locator('[data-guide="trace"]')).toBeVisible();
});

test("master caution lights on new lamps and goes dark when acknowledged", async ({ page }) => {
  await page.goto("./#/budgets");
  const mc = page.getByRole("button", { name: /^Master caution lit/ });
  await expect(mc).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Hold", exact: true }).click();
  await mc.click();
  await expect(page.getByRole("button", { name: "Master caution off" })).toBeVisible();
});
