"""Outbound adapters against fake servers (httpx.MockTransport): no network, real HTTP shapes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from controlroom.adapters import ResolveSink, WebhookPager
from controlroom.config import SLO
from controlroom.sources import PrometheusSource

FIX = Path(__file__).parent / "fixtures"
AT = datetime(2026, 11, 8, 7, 52, tzinfo=timezone.utc)
SLO_ = SLO("scan-success", "Scans finish", 0.995, 0.45,
           error_query='sum(increase(probe_runs_total{service="repolens",outcome="error"}[$window]))',
           valid_query='sum(increase(probe_runs_total{service="repolens",outcome!="cold_start"}[$window]))')


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def prom(handler) -> PrometheusSource:
    return PrometheusSource("http://prom:9090/", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_prometheus_source_parses_recorded_responses():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params["query"]
        seen.append((req.url.path, q, float(req.url.params["time"])))
        return httpx.Response(200, json=fixture("prom_vector.json" if 'outcome="error"' in q else "prom_valid.json"))

    ratio = prom(handler).error_ratio("repolens", SLO_, AT, timedelta(hours=1))
    assert ratio == pytest.approx(412 / 20600)
    assert all(path == "/api/v1/query" for path, _, _ in seen)
    assert all("[1h]" in q and "$window" not in q for _, q, _ in seen)
    assert seen[0][2] == AT.timestamp()


def test_prometheus_source_no_data_is_none_not_zero():
    src = prom(lambda req: httpx.Response(200, json=fixture("prom_empty.json")))
    assert src.error_ratio("repolens", SLO_, AT, timedelta(minutes=5)) is None


def test_prometheus_source_nan_and_scalar():
    nan = {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "NaN"]}]}}
    assert prom(lambda r: httpx.Response(200, json=nan)).query("x", AT) is None
    scalar = {"status": "success", "data": {"resultType": "scalar", "result": [1, "0.25"]}}
    assert prom(lambda r: httpx.Response(200, json=scalar)).query("x", AT) == 0.25


def test_prometheus_source_surfaces_query_errors():
    src = prom(lambda req: httpx.Response(200, json=fixture("prom_error.json")))
    with pytest.raises(RuntimeError, match="bad_data"):
        src.query("sum(", AT)


BODY = {"service": "repolens", "slo": "scan-success", "class": "page", "tier": "page-1h",
        "opened_at": AT.isoformat(), "context": {"remaining": 0.457}}


def resolve(handler, **kw) -> tuple[ResolveSink, list[float]]:
    slept: list[float] = []
    sink = ResolveSink("https://resolve.test/", "tok", client=httpx.Client(transport=httpx.MockTransport(handler)),
                       sleep=slept.append, **kw)
    return sink, slept


def test_resolve_create_is_idempotent_across_retries():
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=req)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(201, json={"id": "RSV-1042"})

    sink, slept = resolve(handler)
    assert sink.open("RepoLens burning", "P1", BODY) == "RSV-1042"
    keys = {r.headers["Idempotency-Key"] for r in calls}
    assert keys == {f"repolens/scan-success/page/{AT.isoformat()}"}
    assert all(r.headers["Authorization"] == "Bearer tok" for r in calls)
    assert json.loads(calls[-1].content)["priority"] == "P1"
    assert slept == [1, 2]


def test_resolve_does_not_retry_client_errors():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(403, json={"detail": "token scope"})

    sink, slept = resolve(handler)
    with pytest.raises(httpx.HTTPStatusError):
        sink.note("RSV-1042", "hello")
    assert len(calls) == 1 and slept == []


def test_resolve_gives_up_after_attempts():
    sink, slept = resolve(lambda req: httpx.Response(502), attempts=3)
    with pytest.raises(httpx.HTTPStatusError):
        sink.set_status("RSV-1042", "resolved")
    assert slept == [1, 2]


def test_pager_retries_rate_limits_then_delivers(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    slept: list[float] = []
    pager = WebhookPager(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=slept.append)
    assert pager.page("[P1] RepoLens · RSV-1042") is True
    assert calls[0].url.path == "/bot123:abc/sendMessage"
    assert json.loads(calls[0].content) == {"chat_id": "42", "text": "[P1] RepoLens · RSV-1042"}
    assert slept == [1, 2]


def test_pager_fails_fast_on_bad_request_and_reports_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("PAGER_WEBHOOK_URL", "https://hooks.test/page")
    calls = []
    pager = WebhookPager(client=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(400))),
                         sleep=lambda s: None)
    assert pager.page("x") is False and len(calls) == 1
