# Control Room

SLOs, multi-window burn-rate alerts and auto-filed incidents for my live apps:
**Resolve** (service desk), **RepoLens** (repo examiner) and **JobBridge** (job matching).

When an error budget burns too fast, Control Room opens a ticket in Resolve with the SLA clock
already running, pages me on Telegram, keeps the incident timeline and drafts a blameless
postmortem. A GitHub Action blocks risky deploys while a budget is under its floor.

> "My side projects have SLOs, burn-rate alerts and postmortems, and my own service desk pages me."

**Live demo:** https://diorwachira.github.io/control-room/ (the 8 November replay, frozen by the
real engine at build time; take the guide or press `?`).

![Guide bubble on the status board](docs/design/10-guide-bubble-light.png)

## Status
Working today (replay mode): the burn-rate engine, alert lifecycle, incident manager, deploy gate
API, postmortem draft, and the web UI (status board, budget console wall, incident detail, guide).
Also: the telemetry stack as code (`infra/`), Resolve and Telegram adapters with idempotency and
retries, Playwright e2e and a GitHub Pages deploy.
Not yet: real telemetry flowing, the Resolve endpoint, live probes. See `roadmap.txt`.

## Run it

```bash
# engine (API on :8000, also serves web/dist if built)
cd engine
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn controlroom.api:app --reload --port 8000
```

```bash
# web (dev server on :5173, proxies /api and /budget to :8000)
cd web
npm install
npm run dev
```

Production-style: `npm run build` in `web/`, then open http://localhost:8000.

```bash
# static demo + e2e (what GitHub Pages serves)
cd engine && .venv/Scripts/python -m controlroom.export ../web/.static/api
cd ../web && npx playwright test     # builds --mode static and serves it on :4174
```

```bash
# telemetry backbone (M1), on the VM
GRAFANA_ADMIN_PASSWORD=... docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml --profile live up -d engine   # once apps send data
```

## How it works
1. Probes and OpenTelemetry count good and valid events per SLI (`slos.yaml`).
2. Every minute the engine asks for error ratios over 5m, 30m, 1h, 6h, 3d and 28d.
3. Burn rate = error ratio ÷ (1 − objective). Tiers from the SRE Workbook: page at 14.4×
   (1h and 5m), page at 6× (6h and 30m), ticket at 1× (3d and 6h). Both windows must agree.
4. A firing tier opens one Resolve ticket per (service, SLO, class), pages, and writes the timeline.
5. When every page tier clears, the incident moves to Monitoring and resolves after 60 quiet minutes.
6. `GET /budget/{service}?labels=...` answers the deploy gate; `emergency-fix` overrides.

## Layout
```
slos.yaml                 SLOs and alert tiers as code
infra/                    collector, prometheus (35d), tempo, grafana; docker compose
Dockerfile                engine + web image
engine/controlroom/       config, sources, burnrate, alerts, incidents, engine, probes,
                          adapters (Resolve, Telegram), postmortem, status, scenario, api
engine/tests/             acceptance tests (blip, spike, one ticket, slow leak, gate, replay)
web/src/                  React UI: screens/, Guide.tsx + guideSteps.ts, styles.css (tokens)
web/e2e/                  Playwright tests (static build)
.github/actions/budget-gate/   composite action for the app repos
docs/resolve-api.md       endpoint Resolve needs to add
DECISIONS.md              why things are the way they are
roadmap.txt               milestones and handoff notes
```

## Design: "House Lights"
A 1960s mission operations room: one big board over a row of sage consoles; lamps are the only
colour. References: the restored Apollo Mission Operations Control Room (palette and console
row), Mission Control's "big boards" (shared projection screen), aircraft annunciator panels and
master caution (lamp grid, acknowledge, lamp test), the Google SRE Workbook (tiers become lamps),
GitHub-style status pages (component rows, 90-day bars), CSS scroll-driven animations (incident
log entries slide in). Type: Barlow Condensed, Barlow, Share Tech Mono.
