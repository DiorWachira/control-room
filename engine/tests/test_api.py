from fastapi.testclient import TestClient

from controlroom.api import app


def test_api_replay_mode_end_to_end():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["mode"] == "replay"

        st = c.get("/api/status").json()
        lamps = {s["id"]: s["state"] for s in st["services"]}
        assert lamps == {"resolve": "nominal", "repolens": "degraded", "jobbridge": "nominal"}
        assert len(st["services"][0]["days"]) == 91
        assert st["active"][0]["id"] == "RSV-1042"

        rp = c.get("/api/replay").json()
        assert len(rp["frames"]) == 83  # 09:30 to 10:52 EAT, one per minute

        inc = c.get("/api/incidents/RSV-1042").json()
        assert inc["priority"] == "P1" and inc["status"] == "monitoring"
        assert inc["postmortem"]["published"] is False
        assert "to be confirmed" in inc["postmortem"]["root_cause"].lower()
        assert c.get("/api/incidents/RSV-9999").status_code == 404


def test_deploy_gate():
    with TestClient(app) as c:
        blocked = c.get("/budget/repolens").json()
        assert blocked["allow"] is False and "scan-success" in blocked["reason"]
        assert c.get("/budget/repolens", params={"labels": "bug,emergency-fix"}).json()["allow"] is True
        assert c.get("/budget/resolve").json()["allow"] is True
        assert c.get("/budget/nope").status_code == 404
