"""Probe mode end to end: probe log, runner, rebuild, notifications, acks, persistence, drill."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from controlroom import config as config_mod
from controlroom import drill, live, notify, postmortem
from controlroom.adapters import MemoryPager, MemorySink
from controlroom.config import SLO, Config, Service
from controlroom.engine import Engine
from controlroom.probelog import ProbeLogSource, ProbeRecord, append, day_strip, prune, read_log
from controlroom.probe_runner import run_round
from controlroom.probes import ProbeResult
from controlroom.sources import Profile, ProfileSource
from controlroom.store import Store

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
RUN = timedelta(minutes=15)


def watch(cfg) -> Config:
    svc = Service("app", "App", "APP", "", (SLO("site-up", "Site answers", 0.98, 0.25),), 50, {"url": "https://app.test/"})
    return Config(cfg.window, cfg.tiers, (svc,), {"attempts": 2, "attempt_gap_s": 10, "lookback": "30m", "idle_after": "15m"})


def history(tmp_path, bad: set[int], runs: int, start=T0) -> None:
    recs = []
    for i in range(runs):
        for n in (1, 2):
            recs.append(ProbeRecord(start + RUN * i + timedelta(seconds=10 * (n - 1)), "app", n,
                                    "error" if i in bad else "success", 0.4, "HTTP 503" if i in bad else "HTTP 200"))
    append(tmp_path / "runs", recs)


def test_probes_yaml_loads_with_tiers_from_slos(cfg):
    w = config_mod.load(config_mod.probes_path())
    assert {s.id for s in w.services} >= {"resolve", "repolens", "seedmind", "metamorph", "context-profiler"}
    assert w.tiers == cfg.tiers  # thresholds only live in slos.yaml
    assert all(s.probe and s.probe["url"].startswith("https://") for s in w.services)
    assert 'service="repolens"' in w.service("repolens").slos[0].valid_query


def test_log_roundtrip_prune_and_window_semantics(tmp_path):
    history(tmp_path, {200}, 4 * 96)  # four days, one bad run
    recs = read_log(tmp_path / "runs")
    assert len(recs) == 4 * 96 * 2 and recs == sorted(recs, key=lambda r: r.at)
    src = ProbeLogSource(recs)
    slo = SLO("site-up", "x", 0.98)
    at_bad = T0 + RUN * 200 + timedelta(minutes=1)
    assert src.error_ratio("app", slo, at_bad, timedelta(minutes=5)) == pytest.approx(2 / 4)  # 5m reads the last 30m
    assert src.error_ratio("app", slo, T0 + timedelta(minutes=20), timedelta(hours=1)) is None  # warming up
    assert src.error_ratio("nope", slo, at_bad, timedelta(hours=1)) is None
    (tmp_path / "runs" / "2026-01-01.jsonl").write_text("{}\n")
    assert [f.name for f in prune(tmp_path / "runs", T0.date(), keep_days=100)] == ["2026-01-01.jsonl"]


def test_runner_marks_cold_starts_only_after_idle(cfg, tmp_path):
    w = watch(cfg)
    calls = []

    def prober(service, journey, url, **kw):
        calls.append(kw["was_idle"])
        slow = kw["was_idle"]  # first request after idle is slow (34 s wake)
        from controlroom.probes import classify
        return ProbeResult(service, journey, classify(True, 34.0 if slow else 0.3, slow_threshold_s=10, wake_window_s=50, was_idle=kw["was_idle"]), 34.0 if slow else 0.3)

    first = run_round(w, tmp_path / "runs", prober, now=T0, sleep=lambda s: None)
    assert [r.outcome for r in first] == ["cold_start", "success"] and calls == [True, False]
    calls.clear()
    second = run_round(w, tmp_path / "runs", prober, now=datetime.now(timezone.utc), sleep=lambda s: None)
    assert calls[0] is (datetime.now(timezone.utc) - first[-1].at > timedelta(minutes=15))
    assert len(read_log(tmp_path / "runs")) == 4 and len(second) == 2


def test_rebuild_pages_once_with_stable_id_and_day_strip(cfg, tmp_path):
    w = watch(cfg)
    history(tmp_path, set(range(200, 205)), 2 * 96 + 30)  # 75-minute outage on day 3
    now = T0 + RUN * (2 * 96 + 30)
    eng, src = live.build(w, tmp_path, now)
    pages = [i for i in eng.incidents.incidents if i.klass == "page"]
    assert len(pages) == 1 and pages[0].id.startswith("CR-APP-") and pages[0].status == "resolved"
    assert [i.id for i in live.build(w, tmp_path, now)[0].incidents.incidents] == [i.id for i in eng.incidents.incidents]
    strip = day_strip(w, src, "app", now, {pages[0].opened_at.astimezone(timezone(timedelta(hours=3))).date()})
    assert strip[0]["status"] == "nodata" and "outage" in {d["status"] for d in strip}
    page_events = [e for e in pages[0].timeline if e.kind == "page"]
    assert page_events and "could not be delivered" in page_events[0].text  # honest: no pager configured


class FakeTelegram:
    def __init__(self, updates=()):
        self.sent, self._updates, self.answered = [], list(updates), []

    def send(self, text, ack_id=None):
        self.sent.append((text, ack_id))
        return True

    def updates(self, offset):
        out, self._updates = [u for u in self._updates if u["update_id"] >= offset], []
        return out

    def answer(self, cid, text):
        self.answered.append(text)


def test_notify_pages_once_resolves_once_and_records_acks(cfg, tmp_path):
    w = watch(cfg)
    history(tmp_path, set(range(190, 195)), 2 * 96 + 5)
    now = T0 + RUN * (2 * 96 + 5)
    eng, _ = live.build(w, tmp_path, now)
    inc = next(i for i in eng.incidents.incidents if i.klass == "page")
    tg = FakeTelegram()
    rep = notify.run(eng, tmp_path, now, tg)
    assert rep["paged"] == [inc.id] and tg.sent[0][1] == inc.id and "#/incidents/" + inc.id in tg.sent[0][0]
    assert notify.run(eng, tmp_path, now, tg)["paged"] == []  # never twice

    tg2 = FakeTelegram([{"update_id": 7, "callback_query": {"id": "cb1", "data": f"ack:{inc.id}"}}])
    assert notify.run(eng, tmp_path, now, tg2)["acks"] == 1 and tg2.answered == [f"{inc.id} acknowledged"]
    eng2, _ = live.build(w, tmp_path, now)
    inc2 = eng2.incidents.get(inc.id)
    assert inc2.acked_at is not None and any(e.kind == "ack" for e in inc2.timeline)

    history(tmp_path, set(), 40, start=now + RUN)  # recovery, 10 quiet hours
    later = now + RUN * 41
    eng3, _ = live.build(w, tmp_path, later)
    assert eng3.incidents.get(inc.id).status == "resolved"
    tg3 = FakeTelegram()
    assert notify.run(eng3, tmp_path, later, tg3)["resolved"] == [inc.id]
    assert notify.run(eng3, tmp_path, later, tg3)["resolved"] == []
    assert json.loads((tmp_path / "notify.json").read_text())["tg_offset"] == 8


def test_old_incidents_are_never_paged_late(cfg, tmp_path):
    w = watch(cfg)
    history(tmp_path, set(range(190, 195)), 2 * 96 + 40)
    now = T0 + RUN * (2 * 96 + 40)  # outage ended ~9 hours ago
    eng, _ = live.build(w, tmp_path, now)
    tg = FakeTelegram()
    rep = notify.run(eng, tmp_path, now, tg)
    assert rep["paged"] == [] and len(rep["skipped"]) == 1 and tg.sent == []


def test_telegram_client_shapes():
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [{"update_id": 1}]})
        return httpx.Response(200, json={"ok": True})

    tg = notify.Telegram("123:abc", "42", httpx.Client(transport=httpx.MockTransport(handler)))
    assert tg.send("hi", ack_id="CR-X") is True
    body = json.loads(seen[0].content)
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "ack:CR-X"
    assert tg.updates(5) == [{"update_id": 1}] and seen[1].url.params["offset"] == "5"


def test_store_restart_mid_fire_never_reopens_a_ticket(cfg, tmp_path):
    svc = Service("svc", "Svc", "S", "", (SLO("avail", "Requests succeed", 0.995),))
    one = Config(cfg.window, cfg.tiers, (svc,))
    prof = Profile(0.0).add(T0 + timedelta(days=2), T0 + timedelta(days=3), 0.3)
    src = ProfileSource({("svc", "avail"): prof})
    db = Store(tmp_path / "state.db")
    sink = MemorySink()
    eng = Engine(one, src, sink, MemoryPager())
    t = T0 + timedelta(days=2)
    for m in range(0, 40, 5):
        eng.evaluate(t + timedelta(minutes=m))
        db.save(eng)
    assert len(sink.tickets) == 1
    # restart: a fresh process, same database
    sink2, pager2 = MemorySink(next_number=99), MemoryPager()
    eng2 = Engine(one, src, sink2, pager2)
    assert db.load(eng2) is True
    assert eng2.sink.next_number == sink.next_number and len(eng2.incidents.incidents) == 1
    for m in range(40, 120, 5):
        eng2.evaluate(t + timedelta(minutes=m))
    assert sink2.tickets == {} and pager2.sent == []  # still the same incident, nothing re-sent
    assert eng2.incidents.incidents[0].timeline[0].at == eng.incidents.incidents[0].timeline[0].at


def test_postmortem_refine_uses_structured_output_and_falls_back(cfg, tmp_path):
    w = watch(cfg)
    history(tmp_path, set(range(200, 205)), 2 * 96 + 30)
    eng, _ = live.build(w, tmp_path, T0 + RUN * (2 * 96 + 30))
    inc = next(i for i in eng.incidents.incidents if i.klass == "page")
    d = postmortem.draft(inc, "App", "Site answers", 0.5)
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(stop_reason="end_turn", model=kw["model"], content=[SimpleNamespace(type="text", text=json.dumps(
                {"summary": "App was down 75 minutes.", "probable_cause": "Check the host.", "evidence": ["5 failed runs"], "follow_ups": ["Add a health route"]}))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=Msgs()))
    out = postmortem.refine(d, inc, client)
    assert out["summary"].startswith("App was down") and out["published"] is False and out["model"] == "claude-opus-5-5"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema" and calls[0]["fallbacks"] == "default"

    class Refuses:
        def create(self, **kw):
            return SimpleNamespace(stop_reason="refusal", model=kw["model"], content=[])

    assert postmortem.refine(d, inc, SimpleNamespace(beta=SimpleNamespace(messages=Refuses()))) is None
    monkeypatch_key = __import__("os").environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert postmortem.refine(d, inc) is None  # without a key it is a no-op, never an error
    finally:
        if monkeypatch_key:
            __import__("os").environ["ANTHROPIC_API_KEY"] = monkeypatch_key


def test_chaos_drill_passes():
    checks = drill.run(verbose=False)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_api_in_probe_mode(monkeypatch, cfg, tmp_path):
    w = config_mod.load(config_mod.probes_path())
    now = datetime.now(timezone.utc)
    recs = [ProbeRecord(now - timedelta(days=2) + RUN * i, s.id, 1, "success", 0.3) for i in range(2 * 96) for s in w.services]
    recs += [ProbeRecord(now - timedelta(hours=3) + RUN * i, "seedmind", 1, "error", 0.3, "HTTP 503") for i in range(1)]
    append(tmp_path / "runs", recs)
    monkeypatch.setenv("CONTROLROOM_PROBE_DATA", str(tmp_path))
    from fastapi.testclient import TestClient

    from controlroom.api import app

    with TestClient(app) as c:
        assert c.get("/api/health").json()["mode"] == "probes"
        st = c.get("/api/status").json()
        assert st["mode"] == "probes" and len(st["services"]) == len(w.services)
        assert all(s["state"] == "nominal" for s in st["services"])  # newest probe 15 min old: signal ok
        assert st["services"][0]["days"][0]["status"] == "nodata" and st["services"][0]["days"][-1]["status"] != "nodata"
        # the replay is still served for the budget wall and RSV-1042
        assert len(c.get("/api/replay").json()["frames"]) == 83
        assert c.get("/api/incidents/RSV-1042").json()["replay"] is True
        assert c.get("/budget/seedmind").json()["allow"] is True
