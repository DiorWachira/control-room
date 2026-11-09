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


# ---- LLM pass (M5) ----------------------------------------------------------------------
MODEL = "claude-opus-5-5"
_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two or three plain sentences: what broke, for how long, what it cost."},
        "probable_cause": {"type": "string", "description": "The most likely root cause, stated as a hypothesis."},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "Timeline facts that support the hypothesis."},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "description": "Concrete action items, at most four."},
    },
    "required": ["summary", "probable_cause", "evidence", "follow_ups"],
    "additionalProperties": False,
}
_SYSTEM = ("You help a solo developer write blameless incident postmortems for their own small web apps. "
           "You get a deterministic draft and the incident timeline. Rewrite the summary in plain words and propose "
           "the most likely root cause using only facts in the timeline. Never invent causes the timeline does not "
           "support; when evidence is thin, say what to check. The result is a draft a human will confirm.")


def refine(draft_: dict, inc: Incident, client=None) -> dict | None:
    """Ask Claude to rewrite the summary and propose a root cause. Returns None (keep the
    deterministic draft) when the SDK or key is missing, or on any API error or refusal.
    Needs `pip install -e ".[llm]"` and ANTHROPIC_API_KEY."""
    import json
    import os

    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic
        except ImportError:
            return None
        client = anthropic.Anthropic(max_retries=2, timeout=120.0)
    prompt = (f"Incident {inc.id} · {inc.title} · {inc.priority} · status {inc.status}\n\n"
              f"Deterministic draft:\n{draft_['markdown']}\n\n"
              "Return the rewrite as JSON matching the schema. Times are EAT.")
    try:
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=4000, system=_SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:  # noqa: BLE001 - any API failure leaves the deterministic draft in place
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        out = json.loads(text) if text else None
    except ValueError:
        return None
    if not out:
        return None
    return out | {"model": resp.model, "published": False, "label": "AI rewrite · to be confirmed"}
