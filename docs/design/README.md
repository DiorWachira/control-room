# Design reference

These images are the visual source of truth for Control Room. When you change a screen, compare it
with the matching image, and re-capture the images when the look changes on purpose.

| File | Screen | Mode | Width |
|---|---|---|---|
| `01-status-light.png` | Status board (public) `#/` | house lights up | 1440 |
| `02-status-dark.png` | Status board | house lights down | 1440 |
| `03-budgets-light.png` | Budget console wall `#/budgets`, end of replay | up | 1440 |
| `04-budgets-dark.png` | Budget console wall, end of replay | down | 1440 |
| `05-incident-light.png` | Incident `#/incidents/RSV-1042` | up | 1440 |
| `06-incident-dark.png` | Incident | down | 1440 |
| `07-status-mobile.png` | Status board | up | 375 |
| `08-budgets-mobile-dark.png` | Budget wall | down | 375 |
| `09-guide-invite.png` | First-visit guide invitation | up | 1440 |
| `10-guide-bubble-light.png` | Guide CHECK 3: bubble below the 91-day strips, caret up | up | 1440 |
| `11-guide-bubble-dark.png` | Guide CHECK 9: bubble above the deploy gate, caret down | down | 1440 |
| `12-guide-bubble-mobile.png` | Guide CHECK 6 docked to the bottom edge | up | 375 |
| `13-status-live-light.png` | Live status board (probe mode), full page | up | 1440 |
| `14-status-live-dark.png` | Live status board | down | 1440 |
| `15-status-live-mobile.png` | Live status board | up | 375 |

## What to look for
- **Lamps are the only colour.** White = nominal or advisory, amber = budget burning, red = breach or
  outage. If amber appears anywhere else (a link, a focus ring, a heading), it is a bug.
- **One big board on top, a row of consoles under it.** The board is dark in both modes (it is a
  projection screen); consoles are sage in light and dark olive in dark.
- **Tight 2px radii, hard 8px "kick plate" shadows.** No glow, blur, gradient fills or soft cards.
- **Type:** Barlow Condensed uppercase for headings, plates and lamp legends; Barlow for prose;
  Share Tech Mono for every number, time and ID.

## Re-capturing
Start the engine (`uvicorn controlroom.api:app --port 8000` from `engine/`) after `npm run build` in
`web/`, then from `docs/design/` (Git Bash):

```bash
CH="/c/Program Files/Google/Chrome/Application/chrome.exe"
shot(){ "$CH" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="C:/Users/$USERNAME/AppData/Local/Temp/cr-shot-$1" --window-size=$2 --virtual-time-budget=$4 --screenshot="$(pwd -W)/$1.png" "$3"; }
shot 03-budgets-light 1440,2700 "http://localhost:8000/?lights=up&guide=off#/budgets" 30000
```

The live board images (13 to 15) come from `node web/scripts/shot-live.mjs docs/design` against a
probe-mode build (`python -m controlroom.export ../web/.static/api --probe-data DIR --probe`).
The guide images (09 to 12) come from `node web/scripts/capture.mjs docs/design` (run from the
repo root) against `npx vite preview --mode static --port 4174` after `npm run build:static`.

`?lights=up|down` forces the theme and `?guide=off` hides the first-visit invitation (both handled
in `web/index.html`). `--virtual-time-budget` lets the budget replay run to the end before capture.

## canvas/
The original design artboards (Design Component `.dc.html` files and the canvas index), as
published at https://claude.ai/artifact/NpTxuU7g2miz56FNBYwxWC. They need the canvas runtime to
render, so read them as source: copy, numbers and layout intent. The React app in `web/` is the
implementation; where the two differ, the app and `DECISIONS.md` win (e.g. Monitoring starts at
10:40, not 10:16).
