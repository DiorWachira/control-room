"""The spec's acceptance criteria, against synthetic time series."""
from datetime import timedelta

from controlroom import scenario
from controlroom.probes import COLD_START, ERROR, SUCCESS, classify
from controlroom.sources import Profile
from conftest import T0, engine_for, step

H = timedelta(hours=1)
M = timedelta(minutes=1)


def page_events(eng):
    return [e for i in eng.incidents.incidents for e in i.timeline if e.kind == "page"]


def test_two_minute_blip_does_not_page(cfg):
    # 100% of requests fail for two minutes on a 99.5% SLO.
    prof = Profile(0.001).add(T0 + 3 * H, T0 + 3 * H + 2 * M, 1.0)
    eng, sink, pager = engine_for(cfg, prof)
    frames = step(eng, T0, 6 * 60)
    assert pager.sent == [] and sink.tickets == {}
    fast = [f["services"][0]["slos"][0]["tiers"][0]["state"] for f in frames]
    assert "pending" in fast  # the short window saw it...
    assert "firing" not in fast  # ...but the hour never agreed


def test_sustained_5xx_spike_pages_within_the_detection_window(cfg):
    start = T0 + 2 * H
    prof = Profile(0.001).add(start, start + 5 * H, 0.20)
    eng, sink, pager = engine_for(cfg, prof)
    step(eng, T0, 5 * 60)
    assert len(eng.incidents.incidents) == 1
    inc = eng.incidents.incidents[0]
    detect = (inc.opened_at - start).total_seconds() / 60
    # 1h window reaches 14.4 x 0.5% = 7.2% average after ~21.4 minutes at 20% errors.
    assert 20 <= detect <= 23
    assert inc.priority == "P1"
    assert len(sink.tickets) == 1 and len(pager.sent) == 1  # still one ticket three hours later


def test_one_ticket_resolves_when_the_burn_stops(cfg):
    start, stop = T0 + 2 * H, T0 + 2 * H + 40 * M
    prof = Profile(0.001).add(start, stop, 0.20)
    eng, sink, _ = engine_for(cfg, prof)
    step(eng, T0, 6 * 60)
    inc = eng.incidents.incidents[0]
    reset = next(e for e in inc.timeline if "resets" in e.text)
    assert (reset.at - stop) <= 5 * M  # the short window gives a fast reset
    assert inc.status == "resolved"
    assert inc.resolved_at - reset.at == timedelta(minutes=60)
    assert len(sink.tickets) == 1
    assert list(sink.tickets.values())[0]["status"] == "resolved"


def test_slow_leak_opens_a_ticket_not_a_page(cfg):
    prof = Profile(0.001).add(T0 + 3 * 24 * H, T0 + 10 * 24 * H, 0.015)  # 3x burn, steady
    eng, sink, pager = engine_for(cfg, prof)
    step(eng, T0 + 3 * 24 * H, 30 * 60, every=5)
    assert pager.sent == []
    assert len(eng.incidents.incidents) == 1
    inc = eng.incidents.incidents[0]
    assert inc.klass == "ticket" and inc.priority == "P3"
    hours = (inc.opened_at - (T0 + 3 * 24 * H)).total_seconds() / 3600
    assert 19 <= hours <= 22


def test_deploy_gate_arms_under_the_floor(cfg):
    prof = Profile(0.001).add(T0 + H, T0 + 3 * H, 0.5)
    eng, _, _ = engine_for(cfg, prof, floor=0.7)  # starts at 80% left
    frames = step(eng, T0, 4 * 60, every=5)
    armed = [f["services"][0]["slos"][0]["gate"]["armed"] for f in frames]
    assert armed[0] is False and armed[-1] is True


def test_replay_of_8_november(cfg):
    eng, frames = scenario.run(cfg, until=scenario.eat(2026, 11, 8, 11, 45))
    inc = eng.incidents.get("RSV-1042")
    assert inc is not None and inc.service == "repolens"
    assert inc.opened_at == scenario.eat(2026, 11, 8, 9, 52)
    assert len(page_events(eng)) == 1
    texts = [e.text for e in inc.timeline]
    assert any(t.startswith("Deploy gate armed") for t in texts)
    assert any("no second ticket" in t for t in texts)
    reset = next(e for e in inc.timeline if "Fast burn resets" in e.text)
    assert reset.at == scenario.eat(2026, 11, 8, 10, 16)
    assert inc.acked_at == scenario.eat(2026, 11, 8, 9, 58, 12)
    # Monitoring starts when the slow tier also clears (10:40); 60 quiet minutes later it closes.
    assert inc.status == "resolved" and inc.resolved_at == scenario.eat(2026, 11, 8, 11, 40)
    assert eng.incidents.get("RSV-1039").service == "jobbridge"


def test_probe_classification_is_honest_about_cold_starts():
    assert classify(True, 0.8) == SUCCESS
    assert classify(True, 34, wake_window_s=50, was_idle=True) == COLD_START
    assert classify(True, 34, wake_window_s=50, was_idle=False) == ERROR
    assert classify(True, 61, wake_window_s=50, was_idle=True) == ERROR
    assert classify(False, 0.2) == ERROR
