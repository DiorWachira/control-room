"""Deliver pages exactly once, and read acknowledgements back from Telegram.

Runs after the probe-mode rebuild (GitHub Actions has no long-running process, so no webhook):
1. Poll Telegram getUpdates for presses of the "Acknowledge" button (callback data ack:<id>)
   or messages "/ack <id>", and append them to acks.json. The next rebuild puts them on the
   incident timeline and stops the SLA response clock.
2. For each page incident not yet paged and opened in the last `fresh` window, send the page
   with an Acknowledge button. Older ones (first run on old history) are marked, never sent.
3. When a paged incident resolves, send one "resolved" message.
State lives in notify.json next to the probe log, so a page is never sent twice.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engine import Engine

SITE = os.environ.get("CONTROLROOM_SITE", "https://diorwachira.github.io/control-room/")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=1, sort_keys=True), encoding="utf-8")


class Telegram:
    def __init__(self, token: str, chat: str, client: Any = None):
        import httpx

        self.base = f"https://api.telegram.org/bot{token}"
        self.chat = chat
        self.client = client or httpx.Client(timeout=15.0)

    def send(self, text: str, ack_id: str | None = None) -> bool:
        body: dict = {"chat_id": self.chat, "text": text, "disable_web_page_preview": True}
        if ack_id:
            body["reply_markup"] = {"inline_keyboard": [[{"text": "Acknowledge", "callback_data": f"ack:{ack_id}"}]]}
        try:
            return self.client.post(f"{self.base}/sendMessage", json=body).is_success
        except Exception:  # noqa: BLE001
            return False

    def updates(self, offset: int) -> list[dict]:
        try:
            r = self.client.get(f"{self.base}/getUpdates", params={"offset": offset, "timeout": 0,
                                                                    "allowed_updates": json.dumps(["callback_query", "message"])})
            return r.json().get("result", []) if r.is_success else []
        except Exception:  # noqa: BLE001
            return []

    def answer(self, callback_id: str, text: str) -> None:
        try:
            self.client.post(f"{self.base}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})
        except Exception:  # noqa: BLE001
            pass


def from_env() -> Telegram | None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    return Telegram(token, chat) if token and chat else None


def collect_acks(tg: Telegram, eng: Engine, data_dir: Path, state: dict, now: datetime) -> int:
    acks = _load(data_dir / "acks.json", [])
    known = {a["id"] for a in acks}
    n = 0
    for u in tg.updates(int(state.get("tg_offset", 0))):
        state["tg_offset"] = u["update_id"] + 1
        cb, msg = u.get("callback_query"), u.get("message")
        if cb and str(cb.get("data", "")).startswith("ack:"):
            iid, cid, at = cb["data"][4:], cb["id"], now
        elif msg and str(msg.get("text", "")).startswith("/ack "):
            iid, cid, at = msg["text"][5:].strip(), None, datetime.fromtimestamp(msg["date"], timezone.utc)
        else:
            continue
        inc = eng.incidents.get(iid)
        if inc is not None and iid not in known:
            acks.append({"id": iid, "at": at.isoformat(), "service": inc.service, "slo": inc.slo,
                         "text": "Acknowledged from Telegram."})
            known.add(iid)
            n += 1
        if cid:
            tg.answer(cid, f"{iid} acknowledged" if inc else f"No incident {iid}")
    _save(data_dir / "acks.json", acks)
    return n


def run(eng: Engine, data_dir: str | Path, now: datetime | None = None, tg: Telegram | None = None,
        fresh: timedelta = timedelta(hours=2)) -> dict:
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    tg = tg if tg is not None else from_env()
    state = _load(data_dir / "notify.json", {"paged": {}, "resolved": {}, "tg_offset": 0})
    report = {"paged": [], "resolved": [], "skipped": [], "acks": 0}
    if tg:
        report["acks"] = collect_acks(tg, eng, data_dir, state, now)
    for inc in eng.incidents.incidents:
        if inc.klass != "page":
            continue
        link = f"{SITE}#/incidents/{inc.id}"
        if inc.id not in state["paged"]:
            if now - inc.opened_at > fresh or tg is None:
                state["paged"][inc.id] = None  # history or no pager: record, never send late
                report["skipped"].append(inc.id)
            elif tg.send(f"[{inc.priority}] {inc.title} · {inc.id}\n{link}", ack_id=inc.id):
                state["paged"][inc.id] = now.isoformat()
                report["paged"].append(inc.id)
        if inc.status == "resolved" and state["paged"].get(inc.id) and inc.id not in state["resolved"]:
            if tg and tg.send(f"Resolved: {inc.id} · {inc.title}\nPostmortem draft: {link}"):
                state["resolved"][inc.id] = now.isoformat()
                report["resolved"].append(inc.id)
    _save(data_dir / "notify.json", state)
    return report
