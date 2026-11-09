"""Synthetic probes with cold-start honesty.

RepoLens sleeps on Render's free tier. A slow first response that still succeeds inside the
documented wake window is a cold start, not an error, and is excluded from the SLI.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

SUCCESS, COLD_START, ERROR = "success", "cold_start", "error"


@dataclass(frozen=True)
class ProbeResult:
    service: str
    journey: str
    outcome: str
    latency_s: float
    detail: str = ""


def classify(ok: bool, latency_s: float, *, slow_threshold_s: float = 10.0, wake_window_s: float | None = None,
             was_idle: bool = False) -> str:
    """success: ok and fast. cold_start: ok, slow, but inside the wake window after an idle period.
    error: failed, or slower than the wake window allows."""
    if not ok:
        return ERROR
    if latency_s <= slow_threshold_s:
        return SUCCESS
    if wake_window_s is not None and was_idle and latency_s <= wake_window_s:
        return COLD_START
    return ERROR


def http_probe(service: str, journey: str, url: str, *, method: str = "GET", body: dict | None = None,
               timeout_s: float = 60.0, expect_status: int = 200, **classify_kw) -> ProbeResult:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "User-Agent": "control-room-probe/0.1"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            ok, detail = r.status == expect_status, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        ok, detail = False, f"HTTP {e.code}"
    except Exception as e:  # timeouts, DNS, resets
        ok, detail = False, type(e).__name__
    latency = time.monotonic() - t0
    return ProbeResult(service, journey, classify(ok, latency, **classify_kw), latency, detail)
