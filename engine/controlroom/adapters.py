"""Outbound integrations: the ticket sink (Resolve) and the pager (Telegram / webhook).

The engine only talks to these protocols. MemorySink and MemoryPager back the replay and
the tests; ResolveSink and WebhookPager are the real ones, switched on by env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


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
    must land in the Resolve repo (service account + scoped token) before this is used."""

    def __init__(self, base_url: str, token: str):
        import httpx

        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=10.0, headers={"Authorization": f"Bearer {token}"})

    def open(self, title: str, priority: str, body: dict) -> str:
        r = self.client.post(f"{self.base}/api/integrations/control-room/tickets", json={"title": title, "priority": priority, **body})
        r.raise_for_status()
        return r.json()["id"]

    def note(self, ticket_id: str, text: str) -> None:
        self.client.post(f"{self.base}/api/integrations/control-room/tickets/{ticket_id}/notes", json={"text": text, "internal": True}).raise_for_status()

    def set_status(self, ticket_id: str, status: str) -> None:
        self.client.patch(f"{self.base}/api/integrations/control-room/tickets/{ticket_id}", json={"status": status}).raise_for_status()


class WebhookPager:
    """Telegram Bot API when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set, else a generic JSON webhook."""

    def __init__(self) -> None:
        import httpx

        self.client = httpx.Client(timeout=10.0)
        self.tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
        self.webhook = os.environ.get("PAGER_WEBHOOK_URL")

    def page(self, text: str) -> bool:
        if self.tg_token and self.tg_chat:
            r = self.client.post(f"https://api.telegram.org/bot{self.tg_token}/sendMessage", json={"chat_id": self.tg_chat, "text": text})
            return r.is_success
        if self.webhook:
            return self.client.post(self.webhook, json={"text": text}).is_success
        return False


def from_env() -> tuple[TicketSink, Pager]:
    base, token = os.environ.get("RESOLVE_URL"), os.environ.get("RESOLVE_TOKEN")
    sink: TicketSink = ResolveSink(base, token) if base and token else MemorySink()
    pager: Pager = WebhookPager() if any(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "PAGER_WEBHOOK_URL")) else MemoryPager()
    return sink, pager
