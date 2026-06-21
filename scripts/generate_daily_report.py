#!/usr/bin/env python3
"""Generate a concise daily command report from local records.

The report is boss-readable: core numbers first, then problems and tomorrow's
actions. Drafts are never sent by this module (see docs/04-outreach-sop.md).

Two ways to feed data:
  * ``--sample``        : render the built-in demo payload (offline, no I/O).
  * ``--input PATH``    : load a JSON file of the shape
                          ``{"leads":[...], "outreach_tasks":[...],
                             "conversations":[...]}`` and render from it.

``--feishu`` is a stub: it will raise ``ConfigError`` unless Feishu credentials
are configured, and even then it does NOT silently call the API in this file.
Live wiring (reading Daily Report / Lead Pool tables and writing the report
record) is intentionally deferred to a later milestone (spec §2.A6).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Stdlib only. ``ConfigError`` lives in the project's own config module and is
# imported lazily inside the --feishu stub so this module remains importable
# with zero side effects even when config.py evolves.


def _field(row: Dict[str, Any], *names: str) -> str:
    """Return the first non-empty value among ``names`` (case-insensitive keys
    are NOT normalized on purpose: docs/02 field names are authoritative, but
    we also accept snake_case aliases so external JSON sources work too)."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def compute_metrics(
    leads: Iterable[Dict[str, Any]],
    outreach_tasks: Iterable[Dict[str, Any]],
    conversations: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    lead_rows = list(leads)
    task_rows = list(outreach_tasks)
    conversation_rows = list(conversations)
    return {
        "new_leads": len(lead_rows),
        "a_leads": sum(1 for row in lead_rows if _field(row, "Priority", "priority") == "A"),
        "b_leads": sum(1 for row in lead_rows if _field(row, "Priority", "priority") == "B"),
        "contacts_found": sum(
            1 for row in lead_rows
            if _field(row, "Status", "status") in {"Contact Found", "Assigned", "Contacted"}
        ),
        "outreach_drafts_generated": len(task_rows),
        "messages_sent": sum(1 for row in task_rows if _field(row, "Send Status", "send_status") == "Sent"),
        "replies": sum(1 for row in conversation_rows if _field(row, "Direction", "direction") == "Inbound"),
        "quote_requests": sum(
            1 for row in conversation_rows if _field(row, "Intent", "intent") == "Quote Request"
        ),
        "meetings": sum(1 for row in task_rows if _field(row, "Result", "result") == "Need Meeting"),
        "won_deals": sum(1 for row in task_rows if _field(row, "Result", "result") == "Won"),
        "lost_deals": sum(1 for row in task_rows if _field(row, "Result", "result") == "Lost"),
    }


def render_markdown(metrics: Dict[str, Any], report_date: str, blockers: List[str]) -> str:
    blockers_text = "\n".join("- %s" % item for item in blockers) if blockers else "- No major blocker recorded."
    return """# ASG Lead Command Report - {date}

## Core Numbers

- New leads: {new_leads}
- A leads: {a_leads}
- B leads: {b_leads}
- Contacts found: {contacts_found}
- Outreach drafts generated: {outreach_drafts_generated}
- Messages sent: {messages_sent}
- Replies: {replies}
- Quote requests: {quote_requests}
- Meetings: {meetings}
- Won deals: {won_deals}
- Lost deals: {lost_deals}

## Problems

{blockers}

## Tomorrow Actions

- Review all A priority leads that still have `Pending Review` outreach tasks.
- Follow up quote requests before starting new cold outreach.
- Convert repeated pain signals into Content Opportunity records.
""".format(date=report_date, blockers=blockers_text, **metrics)


def derive_findings(
    leads: Iterable[Dict[str, Any]],
    outreach_tasks: Iterable[Dict[str, Any]],
    conversations: Iterable[Dict[str, Any]],
) -> List[str]:
    """Deterministic, stdlib-only "Main Findings" bullets derived from data.

    No AI is involved — these are simple, auditable heuristics so the report
    always has concrete observations (spec §8.6 acceptance: no empty summary).
    """
    lead_rows = list(leads)
    task_rows = list(outreach_tasks)
    conv_rows = list(conversations)
    findings: List[str] = []

    a_count = sum(1 for row in lead_rows if _field(row, "Priority", "priority") == "A")
    if a_count:
        findings.append("%d A-priority lead(s) need same-day outreach." % a_count)

    pending_review = sum(
        1 for row in task_rows if _field(row, "Approval Status", "approval_status") == "Pending Review"
    )
    if pending_review:
        findings.append("%d outreach draft(s) are still Pending Review." % pending_review)

    quote_count = sum(1 for row in conv_rows if _field(row, "Intent", "intent") == "Quote Request")
    if quote_count:
        findings.append("%d quote request(s) received — high urgency for sales." % quote_count)

    replies = sum(1 for row in conv_rows if _field(row, "Direction", "direction") == "Inbound")
    if replies:
        findings.append("%d inbound reply/ replies recorded in Conversation Log." % replies)

    if not findings:
        findings.append("No notable signals today; pipeline volume is low.")
    return findings


def derive_problems(
    leads: Iterable[Dict[str, Any]],
    outreach_tasks: Iterable[Dict[str, Any]],
) -> List[str]:
    """Deterministic problem bullets (missing contacts, unsent drafts, etc.)."""
    lead_rows = list(leads)
    task_rows = list(outreach_tasks)
    problems: List[str] = []

    a_or_b = [
        row for row in lead_rows
        if _field(row, "Priority", "priority") in {"A", "B"}
    ]
    contactable = [
        row for row in a_or_b
        if any(_field(row, name) for name in ("Email", "LinkedIn URL", "WhatsApp", "Contact Form URL"))
    ]
    missing_contacts = len(a_or_b) - len(contactable)
    if missing_contacts:
        problems.append("%d A/B lead(s) still missing a usable contact." % missing_contacts)

    not_sent_a = sum(
        1 for row in task_rows
        if _field(row, "Send Status", "send_status") == "Not Sent"
        and _field(row, "Approval Status", "approval_status") == "Approved"
    )
    if not_sent_a:
        problems.append("%d approved outreach draft(s) are still Not Sent." % not_sent_a)

    if not problems:
        problems.append("No major blocker recorded.")
    return problems


def sample_payload() -> Dict[str, Any]:
    leads = [
        {"Lead ID": "LEAD-20260621-0001", "Priority": "A", "Status": "Contact Found"},
        {"Lead ID": "LEAD-20260621-0002", "Priority": "B", "Status": "Scored"},
    ]
    tasks = [
        {"Task ID": "TASK-1", "Send Status": "Sent", "Result": "Need Meeting"},
        {"Task ID": "TASK-2", "Send Status": "Not Sent", "Result": "No Response"},
    ]
    conversations = [
        {"Conversation ID": "CONV-1", "Direction": "Inbound", "Intent": "Quote Request"},
    ]
    metrics = compute_metrics(leads, tasks, conversations)
    return {
        "metrics": metrics,
        "markdown": render_markdown(metrics, dt.date.today().isoformat(), ["Need more verified contacts."]),
    }


def load_input_payload(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read ``--input PATH`` JSON and normalize keys.

    Accepts either the canonical keys (``leads`` / ``outreach_tasks`` /
    ``conversations``) or a few common aliases so callers can pass slightly
    different exports without crashing. Missing keys default to empty lists.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError("input file not found: %s" % path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("input file is not valid JSON: %s" % exc) from exc
    if not isinstance(raw, dict):
        raise ValueError("input JSON must be an object with leads/outreach_tasks/conversations")

    def _pick(*names: str) -> List[Dict[str, Any]]:
        for name in names:
            value = raw.get(name)
            if value is None:
                continue
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            raise ValueError("'%s' must be a list of objects" % name)
        return []

    return {
        "leads": _pick("leads", "Lead Pool"),
        "outreach_tasks": _pick("outreach_tasks", "tasks", "Outreach Task"),
        "conversations": _pick("conversations", "Conversation Log"),
    }


def render_from_payload(payload: Dict[str, List[Dict[str, Any]]], report_date: str) -> str:
    """Compute metrics + sections from a payload dict and return markdown.

    Uses the derived Main Findings / Problems so reports built from real
    ``--input`` data stay concrete even without AI.
    """
    leads = payload.get("leads", [])
    tasks = payload.get("outreach_tasks", [])
    conversations = payload.get("conversations", [])
    metrics = compute_metrics(leads, tasks, conversations)
    problems = derive_problems(leads, tasks)
    findings = derive_findings(leads, tasks, conversations)

    blockers_text = "\n".join("- %s" % item for item in problems)
    findings_text = "\n".join("- %s" % item for item in findings)

    core_lines = "\n".join(
        "- %s: %s" % (label, metrics[key])
        for label, key in (
            ("New leads", "new_leads"),
            ("A leads", "a_leads"),
            ("B leads", "b_leads"),
            ("Contacts found", "contacts_found"),
            ("Outreach drafts generated", "outreach_drafts_generated"),
            ("Messages sent", "messages_sent"),
            ("Replies", "replies"),
            ("Quote requests", "quote_requests"),
            ("Meetings", "meetings"),
            ("Won deals", "won_deals"),
            ("Lost deals", "lost_deals"),
        )
    )

    return """# ASG Lead Command Report - {date}

## Core Numbers

{core}

## Main Findings

{findings}

## Problems

{problems}

## Tomorrow Actions

- Review all A priority leads that still have `Pending Review` outreach tasks.
- Follow up quote requests before starting new cold outreach.
- Convert repeated pain signals into Content Opportunity records.
""".format(date=report_date, core=core_lines, findings=findings_text, problems=blockers_text)


def _require_feishu_credentials_or_raise() -> None:
    """``--feishu`` stub (spec §2.A6).

    If Feishu credentials are not configured, raise ``ConfigError`` with a
    clear message. Even when credentials ARE present this stub does NOT make
    any network call — live write-back of the Daily Report record is deferred
    to a later milestone. We simply refuse to proceed so the user never gets a
    silently-no-op or a half-wired API call.
    """
    try:
        from .config import ConfigError, RuntimeConfig  # type: ignore
    except ImportError:
        from config import ConfigError, RuntimeConfig  # type: ignore

    runtime = RuntimeConfig.from_env()
    configured = bool(runtime.feishu_app_id) and bool(runtime.feishu_app_secret)
    if not configured:
        raise ConfigError("Feishu wiring requires credentials")
    # Credentials exist, but the actual table read/write is intentionally not
    # implemented in this stub. Surface a clear error rather than pretending.
    raise ConfigError(
        "Feishu wiring requires credentials and live table mapping "
        "(not yet implemented in this stub)"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily command report")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sample", action="store_true", help="render the built-in demo payload")
    source.add_argument("--input", metavar="PATH", help="load JSON {leads,outreach_tasks,conversations}")
    parser.add_argument(
        "--feishu",
        action="store_true",
        help="(stub) attempt to write the report to Feishu; raises ConfigError without credentials",
    )
    parser.add_argument(
        "--date",
        default="",
        help="report date in YYYY-MM-DD (defaults to today, local time)",
    )
    args = parser.parse_args(argv)

    if args.feishu:
        # Explicitly refuse to silently call the API. This raises before any
        # report rendering so the failure is loud and unambiguous.
        _require_feishu_credentials_or_raise()
        return 0  # pragma: no cover - _require always raises currently

    report_date = args.date or dt.date.today().isoformat()

    if args.sample:
        payload = sample_payload()
        # Keep the legacy single-section sample output stable for existing
        # consumers (n8n workflow 06 calls `--sample`).
        print(payload["markdown"])
        return 0

    # --input PATH
    data = load_input_payload(args.input)
    print(render_from_payload(data, report_date))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 - CLI boundary, must print cleanly
        # Re-raise ConfigError with its exact message so callers can detect it.
        name = exc.__class__.__name__
        print("error: %s: %s" % (name, exc), file=sys.stderr)
        raise SystemExit(1)
