# Control Room · Project guide

This guide explains the whole project for anyone (or any Claude Code session) picking it up cold.
It covers the why, the maths, every module, the API contract, the UI, the design system, the tests
and how to extend each part. For the task list and what's next, see `../roadmap.txt`. For the
reasons behind specific choices, see `../DECISIONS.md`. Screens are in `design/` as images.

---

## 1. The story

Dior runs three live apps. Senior engineers are trusted with production because they *own* it:
SLOs, alerting that does not cry wolf, and incidents with a paper trail. Control Room gives each
app an error budget, watches how fast it burns, and when the burn is dangerous it:

1. opens a ticket in **Resolve** (Dior's own service desk) with the SLA clock running,
2. pages Dior on **Telegram**,
3. records everything on the incident **timeline**,
4. arms a **deploy gate** so risky deploys fail in CI while the budget is low,
5. drafts a blameless **postmortem** when the incident closes.

The interview line: *"My side projects have SLOs, burn-rate alerts and postmortems, and my own
service desk pages me."*

| App | Stack | SLOs (see `slos.yaml`) |
|---|---|---|
| Resolve | Next.js 15, Prisma, Neon, Vercel | tickets load and save 99.9%; pages respond in 400 ms (p95) 99% |
| RepoLens | Python + JS, Render free tier (sleeps), Gemini Examiner with fallback | scans finish 99.5% (cold starts excluded); Examiner fallback rate (informational) |
| JobBridge | FastAPI, React, Postgres, Neo4j, Docker on a VM | match reasons in 2.5 s 95%; sign-in works 99.9% |

What makes it more than a dashboard:
- **AI-aware SLIs:** LLM fallback rate, token cost per request, explanation latency.
- **Cold-start honesty:** RepoLens sleeps; a slow first answer inside the 50 s wake window is
  logged as `cold_start` and never spends budget.
- **Deploy gate:** a GitHub Action asks `/budget/{service}` before deploying.
- **Closed loop:** alert → ticket → page → timeline → postmortem draft.

---

## 2. The maths (read this before touching `burnrate.py`)

```
SLI          = good events / valid events
error ratio  = bad events / valid events over a window
budget       = 1 − objective                (99.5% → 0.005)
burn rate    = error ratio / budget         (1× spends exactly the whole budget in 28 days)
remaining    = 1 − (error ratio over 28 days / budget)        (negative = SLO breached)
time to exhaustion = 28 days × remaining / burn(1h)           (None when burn < 1×)
```

**Tiers** (SRE Workbook, table 5-8), defined in `slos.yaml`:

| Tier id | Name | Long window | Short window | Threshold | Means | Severity |
|---|---|---|---|---|---|---|
| `page-1h` | Fast burn | 1h | 5m | 14.4× | 2% of budget gone in an hour | page, P1 |
| `page-6h` | Slow burn | 6h | 30m | 6× | 5% in six hours | page, P2 |
| `ticket-3d` | Ticket | 3d | 6h | 1× | 10% in three days | ticket, P3 |

A tier **fires only when both windows exceed the threshold**. The long window proves the burn is
real (a blip can't fill an hour); the short window proves it is still happening and gives a fast
reset when the burn stops.

Tier states (`burnrate.TierReading.state`):
- `firing` — both windows over
- `pending` — only the short window over (a spike that may be a blip)
- `cooling` — only the long window over (burn stopped; alert has reset)
- `inactive` — neither

**Worked example (the 8 Nov replay).** RepoLens objective 99.5% (budget 0.005).
From 09:41 EAT, 40% of scans fail.
- 09:42: the 5m window shows 16.4× while the 1h shows 1.8×, so the alert is pending. A 2-minute
  blip would end here.
- 09:52: the 1h window reaches about 15.1× ((49 × 0.0025 + 11 × 0.40) / 60 / 0.005), and the
  5m window is at 80×. The page fires.
- 10:11: the fix lands (the model order is flipped via an env flag) and the error rate falls to 2%.
- 10:16: the 5m window drops to 4×, under 14.4×, so the fast burn resets. The 1h window is still
  around 40× (cooling).
- 10:40: the slow-burn tier resets. With no page tier firing, the incident moves to monitoring and
  auto-resolves at 11:40.

---

## 3. Architecture

```
            ┌──────────────── live apps ────────────────┐
            │ Resolve      RepoLens      JobBridge      │   (M1–M2: OpenTelemetry SDKs)
            └──────┬────────────┬─────────────┬─────────┘
                   │ OTLP       │             │      probes/ (M2) → probe_runs_total
                   ▼            ▼             ▼
            OpenTelemetry Collector  →  Prometheus (+ Tempo, Grafana)       (M1, not built)
                                             │ PromQL instant queries
                                             ▼
┌──────────────────────────── engine/ (Python, FastAPI) ─────────────────────────────┐
│ config.py ← slos.yaml                                                              │
│ sources.py   MetricSource: PrometheusSource | ProfileSource (replay/tests)         │
│ engine.py    evaluate(now) every 60 s:                                             │
│              ratios(6 windows) → burnrate.py → alerts.py (transitions)             │
│              → incidents.py (tickets, pages, timeline) → deploy-gate state         │
│ adapters.py  ResolveSink / MemorySink · WebhookPager(Telegram) / MemoryPager       │
│ postmortem.py, status.py, scenario.py (8 Nov replay)                               │
│ api.py       /api/* JSON + /budget/{service} + serves web/dist                     │
└───────────────────────────────┬────────────────────────────────────────────────────┘
                                │ fetch /api/*
                                ▼
                 web/ (React + TS): Status · Budgets · Incident · Guide
                                ▲
GitHub Actions in app repos ────┘ GET /budget/{service}?labels=…  (budget-gate action)
```

**Modes** (decided at startup in `api.State`):
- **replay** (default, no env): `scenario.run()` warms the engine from 6 Nov, then evaluates
  every minute from 09:30 to 10:52 EAT on 8 Nov. "Now" is fixed at 10:52 EAT.
- **live** (`PROMETHEUS_URL` set): a background thread calls `engine.evaluate(utcnow)` every
  `EVAL_INTERVAL_S` (60) seconds. Resolve/Telegram adapters switch on from env vars.

---

## 4. Engine, module by module (`engine/controlroom/`)

| Module | Responsibility | Key names | Invariants |
|---|---|---|---|
| `config.py` | Parse `slos.yaml` into frozen dataclasses | `load()`, `Config`, `Service`, `SLO`, `Tier`, `parse_duration`, `prom_range` | objectives in (0,1); durations like `5m`, `3d` |
| `sources.py` | Answer "error ratio over (end − window, end]" | `MetricSource` protocol, `Profile`, `Segment`, `ProfileSource`, `PrometheusSource` | Profile segments never overlap; mean integrates analytically |
| `burnrate.py` | Pure maths | `burn_rate`, `budget_remaining`, `time_to_exhaustion`, `evaluate_tier`, `TierReading` | no I/O; thresholds only from config |
| `alerts.py` | Per-key lifecycle and dedup | `AlertTracker.update()`, `AlertEvent` | emits only on transitions → one ticket per firing |
| `incidents.py` | Incidents, tickets, pages, timeline, SLA | `IncidentManager.handle/record/tick`, `Incident`, `TimelineEvent`, `PRIORITY`, `SLA` | one open incident per (service, slo, class); ticket tier suppressed for 3 d after a page on the same SLO |
| `engine.py` | Orchestration per evaluation | `Engine.evaluate(now)`, `Engine.run()`, `Annotation` | call in increasing time order; returns the snapshot dict |
| `adapters.py` | Outbound integrations | `TicketSink`, `Pager`, `MemorySink(reserved=…)`, `ResolveSink`, `WebhookPager`, `from_env()` | Resolve endpoint is a proposal (docs/resolve-api.md) |
| `probes.py` | Synthetic checks | `classify()`, `http_probe()` | cold_start only if was_idle and latency ≤ wake window |
| `postmortem.py` | Deterministic draft | `draft()` → summary, impact, root cause (TBC), timeline, actions, markdown | `published` is always False |
| `status.py` | Public view | `public_state`, `day_strip`, `uptime` | uptime uses the strictest (availability) SLO |
| `scenario.py` | Replay data | `profiles()`, `ANNOTATIONS`, `HISTORY`, `COLD_DAYS`, `run()`, `eat()` | only human/external facts are hand-written |
| `api.py` | HTTP | FastAPI `app`, `State` | replay endpoints 404 in live mode |

**Timeline event kinds** (`TimelineEvent.kind`): `engine`, `ticket`, `page`, `gate`, `probe`,
`note`, `ack`, `change`. `key=True` marks the moments the UI highlights (amber pin). `ack` sets
`Incident.acked_at` (SLA response met). The postmortem's root-cause notes use only `note`
and `change`.

**Incident lifecycle**
```
firing ──(all tiers of its class reset)──► monitoring ──(60 quiet min)──► resolved
   ▲                                          │
   └──────────(a tier fires again)────────────┘
```

---

## 5. API contract

All times are ISO 8601 UTC; the UI renders EAT (UTC+3). Rates are floats (`15.1` = 15.1×).

`GET /api/health` → `{ok, mode: "replay"|"live", at, last_error}`

`GET /api/budgets` → snapshot:
```jsonc
{ "mode": "replay", "at": "2026-11-08T07:52:00+00:00",
  "services": [{
    "id": "repolens", "name": "RepoLens", "callsign": "SCAN", "description": "…",
    "state": "nominal|ticket|page|breach",
    "slos": [{
      "id": "scan-success", "name": "Scans finish", "objective": 0.995, "informational": false,
      "remaining": 0.4187,
      "error_ratio": {"5m":…, "30m":…, "1h":…, "6h":…, "3d":…, "28d":…},
      "burn":        {"5m":…, "30m":…, "1h":…, "6h":…, "3d":…, "28d":…},
      "tte_seconds": 38280.0, "drain_per_min": 0.00065,
      "gate": {"floor": 0.45, "armed": true},
      "tiers": [{"id":"page-1h","name":"Fast burn","severity":"page","threshold":14.4,
                 "long":"1h","short":"5m","long_rate":26.4,"short_rate":0.5,"state":"cooling"}, …]
    }]
  }],
  "incidents": [ /* Incident without timeline/context */ ] }
```

`GET /api/replay` (replay mode only) →
`{start, end, step_s: 60, frames: [snapshot…] (83), history: {serviceId: [{at, remaining}] (29 daily points)}, incidents: [Incident with timeline]}`

`GET /api/status` →
`{mode, at, services: [{id, name, description, state: "nominal|degraded|outage", uptime_90d, days: [{date, status: "nominal|burning|outage|cold", burn, note}] (91), objectives}], active: [Incident + last], history: [{id, service, title, start, end, status, detail}]}`

`GET /api/incidents` → list of Incident summaries.
`GET /api/incidents/{id}` → Incident with `timeline`, `context` (at fire), plus
`service_name, slo_name, objective, now, remaining_now, gate, trace: [{at, h1, m5}], postmortem`.

Incident shape:
`{id, service, slo, class: "page"|"ticket", title, priority: "P1"|"P2"|"P3", status, opened_at, resolved_at, quiet_since, firing: [tierIds], sla: {respond_by, resolve_by, responded_at}}`

`GET /budget/{service}?labels=a,b` → `{service, allow, reason, slos: [{slo, remaining, floor, armed}], at}`.
`allow` is false when any SLO is under its floor, unless `labels` contains `emergency-fix`.

TypeScript mirrors of all shapes live in `web/src/api.ts`; keep them in sync.

---

## 6. The replay scenario (`scenario.py`)

Error-ratio profiles (piecewise constant, steady traffic assumed):

| Service / SLO | Baseline | Notable segments |
|---|---|---|
| resolve / api-availability | 0.013% (0.13×) | 21 Oct 13:40–14:12 at 5.55% (pool exhaustion) |
| resolve / api-latency | 0.12% | 19 Sep 10:00–10:06 60%; 21 Oct 13:40–14:12 35% |
| repolens / scan-success | 0.25% (0.5×) | 1 Sep quota; 30 Sep 41-min outage; 27 Oct slow wakes; **8 Nov 09:41–10:11 40%**, 10:11–10:24 2% |
| repolens / examiner-fallback | 7% | 8 Nov 64% then 3% |
| jobbridge / match-latency | 2% (0.4×) | 9 Oct 70%; from 5 Nov 09:30 6.5% (1.3×) → ticket RSV-1039 |
| jobbridge / auth-availability | 0.01% | 2 Nov 21:14–21:28 25% |

Hand-written annotations: the 09:41 probe failure, Dior's 09:58 ack, the 10:04 note, the 10:11
config change and the 10:48 cold start. Ticket numbers 1039 and 1042 are reserved so the replay
matches Resolve's history. Past incidents before the replay (`HISTORY`) are static.

---

## 7. Web app (`web/src/`)

- **Routing:** hash routes in `hooks.ts` (`#/`, `#/budgets`, `#/incidents/:id`, anything else → 404).
- **Data:** `useData(path)` → `{state: loading|error|ready}`; `Loaded` renders the warm-up,
  "Link lost" fault (with retry) or the screen.
- **Theme:** `<html data-lights="up|down">`, set before paint by the script in `index.html`
  (localStorage `cr.lights`, else `prefers-color-scheme`), toggled by the House lights knob.
- **Screens**
  - `StatusScreen` — big board headline, per-service lamp, 91-day strip (`DayStrip`: hover, or
    focus and use ← → Home End), 90-day SLI, three consoles, incident history.
  - `BudgetsScreen` — `Wall` plays `/api/replay` frames (250 ms per engine minute; 500 ms under
    reduced motion). Master caution compares lit keys (`service/slo/tier`, `…/gate`) with the
    acknowledged set. Includes the 28-day chart (last point live), incident strip (slides in, its
    timeline auto-scrolls), consoles (`Desk`: tank, needle, gate floor, 1h/5m log meters,
    readouts; `Gate`: lift cover → emergency-fix toggle). The scrubber pauses and scrubs.
  - `IncidentScreen` — SLA drum (counts down from the engine's "now"), burn trace (log scale,
    paging band, numbered pins), loop (buttons with `aria-pressed`, linked to pins), context,
    gate, postmortem draft (checkboxes, Mark reviewed, Copy Markdown).
- **Guide** (`Guide.tsx`) — `STEPS` (11) each `{hash, target, title, body}` targeting
  `[data-guide="…"]`. It navigates, waits for the target, scrolls under the sticky header, and
  draws a spotlight ring. Keys ← → Esc, focus trap, aria-live. The invitation shows once
  (localStorage `cr.guide.seen`). `HelpDrawer` opens with `?`: full tour, tour this screen,
  pipeline, glossary, keys.
  **If you rename or move a `data-guide` attribute, update `STEPS`.**
  Current targets: board, strips, cold, controls, tank, meters, strip, gate, trace, postmortem,
  guide-key (plus loop, console).
- **URL params for demos/screenshots:** `?lights=up|down`, `?guide=off`.

---

## 8. Design system: "House Lights"

See `design/` for screenshots of every screen (light, dark, 375 px) and `design/canvas/` for
the original artboards.

- **Concept:** a 1960s mission operations room. One shared **big board** (dark projection
  screen with a plotboard grid, dark in both modes) over a row of sage **consoles**, each with an
  annunciator riser, a desk and a deploy-gate kick panel.
- **Colour = lamps only:** white `#F1E8CA` nominal/advisory · amber `#E59C2F` budget burning ·
  red `#A9412F` breach/outage. Everything else is neutral (wall `#E6DDC8`, console `#AAB08F`,
  ink `#1D2115`, board `#1B1F18`). Dark mode = "house lights down" (wall `#11130D`,
  console `#2A2F21`, ink `#E6E0CA`).
- **Type:** Barlow Condensed 500–700 (display, plates, lamps, uppercase), Barlow (body),
  Share Tech Mono (numbers, times, IDs). Loaded from Google Fonts in `index.html`.
- **Shape:** 2px radii, hard offset shadows, physical keys that press down 4px, no glow, blur
  or gradient fills.
- **Signature pieces:** draining budget tank with flow ticks and gate floor; incident strip
  sliding in from the edge; annunciator riser, master caution and lamp test; guarded gate switch.
- **Accessibility:** contrast checked (AA in both modes); visible ink focus rings; every control
  is a real button, link or input; meters use `role="meter"`; the SLA uses `role="timer"`; under
  `prefers-reduced-motion` all animation stops.

References: restored Apollo MOCR (palette, console row), Mission Control "big boards", aircraft
annunciator panels and master caution, Google SRE Workbook tiers, GitHub-style status pages,
CSS scroll-driven animations (incident loop entries slide in via `animation-timeline: view()`).

---

## 9. Tests

`engine/tests/` (run `cd engine && .venv/Scripts/python -m pytest -q`):

| Test | Proves |
|---|---|
| `test_burnrate.py` | formulas, 14.4× ≈ 2.08 days to empty a 30-day budget, tier states, profile integration, durations |
| `test_two_minute_blip_does_not_page` | 100% errors for 2 min on 99.5% → pending only, no ticket, no page |
| `test_sustained_5xx_spike_pages_within_the_detection_window` | 20% errors → page 20–23 min in; one ticket, one page after 3 more hours |
| `test_one_ticket_resolves_when_the_burn_stops` | reset ≤ 5 min after the burn stops; resolved 60 min later; still one ticket |
| `test_slow_leak_opens_a_ticket_not_a_page` | 3× steady → P3 ticket at ~20 h, no page |
| `test_deploy_gate_arms_under_the_floor` | gate flips when remaining < floor |
| `test_replay_of_8_november` | exact replay times (09:52 fire, 10:16 reset, 11:40 resolve), suppression, ack |
| `test_api.py` | endpoints, lamp states, 83 frames, 404s, gate override |

Web has no automated tests yet (Playwright + Vitest are in roadmap M5). `npm run build` runs
`tsc` in strict mode.

---

## 10. How to extend

- **Add an SLO:** add it under the service in `slos.yaml` (id, name, objective, deploy_floor,
  error_query, valid_query). In replay, also add a `Profile` in `scenario.profiles()`.
  Nothing else changes.
- **Add a service:** add it to `slos.yaml` with a callsign. The consoles grid assumes three
  columns at desktop; four will wrap to 2×2 at ≤1180 px, which is fine.
- **Change a threshold or window:** edit `tiers` in `slos.yaml`. Then update the UI copy that
  mentions 14.4 / 6 / 1 (Budgets footer, meters' threshold line `THR`, Guide, HelpDrawer).
- **New metric backend:** implement `MetricSource.error_ratio()` and choose it in `api.State`.
- **Real Resolve:** land docs/resolve-api.md in the Resolve repo, set `RESOLVE_URL` /
  `RESOLVE_TOKEN`, and add idempotency keys in `ResolveSink.open`.
- **New screen:** add a route in `hooks.parseHash`, a nav link in `App.tsx`, a screen in
  `screens/`, `data-guide` targets and guide `STEPS`, and a screenshot in `docs/design/`.

---

## 11. Conventions

- DiorWachira is the only git contributor. No co-author or "generated with" trailers.
- Python ≥ 3.11 syntax (CI uses 3.12). Keep `burnrate.py` pure.
- No UI or chart libraries in `web/`; hand-written SVG.
- Amber means burning budget and nothing else. Never use it for focus, links or emphasis.
- Every timeline text is a full sentence a human would write in an incident channel.
- Times on screen are EAT; times in the API are UTC.
