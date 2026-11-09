"""Outbound integrations: the ticket sink (Resolve) and the pager (Telegram / webhook).

The engine only talks to these protocols. MemorySink and MemoryPager back the replay and
the tests; ResolveSink and WebhookPager are the real ones, switched on by env vars.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class TicketSink(Protocol):
    def open(self, title: str, priority: str, body: dict) -> str: ...
    def note(self, ticket_id: str, text: str) -> None: ...
    def set_status(self, ticket_id: str, status: str) -> None: ...


class Pager(Protocol):
    def page(self, text: str) -> bool: ...


@dataclass
class MemorySink:
    next_number: int = 1
    prefix: str = "RSV"
    tickets: dict[str, dict] = field(default_factory=dict)
    reserved: list[int] = field(default_factory=list)  # numbers to hand out first (replay matches Resolve's history)

    def open(self, title: str, priority: str, body: dict) -> str:
        if self.reserved:
            n = self.reserved.pop(0)
        else:
            n, self.next_number = self.next_number, self.next_number + 1
        tid = f"{self.prefix}-{n}"
        self.tickets[tid] = {"title": title, "priority": priority, "body": body, "notes": [], "status": "open"}
        return tid

    def note(self, ticket_id: str, text: str) -> None:
        self.tickets[ticket_id]["notes"].append(text)

    def set_status(self, ticket_id: str, status: str) -> None:
        self.tickets[ticket_id]["status"] = status


@dataclass
class MemoryPager:
    sent: list[str] = field(default_factory=list)

    def page(self, text: str) -> bool:
        self.sent.append(text)
        return True


class ResolveSink:
    """Resolve's incident endpoint. The contract is proposed in docs/resolve-api.md and
    must land in the Resolve repo (service account + scoped token) before this is used.

    Creates carry an Idempotency-Key (service/slo/class/opened_at), so a retry after a
    timeout or a 5xx can never open a second ticket for the same incident.
    """

    def __init__(self, base_url: str, token: str, client: Any = None, attempts: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        import httpx

        self.base = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.attempts, self.sleep = attempts, sleep

    @staticmethod
    def idempotency_key(body: dict) -> str:
        return "/".join(str(body.get(k, "")) for k in ("service", "slo", "class", "opened_at"))

    def _send(self, method: str, path: str, json: dict, headers: dict | None = None):
        import httpx

        last: Exception | None = None
        for n in range(self.attempts):
            try:
                r = self.client.request(method, f"{self.base}{path}", json=json, headers={**self.headers, **(headers or {})})
                if r.status_code < 500:
                    r.raise_for_status()
                    return r
                last = httpx.HTTPStatusError(f"{r.status_code} from Resolve", request=r.request, response=r)
            except httpx.TransportError as e:
                last = e
            if n + 1 < self.attempts:
                self.sleep(2 ** n)  # 1 s, 2 s, 4 s ...
        assert last is not None
        raise last

    def open(self, title: str, priority: str, body: dict) -> str:
        r = self._send("POST", "/api/integrations/control-room/tickets", {"title": title, "priority": priority, **body},
                       {"Idempotency-Key": self.idempotency_key(body)})
        return r.json()["id"]

    def note(self, ticket_id: str, text: str) -> None:
        self._send("POST", f"/api/integrations/control-room/tickets/{ticket_id}/notes", {"text": text, "internal": True})

    def set_status(self, ticket_id: str, status: str) -> None:
        self._send("PATCH", f"/api/integrations/control-room/tickets/{ticket_id}", {"status": status})


class WebhookPager:
    """Telegram Bot API when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set, else a generic JSON webhook.

    Retries with exponential backoff (1 s, 2 s) on network errors, 429 and 5xx. A page that
    still fails returns False, and the incident timeline records "page failed".
    """

    def __init__(self, client: Any = None, attempts: int = 3, sleep: Callable[[float], None] = time.sleep) -> None:
        import httpx

        self.client = client or httpx.Client(timeout=10.0)
        self.tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
        self.webhook = os.environ.get("PAGER_WEBHOOK_URL")
        self.attempts, self.sleep = attempts, sleep

    def _post(self, url: str, payload: dict) -> bool:
        import httpx

        for n in range(self.attempts):
            try:
                r = self.client.post(url, json=payload)
                if r.is_success:
                    return True
                if r.status_code != 429 and r.status_code < 500:
                    return False  # a 4xx other than rate limiting will not fix itself
            except httpx.TransportError:
                pass
            if n + 1 < self.attempts:
                self.sleep(2 ** n)
        return False

    def page(self, text: str) -> bool:
        if self.tg_token and self.tg_chat:
            return self._post(f"https://api.telegram.org/bot{self.tg_token}/sendMessage", {"chat_id": self.tg_chat, "text": text})
        if self.webhook:
            return self._post(self.webhook, {"text": text})
        return False


def from_env() -> tuple[TicketSink, Pager]:
    base, token = os.environ.get("RESOLVE_URL"), os.environ.get("RESOLVE_TOKEN")
    sink: TicketSink = ResolveSink(base, token) if base and token else MemorySink()
    pager: Pager = WebhookPager() if any(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "PAGER_WEBHOOK_URL")) else MemoryPager()
    return sink, pager
