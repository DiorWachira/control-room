from datetime import timedelta

import pytest

from controlroom.burnrate import COOLING, FIRING, INACTIVE, PENDING, budget_remaining, burn_rate, evaluate_tier, time_to_exhaustion
from controlroom.config import SLO, Tier, parse_duration, prom_range
from controlroom.sources import Profile
from conftest import T0

SLO995 = SLO("s", "s", 0.995)
SLO999 = SLO("s", "s", 0.999)
FAST = Tier("page-1h", "Fast burn", "page", timedelta(hours=1), timedelta(minutes=5), 14.4)


def test_burn_rate_is_error_ratio_over_budget():
    assert burn_rate(0.0745, SLO995) == pytest.approx(14.9)
    assert burn_rate(None, SLO995) is None


def test_14_4x_at_three_nines_empties_a_30_day_budget_in_about_two_days():
    tte = time_to_exhaustion(1.0, 14.4, timedelta(days=30))
    assert tte.total_seconds() / 86400 == pytest.approx(2.083, abs=0.01)


def test_burn_under_1x_never_exhausts_a_rolling_window():
    assert time_to_exhaustion(0.4, 0.9, timedelta(days=28)) is None
    assert time_to_exhaustion(-0.1, 3, timedelta(days=28)) == timedelta(0)


def test_budget_remaining_goes_negative_on_breach():
    assert budget_remaining(0.0005, SLO999) == pytest.approx(0.5)
    assert budget_remaining(0.002, SLO999) == pytest.approx(-1.0)


@pytest.mark.parametrize("long,short,state", [(20, 20, FIRING), (2, 20, PENDING), (20, 2, COOLING), (2, 2, INACTIVE), (14.4, 14.4, FIRING)])
def test_both_windows_must_exceed_the_threshold(long, short, state):
    r = evaluate_tier(FAST, {timedelta(hours=1): long, timedelta(minutes=5): short})
    assert r.state == state


def test_profile_mean_integrates_segments():
    p = Profile(0.01).add(T0, T0 + timedelta(minutes=30), 0.5)
    assert p.mean(T0 + timedelta(minutes=30), timedelta(hours=1)) == pytest.approx((30 * 0.01 + 30 * 0.5) / 60)
    assert p.mean(T0 + timedelta(hours=3), timedelta(hours=1)) == pytest.approx(0.01)


def test_profile_rejects_overlaps():
    p = Profile(0).add(T0, T0 + timedelta(hours=1), 0.1)
    with pytest.raises(ValueError):
        p.add(T0 + timedelta(minutes=30), T0 + timedelta(hours=2), 0.2)


def test_durations_round_trip():
    assert parse_duration("3d") == timedelta(days=3)
    assert prom_range(timedelta(minutes=30)) == "30m"
    assert prom_range(timedelta(hours=6)) == "6h"
    assert prom_range(timedelta(days=28)) == "28d"
