from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from controlroom import config
from controlroom.adapters import MemoryPager, MemorySink
from controlroom.config import SLO, Config, Service
from controlroom.engine import Engine
from controlroom.sources import Profile, ProfileSource

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def cfg() -> Config:
    return config.load(ROOT / "slos.yaml")


def one_service(cfg: Config, objective: float = 0.995, floor: float = 0.0) -> Config:
    svc = Service("svc", "Svc", "TEST", "", (SLO("avail", "Requests succeed", objective, floor),))
    return Config(cfg.window, cfg.tiers, (svc,))


def engine_for(cfg: Config, profile: Profile, objective: float = 0.995, floor: float = 0.0):
    sink, pager = MemorySink(), MemoryPager()
    eng = Engine(one_service(cfg, objective, floor), ProfileSource({("svc", "avail"): profile}), sink, pager)
    return eng, sink, pager


def step(eng: Engine, start: datetime, minutes: int, every: int = 1) -> list[dict]:
    return [eng.evaluate(start + timedelta(minutes=m)) for m in range(0, minutes + 1, every)]
