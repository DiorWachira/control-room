"""Blameless postmortem draft, assembled from the incident timeline.

This deterministic draft is the fallback and the scaffold. Milestone 5 adds an LLM pass that
rewrites the summary and proposes a root cause; the output is always a draft for Dior to
edit and is never published automatically.
"""
from __future__ import annotations

from datetime import timedelta, timezone

from .incidents import Incident, fmt_rate

EAT = timezone(timedelta(hours=3))


def _t(dt) -> str:
    return dt.astimezone(EAT).strftime("%H:%M")


def draft(inc: Incident, service_name: str, slo_name: str, remaining_now: float | None) -> dict:
    first = inc.timeline[0].at if inc.timeline else inc.opened_at
    resets = [e for e in inc.timeline if "resets" in e.text]
    last_reset = resets[-1].at if resets else None
    burn = inc.context.get("burn", {})
    ratio = inc.context.get("error_ratio", {})
    rem_fire = inc.context.get("remaining")
    notes = [e for e in inc.timeline if e.kind in ("note", "change")]

    duration = f"{int((last_reset - first).total_seconds() // 60)} minutes" if last_reset else "an ongoing period"
    summary = (f"{service_name} burned its “{slo_name}” error budget at {fmt_rate(burn.get('1h'))} over the hour "
               f"({fmt_rate(burn.get('5m'))} on the 5-minute window) when the page fired at {_t(inc.opened_at)} EAT. "
               f"The burn lasted about {duration} from the first failed probe to the alert reset.")
    spent = (rem_fire - remaining_now) if (rem_fire is not None and remaining_now is not None) else None
    impact = (f"Error ratio peaked at {ratio.get('5m', 0):.1%} over 5 minutes. "
              + (f"{max(spent, 0):.1%} of the 28-day budget was spent after the page; " if spent is not None else "")
              + (f"{remaining_now:.1%} remains." if remaining_now is not None else ""))
    gate = [e for e in inc.timeline if e.source == "Gate"]
    if gate:
        impact += " " + gate[0].text.split(":")[0] + "."
    root = "To be confirmed. Notes captured during the incident: " + (" ".join(f"({_t(n.at)}) {n.text}" for n in notes) or "none.")
    timeline = [f"{_t(e.at)} · {e.source} · {e.text}" for e in inc.timeline]
    actions = [
        {"text": "Confirm the root cause and replace the placeholder above", "done": False},
        {"text": "Add a chaos drill that reproduces this failure in staging and checks the page fires and resets", "done": False},
    ] + [{"text": f"Keep: {n.text}", "done": True} for n in notes if n.kind == "change"]

    md = [f"# Postmortem draft · {inc.id}", "", f"**{inc.title}** · {inc.priority} · status {inc.status}", "",
          "## Summary", summary, "", "## Impact", impact, "", "## Timeline (EAT)", *[f"- {line}" for line in timeline], "",
          "## Root cause (to be confirmed)", root, "", "## Action items",
          *[f"- [{'x' if a['done'] else ' '}] {a['text']}" for a in actions], ""]
    return {"summary": summary, "impact": impact, "root_cause": root, "timeline": timeline, "action_items": actions,
            "markdown": "\n".join(md), "published": False}
