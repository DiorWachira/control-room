"""Chaos drill: break a real HTTP app on purpose and prove the whole loop reacts.

    python -m controlroom.drill

Starts a throwaway app on localhost (never a live app), probes it with the real probe code on a
simulated 15-minute clock (two healthy days first), injects a 75-minute outage, then rebuilds the engine from the log
exactly as production does. It checks the acceptance criteria end to end:
  - the page fires within two failed runs, and only once (one ticket);
  - the deploy gate blocks while the budget is under its floor, and emergency-fix overrides it;
  - the alert resets when the app recovers and the incident resolves after 60 quiet minutes;
  - a single failed run on its own never pages.
Exit code 0 when every check passes.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as config_mod
from .api import gate_answer
from .config import SLO, Config, Service
from .live import build
from .probe_runner import probe_service
from .probelog import append

T0 = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)
RUN = timedelta(minutes=15)


class _App(BaseHTTPRequestHandler):
    broken = False

    def do_GET(self):  # noqa: N802
        code, body = (503, b"upstream down") if _App.broken else (200, b"<title>Drill app</title> ok")
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def run(verbose: bool = True) -> list[Check]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    tiers = config_mod.load().tiers
    svc = Service("drill", "Drill app", "DRILL", "Throwaway app for the chaos drill",
                  (SLO("site-up", "Site answers", 0.98, deploy_floor=0.5),), probe={"url": url, "expect_text": "Drill app"})
    cfg = Config(timedelta(days=28), tiers, (svc,), {"attempts": 2, "attempt_gap_s": 10, "lookback": "30m", "slow_threshold_s": 10})
    say = print if verbose else (lambda *a, **k: None)

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        # Two healthy days of history (production always has them), then at 08:00 one failed
        # run alone (a blip), 09:00-10:15 an outage, and recovery after.
        schedule = [T0 + RUN * i for i in range(-2 * 96, 33)]
        blip = {T0 + timedelta(hours=2)}
        outage = {t for t in schedule if T0 + timedelta(hours=3) <= t < T0 + timedelta(hours=4, minutes=15)}
        snapshots = {}
        for t in schedule:
            _App.broken = t in blip or t in outage
            append(data / "runs", probe_service(svc, cfg.probe, False, sleep=lambda s: None, at0=t))
            if t in (T0 + timedelta(hours=2, minutes=30), T0 + timedelta(hours=3, minutes=45), schedule[-1]):
                snapshots[t] = build(cfg, data, t + timedelta(minutes=1))[0]
        srv.shutdown()

        after_blip = snapshots[T0 + timedelta(hours=2, minutes=30)]
        mid = snapshots[T0 + timedelta(hours=3, minutes=45)]
        end = snapshots[schedule[-1]]
        again = build(cfg, data, schedule[-1] + timedelta(minutes=1))[0]

    pages = [i for i in end.incidents.incidents if i.klass == "page"]
    fired = next((e.at for e in pages[0].timeline if "fires" in e.text), None) if pages else None
    gate_mid, gate_fix = gate_answer(mid.last, "drill"), gate_answer(mid.last, "drill", "emergency-fix")
    checks = [
        Check("a single failed run does not page", not after_blip.incidents.incidents, f"{len(after_blip.incidents.incidents)} incidents after the 08:00 blip"),
        Check("the outage pages exactly once", len(pages) == 1, f"{len(pages)} page incidents, ids {[i.id for i in pages]}"),
        Check("the page fires within two failed runs", fired is not None and fired - (T0 + timedelta(hours=3)) <= RUN * 2,
              f"fired at {fired:%H:%M} UTC" if fired else "never fired"),
        Check("the deploy gate blocks under the floor", gate_mid["allow"] is False, gate_mid["reason"]),
        Check("emergency-fix overrides the gate", gate_fix["allow"] is True, gate_fix["reason"]),
        Check("the incident resolves after recovery", bool(pages) and pages[0].status == "resolved",
              f"status {pages[0].status}" if pages else "no incident"),
        Check("a rebuild gives the same ticket id", [i.id for i in again.incidents.incidents] == [i.id for i in end.incidents.incidents],
              ", ".join(i.id for i in again.incidents.incidents)),
    ]
    say(f"Chaos drill against {url} on a simulated clock from {T0:%H:%M} UTC")
    for c in checks:
        say(f"  [{'pass' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    return checks


if __name__ == "__main__":
    sys.exit(0 if all(c.ok for c in run()) else 1)
