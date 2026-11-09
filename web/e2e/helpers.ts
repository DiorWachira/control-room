import type { Page } from "@playwright/test";

/** Every test except the guide's own marks the guide as seen, so the invite never covers the UI. */
export async function guideSeen(page: Page) {
  await page.addInitScript(() => { try { localStorage.setItem("cr.guide.seen", "1"); } catch { /* ignore */ } });
}

/** Where the bubble sits relative to its target: it must not cover the panel and must stay on screen. */
export async function bubbleGeometry(page: Page, target: string) {
  return page.evaluate((t) => {
    const el = document.querySelector('[data-testid="guide-bubble"]')!;
    const b = el.getBoundingClientRect();
    const g = document.querySelector(`[data-guide="${t}"]`)!.getBoundingClientRect();
    const overlap = Math.max(0, Math.min(b.right, g.right) - Math.max(b.left, g.left)) * Math.max(0, Math.min(b.bottom, g.bottom) - Math.max(b.top, g.top));
    return {
      b: { l: b.left, t: b.top, r: b.right, btm: b.bottom }, overlap, vw: innerWidth, vh: innerHeight,
      side: [...el.classList].find((c) => c.startsWith("side-")),
    };
  }, target);
}
