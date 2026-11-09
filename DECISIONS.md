# Decisions

Short records of choices that are not obvious from the code. Newest first.

## 2026-11-09 · Monitoring starts when every page tier is clear
The fast-burn tier reset at 10:16 on 8 Nov, but the slow-burn tier (6 h + 30 m) stayed firing
until 10:40. The incident therefore moves to Monitoring at 10:40, not 10:16, and auto-resolves
after 60 quiet minutes (11:40). The design artboard said 11:16; the engine is the source of truth.

## 2026-11-09 · One incident per (service, SLO, class), ticket tier suppressed after a page
The 3-day ticket tier also fires during a big fast burn. If a page incident for the same SLO
opened within the last 3 days, the ticket tier only adds a timeline note. One bad morning never
opens two tickets.

## 2026-11-09 · "Pending" and "cooling" are UI states, not alert states
Only firing/resolved transitions reach Resolve. Pending (short window over, long not yet) is
recorded on the timeline for page tiers so the "a blip would end here" moment is visible; it is
skipped for the ticket tier, whose short window is 6 h.

## 2026-11-09 · Error ratios come through one interface
`MetricSource.error_ratio(service, slo, end, window)` is the only thing the engine asks. Prometheus
implements it with instant queries; `ProfileSource` integrates piecewise-constant profiles
analytically (O(segments) for a 28-day window). That makes the maths testable with synthetic
series and powers the replay without a database.

## 2026-11-09 · Replay mode is the default
Until the collector and Prometheus exist (M1–M2), the API serves the 8 November scenario,
computed by the real engine minute by minute. Only human notes, probe details and incidents
closed before the replay are written by hand (`controlroom/scenario.py`).

## 2026-11-09 · Stack
- Engine: Python 3.11+ (FastAPI, PyYAML, httpx). The burn-rate evaluator is our own code; the
  point of the project is the maths and lifecycle, not a vendor's alerting.
- Web: Vite + React + TypeScript, no UI or chart library. Charts are hand-written SVG.
- Backend for telemetry: **not chosen yet** (Prometheus + Tempo + Grafana on the VM vs Grafana
  Cloud free tier). Record the choice here in M1.

## 2026-11-09 · Design: "House Lights"
A 1960s operations room: a shared big board over a row of sage consoles. Lamps are the only
colour (white nominal/advisory, amber budget burning, red breach). Barlow Condensed + Barlow +
Share Tech Mono. Design canvas: https://claude.ai/artifact/NpTxuU7g2miz56FNBYwxWC
Note: `~/.claude/CLAUDE.md` later retired "annunciator lamps" as a house look (after Context
Profiler). Control Room's brief explicitly asked for annunciator panels, so they stay here;
do not carry them into the next project.
