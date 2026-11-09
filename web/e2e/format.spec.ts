// Unit tests for the formatters in src/api.ts. Playwright runs them under Node (no browser),
// so the web app needs no second test runner.
import { expect, test } from "@playwright/test";
import { ago, apiUrl, dateLabel, duration, eatDay, eatTime, objective, pct, rate } from "../src/api";

test("EAT times and days are UTC+3", () => {
  expect(eatTime("2026-11-08T06:52:00+00:00")).toBe("09:52");
  expect(eatTime("2026-11-08T06:52:07Z", true)).toBe("09:52:07");
  expect(eatTime("2026-11-08T22:30:00Z")).toBe("01:30");
  expect(eatDay("2026-11-08T22:30:00Z")).toBe("9 Nov"); // after midnight in Nairobi
  expect(dateLabel("2026-08-10")).toBe("10 Aug");
});

test("percentages, rates and objectives", () => {
  expect(pct(0.4187)).toBe("41.9%");
  expect(pct(null)).toBe("—");
  expect(pct(0.99995, 2)).toBe("100.00%");
  expect(rate(15.08)).toBe("15.1×");
  expect(rate(0.5)).toBe("0.50×");
  expect(rate(undefined)).toBe("—");
  expect(objective(0.995)).toBe("99.5%");
  expect(objective(0.98)).toBe("98%");
});

test("durations and ages", () => {
  expect(duration(null)).toBe("outlasts window");
  expect(duration(38280)).toBe("10 h 38 m");
  expect(duration(3 * 86400 + 7200)).toBe("3 d 2 h");
  const now = Date.parse("2026-11-09T12:00:00Z");
  expect(ago("2026-11-09T11:56:00Z", now)).toBe("4 min ago");
  expect(ago("2026-11-09T09:00:00Z", now)).toBe("3 h ago");
  expect(ago("2026-11-06T12:00:00Z", now)).toBe("3 d ago");
  expect(ago("2026-11-09T12:05:00Z", now)).toBe("0 min ago"); // clock skew never goes negative
});

test("api paths pass through outside the static build", () => {
  expect(apiUrl("/api/status")).toBe("/api/status");
});
