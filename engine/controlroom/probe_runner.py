"""Run one round of synthetic probes and append them to the probe log.

    python -m controlroom.probe_runner probe-data/runs           # uses probes.yaml

Every app is probed in parallel, `attempts` times with a short gap. An app that has not
answered successfully for `idle_after` may be asleep (Render free tier), so a slow first answer
inside its wake window is logged as cold_start and never spends budget.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import config as config_mod
from .config import Config, Service, parse_duration
from .probelog import ProbeRecord, append, prune, read_log
from .probes import ProbeResult, http_probe

Prober = Callable[..., ProbeResult]


def last_success(records: list[ProbeRecord]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for r in records:
        if r.outcome != "error":
            out[r.service] = r.at
    return out


def probe_service(svc: Service, settings: dict, was_idle: bool, prober: Prober = http_probe,
                  sleep: Callable[[float], None] = time.sleep, at0: datetime | None = None) -> list[ProbeRecord]:
    """at0 pins the record times (drills on a simulated clock); otherwise wall-clock time."""
    p = svc.probe or {}
    attempts = int(settings.get("attempts", 2))
    out: list[ProbeRecord] = []
    for n in range(1, attempts + 1):
        gap = float(settings.get("attempt_gap_s", 10))
        at = at0 + timedelta(seconds=gap * (n - 1)) if at0 else datetime.now(timezone.utc)
        res = prober(svc.id, "home", p["url"], timeout_s=float(p.get("timeout_s", 30)),
                     expect_status=int(p.get("expect_status", 200)), expect_text=p.get("expect_text"),
                     slow_threshold_s=float(settings.get("slow_threshold_s", 10)),
                     wake_window_s=svc.cold_start_window_s, was_idle=was_idle and n == 1)
        out.append(ProbeRecord(at, svc.id, n, res.outcome, res.latency_s, res.detail))
        if n < attempts:
            sleep(float(settings.get("attempt_gap_s", 10)))
    return out


def run_round(cfg: Config, log_dir: str | Path, prober: Prober = http_probe, now: datetime | None = None,
              sleep: Callable[[float], None] = time.sleep) -> list[ProbeRecord]:
    now = now or datetime.now(timezone.utc)
    history = read_log(log_dir)
    ok_at = last_success(history)
    idle = parse_duration(cfg.probe.get("idle_after", "15m"))
    targets = [s for s in cfg.services if s.probe]
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
        futures = [pool.submit(probe_service, s, cfg.probe, s.id not in ok_at or now - ok_at[s.id] > idle, prober, sleep)
                   for s in targets]
        records = [r for f in futures for r in f.result()]
    records.sort(key=lambda r: (r.at, r.service))
    append(log_dir, records)
    prune(log_dir, now.date())
    return records


def main(argv: list[str]) -> int:
    log_dir = Path(argv[1] if len(argv) > 1 else "probe-data/runs")
    cfg = config_mod.load(config_mod.probes_path())
    records = run_round(cfg, log_dir)
    width = max(len(r.service) for r in records) if records else 0
    for r in records:
        print(f"{r.service:<{width}}  #{r.attempt}  {r.outcome:<10} {r.latency_s:6.2f}s  {r.detail}")
    bad = sum(r.outcome == "error" for r in records)
    print(f"{len(records)} probes, {bad} errors -> {log_dir}")
    return 0  # an app being down is data, not a failed job


if __name__ == "__main__":
    sys.exit(main(sys.argv))
