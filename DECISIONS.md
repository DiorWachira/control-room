# Decisions

Short records of choices that are not obvious from the code. Newest first.

## 2026-11-09 · The live board runs on synthetic probes until OpenTelemetry lands
Instrumenting each app is work in each app's repo (M1–M2, JobBridge deferred). Meanwhile a GitHub
Actions cron probes seven deployed apps every 15 minutes (`probes.yaml`) and the real engine
evaluates that history. No server is needed: the log lives on a `probe-data` branch (one commit,
force-pushed, so the branch never grows), and the engine is rebuilt deterministically from the
log every run, which also makes ticket ids stable (`CR-<CALLSIGN>-<MMDD>-<HHMM>`). Side effects
are separated from the rebuild: `notify.py` sends each page once and never sends one older than
two hours. Telegram acks are read by polling `getUpdates`, because there is no webhook endpoint.

## 2026-11-09 · Probe SLO 98%, 30-minute lookback, one-day warm-up
Probes are sparse (2 requests per app per 15 min), so a 5-minute window would usually be empty
and no page could fire; windows shorter than 30 minutes read the last 30. At 98%, one failed
run (2 of 8 attempts in the hour = 12.5×) does not page and two in a row (25×) do. The chaos
drill showed that on a fresh history a single blip looked like a 3-day burn and opened a ticket,
so a window only answers once the history covers min(window, 1 day).

## 2026-11-09 · LLM postmortem pass: Claude, cached, never published
`postmortem.refine()` sends the deterministic draft to `claude-opus-5-5` with a JSON schema
(summary, probable cause, evidence, follow-ups) and the server-side refusal fallback. It runs once
per resolved incident (cached in `postmortems.json`) and shows next to the draft, labelled
"AI rewrite · to be confirmed". Without `ANTHROPIC_API_KEY`, or on any error or refusal, the
deterministic draft stands alone.

## 2026-11-09 · Telemetry backend: self-hosted on the JobBridge VM
OpenTelemetry Collector + Prometheus + Tempo + Grafana in Docker Compose (`infra/`), not Grafana
Cloud's free tier. The free tier keeps metrics for 14 days and every SLO here is a 28-day window,
so budgets would be computed from half the data. Self-hosting costs nothing extra (the VM already
runs JobBridge), keeps 35 days (28 plus a week of slack) and keeps the PromQL in `slos.yaml`
portable. Ops load is one compose file with pinned images; Prometheus, Tempo and Grafana only
listen on localhost or the internal network. The collector copies `service.name` onto a `service`
label so the selectors in `slos.yaml` work unchanged.

## 2026-11-09 · Public demo is a static replay on GitHub Pages
The 8 November replay is deterministic, so `python -m controlroom.export` freezes every API answer
to JSON at build time and `vite build --mode static` reads those files (`VITE_STATIC=1`). The demo
is free, never sleeps and needs no secrets. Live mode still needs the engine (Dockerfile) on the VM.

## 2026-11-09 · Guide steps are pointer bubbles, not a floating card
Each CHECK card now points at its panel with a caret, like the coach marks people know from other
sites. Placement is measured (real bubble height): below, above, right, left, else inside the
panel's visible part (no caret). On phones (<= 560 px) it docks to the edge away from the panel.
After a smooth scroll settles the guide re-checks the panel's position and corrects it, because
fast Next presses can overlap two smooth scrolls. A first step now introduces the three screens.

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
- Backend for telemetry: self-hosted Prometheus + Tempo + Grafana (see the entry above).

## 2026-11-09 · Design: "House Lights"
A 1960s operations room: a shared big board over a row of sage consoles. Lamps are the only
colour (white nominal/advisory, amber budget burning, red breach). Barlow Condensed + Barlow +
Share Tech Mono. Design canvas: https://claude.ai/artifact/NpTxuU7g2miz56FNBYwxWC
Note: `~/.claude/CLAUDE.md` later retired "annunciator lamps" as a house look (after Context
Profiler). Control Room's brief explicitly asked for annunciator panels, so they stay here;
do not carry them into the next project.
