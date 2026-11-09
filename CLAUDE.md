# Control Room · notes for Claude Code

Start here, in this order:
1. `roadmap.txt` — milestones, what is done, what is next, gotchas.
2. `docs/PROJECT_GUIDE.md` — the full explanation: maths, architecture, every module, API
   contract, UI, design system, tests, how to extend.
3. `docs/design/` — screenshots of every screen (light, dark, 375 px). Open the matching image
   before changing a screen; the look must stay consistent with them.
4. `DECISIONS.md` — why things are the way they are.

Rules:
- Engine: `cd engine && .venv/Scripts/python -m pytest -q` must stay green. The maths lives in
  `controlroom/burnrate.py`; never change thresholds in code, change `slos.yaml`.
- Web: `cd web && npm run build` must pass (tsc strict). No UI or chart libraries; SVG by hand.
- Design tokens are in `web/src/styles.css` (`:root` and `[data-lights="down"]`). Amber means
  "budget burning" and nothing else; red means breach/outage only.
- Keep the guide (`web/src/guideSteps.ts` STEPS) in sync when a screen's `data-guide` targets move;
  `cd web && npx playwright test` walks every step and fails on a missing target.
- Re-capture `docs/design/*.png` when a screen's look changes on purpose (see docs/design/README.md).
- Git: DiorWachira is the only contributor. No co-author or "generated with" trailers.
- `agentacl/`, `context-profiler/`, `receipt-index/` at the repo root are other projects' design
  files, kept locally on purpose. Do not commit them, edit them or build on them.
