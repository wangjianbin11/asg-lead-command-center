#!/usr/bin/env python3
"""Generate a concise daily command report from local records.

The report is boss-readable: core numbers first, then problems and tomorrow's
actions. Drafts are never sent by this module (see docs/04-outreach-sop.md).

Two ways to feed data:
  * ``--sample``        : render the built-in demo payload (offline, no I/O).
  * ``--input PATH``    : load a JSON file of the shape
                          ``{"leads":[...], "outreach_tasks":[...],
                             "conversations":[...]}`` and render from it.

``--feishu`` writes the report to the Daily Report table, upserting by Report
Date (re-running on the same day updates the existing row instead of stacking
duplicates). Credentials + ``FEISHU_REPORT_TABLE_ID`` must be set; a missing
destination fails loudly at the first call rather than silently no-op'ing.
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


def sample_records() -> Dict[str, List[Dict[str, Any]]]:
    """Return the built-in demo leads / tasks / conversations.

    Used by ``--sample`` (rendered to markdown) and by ``--feishu --sample``
    (fed to compute_metrics + write). Factored out so both paths share one
    source of demo data.
    """
    return {
        "leads": [
            {"Lead ID": "LEAD-20260621-0001", "Priority": "A", "Status": "Contact Found"},
            {"Lead ID": "LEAD-20260621-0002", "Priority": "B", "Status": "Scored"},
        ],
        "outreach_tasks": [
            {"Task ID": "TASK-1", "Send Status": "Sent", "Result": "Need Meeting"},
            {"Task ID": "TASK-2", "Send Status": "Not Sent", "Result": "No Response"},
        ],
        "conversations": [
            {"Conversation ID": "CONV-1", "Direction": "Inbound", "Intent": "Quote Request"},
        ],
    }


def sample_payload() -> Dict[str, Any]:
    data = sample_records()
    metrics = compute_metrics(data["leads"], data["outreach_tasks"], data["conversations"])
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


# --- Feishu write path (Daily Report table, docs/02 §6.7) -------------------

# The fixed next-day action list. Shared by the markdown renderers and the
# Feishu write so every report carries the same concrete forward actions
# regardless of output channel.
TOMORROW_ACTIONS = [
    "Review all A priority leads that still have `Pending Review` outreach tasks.",
    "Follow up quote requests before starting new cold outreach.",
    "Convert repeated pain signals into Content Opportunity records.",
]


def _date_to_ms(date_str: str) -> int:
    """Convert a YYYY-MM-DD date to a UTC-midnight ms-since-epoch timestamp.

    Feishu DateTime fields store ms-since-epoch; mapping a calendar date to UTC
    midnight keeps the value stable regardless of the runner's local timezone.
    """
    d = dt.date.fromisoformat(date_str)
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)


def build_report_fields(
    metrics: Dict[str, Any],
    report_date: str,
    findings: List[str],
    problems: List[str],
) -> Dict[str, Any]:
    """Translate metrics + sections into a Daily Report field dict (docs/02 §6.7).

    Field names match docs/02 §6.7 EXACTLY so the dict is directly writable to
    Feishu. Numbers coerce to int (default 0); the three text sections are
    joined bullet lists; Report Date is a ms timestamp (Feishu DateTime).
    """
    def _bullets(items: List[str]) -> str:
        return "\n".join("- %s" % item for item in items) if items else "- "

    return {
        "Report Date": _date_to_ms(report_date),
        "New Leads": int(metrics.get("new_leads", 0) or 0),
        "A Leads": int(metrics.get("a_leads", 0) or 0),
        "B Leads": int(metrics.get("b_leads", 0) or 0),
        "Contacts Found": int(metrics.get("contacts_found", 0) or 0),
        "Outreach Drafts Generated": int(metrics.get("outreach_drafts_generated", 0) or 0),
        "Messages Sent": int(metrics.get("messages_sent", 0) or 0),
        "Replies": int(metrics.get("replies", 0) or 0),
        "Quote Requests": int(metrics.get("quote_requests", 0) or 0),
        "Meetings": int(metrics.get("meetings", 0) or 0),
        "Won Deals": int(metrics.get("won_deals", 0) or 0),
        "Lost Deals": int(metrics.get("lost_deals", 0) or 0),
        "Main Findings": _bullets(findings),
        "Problems": _bullets(problems),
        "Tomorrow Actions": _bullets(TOMORROW_ACTIONS),
    }


def write_daily_report_to_feishu(
    metrics: Dict[str, Any],
    report_date: str,
    findings: List[str],
    problems: List[str],
    client: Any,
    config: Any,
) -> Dict[str, Any]:
    """Upsert today's Daily Report row, keyed by Report Date (docs/02 §6.7).

    Matches an existing record whose Report Date equals the target date by
    comparing the stored ms timestamp client-side (robust against Feishu
    filter-syntax quirks on DateTime fields), updates it if found, otherwise
    creates a new row. This makes re-running the report on the same day
    idempotent rather than stacking duplicate daily rows. ``config.table_id``
    ("report")`` raises a clear ``ConfigError`` when the table id is unset so a
    missing destination fails loudly instead of silently no-op'ing.
    """
    table_id = config.table_id("report")
    fields = build_report_fields(metrics, report_date, findings, problems)
    date_ms = fields["Report Date"]

    existing_id = ""
    for record in client.list_records(table_id):
        if (record.get("fields") or {}).get("Report Date") == date_ms:
            existing_id = str(record.get("record_id") or "")
            break

    if existing_id:
        client.update_record(table_id, existing_id, fields)
        return {"action": "updated", "record_id": existing_id, "report_date": report_date}
    created = client.create_record(table_id, fields)
    return {
        "action": "created",
        "record_id": str((created or {}).get("record_id") or ""),
        "report_date": report_date,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily command report")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sample", action="store_true", help="render the built-in demo payload")
    source.add_argument("--input", metavar="PATH", help="load JSON {leads,outreach_tasks,conversations}")
    parser.add_argument(
        "--feishu",
        action="store_true",
        help="write the report to the Daily Report Feishu table (upsert by Report Date)",
    )
    parser.add_argument(
        "--date",
        default="",
        help="report date in YYYY-MM-DD (defaults to today, local time)",
    )
    args = parser.parse_args(argv)

    report_date = args.date or dt.date.today().isoformat()

    if args.feishu:
        # Real write path (spec §2.A6): compute metrics + sections from the
        # chosen source, then upsert one Daily Report row keyed by Report Date.
        # Missing creds / table id fail loudly at the first client call.
        from config import RuntimeConfig
        from feishu_client import FeishuClient

        data = sample_records() if args.sample else load_input_payload(args.input)
        metrics = compute_metrics(data["leads"], data["outreach_tasks"], data["conversations"])
        findings = derive_findings(data["leads"], data["outreach_tasks"], data["conversations"])
        problems = derive_problems(data["leads"], data["outreach_tasks"])
        result = write_daily_report_to_feishu(
            metrics, report_date, findings, problems, FeishuClient(), RuntimeConfig.from_env()
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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
