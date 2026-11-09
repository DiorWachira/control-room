"""The maths. Pure functions, no I/O.

burn rate   = error ratio / (1 - objective)
remaining   = 1 - (error ratio over the SLO window / (1 - objective))
tier fires  = long-window burn >= threshold AND short-window burn >= threshold
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .config import SLO, Tier

INACTIVE, PENDING, COOLING, FIRING = "inactive", "pending", "cooling", "firing"


def burn_rate(error_ratio: float | None, slo: SLO) -> float | None:
    if error_ratio is None:
        return None
    return error_ratio / slo.budget


def budget_remaining(window_error_ratio: float | None, slo: SLO) -> float | None:
    """Fraction of the error budget left. Goes negative once the SLO is breached."""
    if window_error_ratio is None:
        return None
    return 1.0 - window_error_ratio / slo.budget


def time_to_exhaustion(remaining: float | None, burn: float | None, window: timedelta) -> timedelta | None:
    """How long the remaining budget lasts if the current burn holds.

    A rolling window forgets old errors, so a steady burn below 1x settles at
    (1 - burn) remaining and never runs out: that returns None.
    """
    if remaining is None or burn is None or burn < 1.0:
        return None
    if remaining <= 0:
        return timedelta(0)
    return window * (remaining / burn)


@dataclass(frozen=True)
class TierReading:
    tier: Tier
    long_rate: float | None
    short_rate: float | None

    @property
    def long_over(self) -> bool:
        return self.long_rate is not None and self.long_rate >= self.tier.threshold

    @property
    def short_over(self) -> bool:
        return self.short_rate is not None and self.short_rate >= self.tier.threshold

    @property
    def state(self) -> str:
        """firing: both windows over. pending: only the short window (a spike that may be a blip).
        cooling: only the long window (the burn has stopped; the short window resets the alert)."""
        if self.long_over and self.short_over:
            return FIRING
        if self.short_over:
            return PENDING
        if self.long_over:
            return COOLING
        return INACTIVE


def evaluate_tier(tier: Tier, rates: dict[timedelta, float | None]) -> TierReading:
    return TierReading(tier, rates.get(tier.long), rates.get(tier.short))
