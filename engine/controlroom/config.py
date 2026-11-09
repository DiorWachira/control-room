"""Load slos.yaml into typed objects."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import yaml

_DUR = re.compile(r"^(\d+(?:\.\d+)?)([smhd])$")
_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_duration(text: str) -> timedelta:
    m = _DUR.match(str(text).strip())
    if not m:
        raise ValueError(f"bad duration {text!r}; use e.g. 5m, 1h, 3d")
    return timedelta(**{_UNIT[m.group(2)]: float(m.group(1))})


def prom_range(td: timedelta) -> str:
    """timedelta -> Prometheus range string (largest whole unit)."""
    secs = int(td.total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs % size == 0:
            return f"{secs // size}{unit}"
    return f"{secs}s"


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    severity: str  # "page" | "ticket"
    long: timedelta
    short: timedelta
    threshold: float


@dataclass(frozen=True)
class SLO:
    id: str
    name: str
    objective: float
    deploy_floor: float = 0.0
    informational: bool = False
    error_query: str = ""
    valid_query: str = ""

    @property
    def budget(self) -> float:
        """Allowed error ratio, e.g. 0.005 for 99.5%."""
        return 1.0 - self.objective


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    callsign: str
    description: str
    slos: tuple[SLO, ...]
    cold_start_window_s: float | None = None
    probe: dict | None = None  # {url, expect_status?, expect_text?, timeout_s?} (probes.yaml)


@dataclass(frozen=True)
class Config:
    window: timedelta
    tiers: tuple[Tier, ...]
    services: tuple[Service, ...] = field(default_factory=tuple)
    probe: dict = field(default_factory=dict)  # runner settings from probes.yaml

    def only(self, ids: set[str]) -> "Config":
        """The same config restricted to some services (the replay covers three)."""
        return Config(self.window, self.tiers, tuple(s for s in self.services if s.id in ids), self.probe)

    def service(self, sid: str) -> Service:
        for s in self.services:
            if s.id == sid:
                return s
        raise KeyError(sid)


def default_path() -> Path:
    env = os.environ.get("CONTROLROOM_SLOS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "slos.yaml"


def probes_path() -> Path:
    env = os.environ.get("CONTROLROOM_PROBES")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "probes.yaml"


def load(path: str | Path | None = None) -> Config:
    raw = yaml.safe_load(Path(path or default_path()).read_text(encoding="utf-8"))
    if "tiers" not in raw:
        # probes.yaml and other watch lists borrow the tiers: thresholds live only in slos.yaml.
        raw["tiers"] = yaml.safe_load(default_path().read_text(encoding="utf-8"))["tiers"]
    tiers = tuple(
        Tier(t["id"], t["name"], t["severity"], parse_duration(t["long"]), parse_duration(t["short"]), float(t["threshold"]))
        for t in raw["tiers"]
    )
    services = []
    for s in raw["services"]:
        slos = tuple(
            SLO(
                id=o["id"], name=o["name"], objective=float(o["objective"]),
                deploy_floor=float(o.get("deploy_floor", 0.0)), informational=bool(o.get("informational", False)),
                error_query=o.get("error_query", "").replace("$service", s["id"]),
                valid_query=o.get("valid_query", "").replace("$service", s["id"]),
            )
            for o in s["slos"]
        )
        for o in slos:
            if not 0 < o.objective < 1:
                raise ValueError(f"{s['id']}/{o.id}: objective must be between 0 and 1")
        services.append(Service(s["id"], s["name"], s["callsign"], s.get("description", ""), slos,
                                s.get("cold_start_window_s"), s.get("probe")))
    return Config(timedelta(days=int(raw.get("window_days", 28))), tiers, tuple(services), raw.get("probe") or {})
