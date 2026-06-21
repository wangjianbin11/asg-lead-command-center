#!/usr/bin/env python3
"""Set up and inspect the ASG Lead Command Center Feishu Base.

This module owns the 8-table schema (mirroring docs/02-feishu-base-schema.md) and
provides two operations:

- ``ensure``: idempotently create any of the 8 tables that are missing in the
  target Base (POST /bitable/v1/apps/{app_token}/tables), then optionally write
  the resulting ``table_id`` map to a local, gitignored JSON file.
- ``doctor``: report whether credentials, the base token, all 8 tables, and the
  key fields of each table are present. ``doctor`` runs offline without
  crashing even when credentials are absent.

Field-type ints follow the Feishu Bitable field-type vocabulary:

    1  = Text          5  = DateTime    13 = Phone
    2  = Number        7  = Checkbox    15 = URL / Link
    3  = SingleSelect  11 = Person/User 18 = Email
    4  = MultiSelect

Relation/lookup and other uncertain types are intentionally defaulted to ``1``
(Text) with a ``note`` — correctness over completeness. ``doctor`` only checks
field presence by name; type perfection is not required for the blocked live
step (see design spec §2.A5).

This module never prints secrets and performs no real API call unless a
configured client is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Reuse the shared Feishu client — never reimplement HTTP/auth here.
from feishu_client import FeishuApiError, FeishuClient, FeishuClientConfig


# --- Feishu Bitable field-type constants ------------------------------------
TYPE_TEXT = 1
TYPE_NUMBER = 2
TYPE_SINGLE = 3
TYPE_MULTI = 4
TYPE_DATETIME = 5
TYPE_CHECKBOX = 7
TYPE_USER = 11
TYPE_PHONE = 13
TYPE_URL = 15
TYPE_EMAIL = 18


def _text(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_TEXT}


def _number(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_NUMBER}


def _single(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_SINGLE}


def _multi(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_MULTI}


def _datetime(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_DATETIME}


def _checkbox(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_CHECKBOX}


def _user(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_USER}


def _phone(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_PHONE}


def _url(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_URL}


def _email(name: str) -> Dict[str, Any]:
    return {"name": name, "type": TYPE_EMAIL}


def _relation(name: str, note: str) -> Dict[str, Any]:
    """Relation/lookup fields are typed as Text in this builder.

    Feishu Relation/lookup types carry extra linkage config (foreign table +
    whether it is single/multi) that the doctor step does not need to validate.
    Per the design contract, we type uncertain fields as Text (1) and record a
    note rather than guess; ``doctor`` only checks presence by name.
    """
    return {"name": name, "type": TYPE_TEXT, "note": note}


# --- The 8-table schema (mirrors docs/02-feishu-base-schema.md) -------------
# Keyed by logical name; each entry is {"name": <display name>, "fields": [...]}.
# Field NAMES must match docs/02 EXACTLY (they are the contract for record writes).
TABLES: Dict[str, Dict[str, Any]] = {
    "lead": {
        "name": "Lead Pool",
        "fields": [
            _text("Lead ID"),
            _text("Company / Store Name"),
            _url("Website URL"),
            _single("Platform"),
            _single("Country / Region"),
            _text("Category"),
            _single("Source Channel"),
            _url("Source URL"),
            _multi("Pain Signal"),
            _text("Evidence Text"),
            _single("Estimated Stage"),
            _single("Estimated Order Volume"),
            _text("Current Supplier Guess"),
            _number("ASG Fit Score"),
            _single("Priority"),
            _single("Status"),
            _user("Owner"),
            _datetime("Created Time"),
            _datetime("Last Updated"),
            _text("Notes"),
        ],
    },
    "contact": {
        "name": "Contact Table",
        "fields": [
            _text("Contact ID"),
            _relation("Lead ID", "Relation to Lead Pool; created as Text for builder, link in Feishu UI"),
            _text("Name"),
            _text("Role"),
            _email("Email"),
            _single("Email Confidence"),
            _url("LinkedIn URL"),
            _phone("WhatsApp"),
            _url("Facebook URL"),
            _url("Instagram URL"),
            _url("Contact Form URL"),
            _single("Preferred Channel"),
            _single("Contact Status"),
            _text("Notes"),
        ],
    },
    "score": {
        "name": "Lead Scoring",
        "fields": [
            _text("Score ID"),
            _relation("Lead ID", "Relation to Lead Pool; created as Text for builder, link in Feishu UI"),
            _number("Total Score"),
            _number("Sourcing Need Score"),
            _number("Fulfillment Pain Score"),
            _number("Custom Packaging Score"),
            _number("Store Maturity Score"),
            _number("Contactability Score"),
            _number("ASG Service Fit Score"),
            _text("Reasoning Summary"),
            _single("Main Pain Point"),
            _single("Recommended Offer"),
            _single("Risk"),
            _checkbox("Review Needed"),
        ],
    },
    "outreach": {
        "name": "Outreach Task",
        "fields": [
            _text("Task ID"),
            _relation("Lead ID", "Relation to Lead Pool; created as Text for builder, link in Feishu UI"),
            _relation("Contact ID", "Relation to Contact Table; created as Text for builder, link in Feishu UI"),
            _user("Owner"),
            _single("Channel"),
            _single("Message Type"),
            _text("AI Draft"),
            _text("Human Edited Version"),
            _single("Approval Status"),
            _single("Send Status"),
            _datetime("Send Date"),
            _datetime("Next Follow-up Date"),
            _single("Result"),
            _text("Notes"),
        ],
    },
    "conversation": {
        "name": "Conversation Log",
        "fields": [
            _text("Conversation ID"),
            _relation("Lead ID", "Relation to Lead Pool; created as Text for builder, link in Feishu UI"),
            _relation("Contact ID", "Relation to Contact Table; created as Text for builder, link in Feishu UI"),
            _single("Channel"),
            _single("Direction"),
            _text("Message Content"),
            _text("AI Summary"),
            _single("Intent"),
            _single("Urgency"),
            _text("Next Action"),
            _user("Owner"),
            _datetime("Created Time"),
        ],
    },
    "content": {
        "name": "Content Opportunity",
        "fields": [
            _text("Content ID"),
            _relation("Source Lead ID", "Relation to Lead Pool; created as Text for builder, link in Feishu UI"),
            _relation(
                "Source Conversation ID",
                "Relation to Conversation Log; created as Text for builder, link in Feishu UI",
            ),
            _single("Pain Point"),
            _text("Topic"),
            _single("Search Intent"),
            _multi("Recommended Format"),
            _text("Draft Brief"),
            _single("Priority"),
            _single("Status"),
            _user("Owner"),
        ],
    },
    "report": {
        "name": "Daily Report",
        "fields": [
            _datetime("Report Date"),
            _number("New Leads"),
            _number("A Leads"),
            _number("B Leads"),
            _number("Contacts Found"),
            _number("Outreach Drafts Generated"),
            _number("Messages Sent"),
            _number("Replies"),
            _number("Quote Requests"),
            _number("Meetings"),
            _number("Won Deals"),
            _number("Lost Deals"),
            _text("Main Findings"),
            _text("Problems"),
            _text("Tomorrow Actions"),
        ],
    },
    "prompt": {
        "name": "Prompt Version",
        "fields": [
            _text("Prompt ID"),
            _text("Prompt Name"),
            _text("Version"),
            _single("Use Case"),
            _text("Prompt Content"),
            _text("Output Schema"),
            _single("Status"),
            _user("Owner"),
            _datetime("Last Updated"),
            _text("Test Result"),
        ],
    },
}


# Expected table display names in priority order, used by doctor summaries.
LOGICAL_NAMES: List[str] = ["lead", "contact", "score", "outreach", "conversation", "content", "report", "prompt"]


def _existing_tables_index(client: FeishuClient) -> Dict[str, Dict[str, Any]]:
    """Return ``{table_name_lower: table_meta}`` for tables that already exist.

    Lookup is by display name (Feishu guarantees unique table names per Base),
    matched case-insensitively. Returns ``{}`` if no tables exist.
    """
    index: Dict[str, Dict[str, Any]] = {}
    for table in client.list_tables():
        name = str(table.get("name") or "").strip()
        if name:
            index[name.lower()] = table
    return index


def _list_field_names(table_meta: Dict[str, Any]) -> List[str]:
    """Extract field display names from a table meta dict.

    Feishu's ``list_tables`` response omits ``fields``; ``fields`` only appear on
    the per-table describe response. We defensively support both shapes so the
    doctor can also be fed a richer table meta if the caller provides one.
    """
    names: List[str] = []
    fields = table_meta.get("fields") or []
    for field in fields:
        name = str(field.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _describe_table_fields(client: FeishuClient, table_id: str) -> List[Dict[str, Any]]:
    """Fetch the full field list for a single table via the describe endpoint.

    Falls back to an empty list on any Feishu error so ``doctor`` never crashes
    mid-report — a missing describe is itself a useful signal.
    """
    try:
        data = client.api_request(
            "GET",
            "/bitable/v1/apps/%s/tables/%s/fields" % (client.config.app_token, table_id),
        )
    except FeishuApiError:
        return []
    items = data.get("items") or data.get("fields") or []
    return list(items)


def ensure(client: FeishuClient, *, dry_run: bool = False) -> Dict[str, Any]:
    """Idempotently create the 8 ASG tables in the client's Base.

    For each logical table: if a table with the same display name already exists,
    reuse its ``table_id``; otherwise create it via
    ``POST /bitable/v1/apps/{app_token}/tables`` with ``{table: {name, fields}}``.

    Returns a report dict::

        {
            "dry_run": bool,
            "created": {logical_name: table_id, ...},
            "reused":  {logical_name: table_id, ...},
            "skipped": [logical_name, ...],   # dry-run only
            "table_ids": {logical_name: table_id, ...},
            "errors":   [{logical_name, error}, ...],
        }
    """
    if not client.config.app_token:
        raise FeishuApiError("missing FEISHU_BASE_APP_TOKEN (cannot ensure tables)")

    report: Dict[str, Any] = {
        "dry_run": bool(dry_run),
        "created": {},
        "reused": {},
        "skipped": [],
        "table_ids": {},
        "errors": [],
    }

    existing = _existing_tables_index(client)

    for logical_name in LOGICAL_NAMES:
        spec = TABLES[logical_name]
        display_name = spec["name"]

        match = existing.get(display_name.lower())
        if match:
            table_id = str(match.get("table_id") or match.get("tableId") or "")
            report["reused"][logical_name] = table_id
            report["table_ids"][logical_name] = table_id
            continue

        if dry_run:
            report["skipped"].append(logical_name)
            continue

        # Create missing table. The builder payload uses field objects shaped as
        # {field_name, type}; Feishu accepts the keys ``field_name`` / ``type``.
        builder_fields = [
            {"field_name": field["name"], "type": field["type"]}
            for field in spec["fields"]
        ]
        try:
            data = client.api_request(
                "POST",
                "/bitable/v1/apps/%s/tables" % client.config.app_token,
                payload={"table": {"name": display_name, "fields": builder_fields}},
            )
        except FeishuApiError as exc:
            report["errors"].append({"logical_name": logical_name, "error": str(exc)})
            continue

        table_id = str(data.get("table_id") or data.get("tableId") or "")
        if not table_id:
            report["errors"].append(
                {"logical_name": logical_name, "error": "create response missing table_id: %s" % data}
            )
            continue
        report["created"][logical_name] = table_id
        report["table_ids"][logical_name] = table_id

    report["ok"] = len(report["errors"]) == 0
    return report


def doctor(client: Optional[FeishuClient] = None, *, live: bool = False) -> Dict[str, Any]:
    """Report Feishu Base readiness without performing writes.

    Checks (in order):
      1. credential presence (APP_ID / APP_SECRET / BASE_APP_TOKEN);
      2. tenant access token, when ``live=True`` and creds are sufficient;
      3. all 8 tables present (by display name);
      4. per-table key-field presence (one representative field per table).

    Runs offline without crashing when credentials are absent — every check
    degrades to ``False`` with an explanatory note. Never prints secrets.
    """
    config = (client.config if client is not None else FeishuClientConfig.from_env())

    report: Dict[str, Any] = {
        "live": bool(live),
        "credentials": {
            "FEISHU_APP_ID": bool(config.app_id),
            "FEISHU_APP_SECRET": bool(config.app_secret),
            "FEISHU_BASE_APP_TOKEN": bool(config.app_token),
            "direct_access_token": bool(config.access_token),
        },
        "tenant_access_token_ok": False,
        "tables_present": 0,
        "tables_total": len(LOGICAL_NAMES),
        "tables": {},
        "field_checks": {},
        "errors": [],
    }

    creds_sufficient = bool(config.app_token) and (
        bool(config.access_token) or (bool(config.app_id) and bool(config.app_secret))
    )

    if live and creds_sufficient:
        try:
            if client is not None:
                report["tenant_access_token_ok"] = bool(client.get_tenant_access_token())
            else:
                report["tenant_access_token_ok"] = bool(FeishuClient(config).get_tenant_access_token())
        except FeishuApiError as exc:
            report["errors"].append({"check": "tenant_access_token", "error": str(exc)})

    # Table + field presence requires network access. When creds are missing we
    # short-circuit and mark everything as not-checked rather than crash.
    if not creds_sufficient or client is None:
        report["errors"].append(
            {
                "check": "credentials",
                "error": "Feishu credentials not configured; cannot inspect live Base",
            }
        )
        for logical_name in LOGICAL_NAMES:
            report["tables"][logical_name] = {
                "name": TABLES[logical_name]["name"],
                "present": False,
                "checked": False,
                "table_id": "",
            }
            report["field_checks"][logical_name] = {
                "key_field": _key_field(logical_name),
                "present": False,
                "checked": False,
            }
        report["ok"] = False
        return report

    try:
        existing = _existing_tables_index(client)  # type: ignore[arg-type]
    except FeishuApiError as exc:
        report["errors"].append({"check": "list_tables", "error": str(exc)})
        report["ok"] = False
        return report

    for logical_name in LOGICAL_NAMES:
        display_name = TABLES[logical_name]["name"]
        match = existing.get(display_name.lower())
        present = bool(match)
        if present:
            report["tables_present"] += 1
        report["tables"][logical_name] = {
            "name": display_name,
            "present": present,
            "checked": True,
            "table_id": str((match or {}).get("table_id") or (match or {}).get("tableId") or ""),
        }

        key_field = _key_field(logical_name)
        field_present = False
        if present:
            table_id = str((match or {}).get("table_id") or (match or {}).get("tableId") or "")
            field_defs = _describe_table_fields(client, table_id)  # type: ignore[arg-type]
            field_names = {str(f.get("field_name") or f.get("name") or "").strip() for f in field_defs}
            field_present = key_field in field_names
        report["field_checks"][logical_name] = {
            "key_field": key_field,
            "present": field_present,
            "checked": present,
        }

    report["ok"] = (
        report["tables_present"] == len(LOGICAL_NAMES)
        and all(fc["present"] for fc in report["field_checks"].values())
        and not report["errors"]
    )
    return report


def _key_field(logical_name: str) -> str:
    """Return a single representative field used to sanity-check a table.

    Chosen to be the most diagnostic name per table (the unique ID column where
    one exists). Falls back to the first field otherwise.
    """
    preferred = {
        "lead": "Lead ID",
        "contact": "Contact ID",
        "score": "Score ID",
        "outreach": "Task ID",
        "conversation": "Conversation ID",
        "content": "Content ID",
        "report": "Report Date",
        "prompt": "Prompt ID",
    }
    if logical_name in preferred:
        return preferred[logical_name]
    return TABLES[logical_name]["fields"][0]["name"]


def write_local_config(table_ids: Dict[str, str], path: str = "config/feishu_tables.local.json") -> str:
    """Write the logical-name -> table_id map to a local JSON file.

    The output file is intended to be gitignored (see .gitignore owned by A7).
    The path is repo-relative by default; callers may pass an absolute path.
    Returns the absolute path written.
    """
    # Resolve repo-relative paths against this file's parent-of-parent (repo root).
    if not os.path.isabs(path):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(repo_root, path)
    else:
        target = path

    os.makedirs(os.path.dirname(target), exist_ok=True)
    payload = {name: {"name": TABLES[name]["name"], "table_id": str(tid)} for name, tid in table_ids.items()}
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return target


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set up and inspect the ASG Lead Command Center Feishu Base (8 tables).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_p = sub.add_parser("doctor", help="report Base/credentials/tables/fields status (offline-safe)")
    doctor_p.add_argument("--live", action="store_true", help="also request a tenant access token")

    ensure_p = sub.add_parser("ensure", help="create any missing tables idempotently")
    ensure_p.add_argument("--dry-run", action="store_true", help="report what would be created without writing")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = FeishuClientConfig.from_env()

    if args.command == "doctor":
        # doctor must run without crashing even when creds are absent; never
        # construct a live transport when we have no credentials.
        client = FeishuClient(config) if config.app_token else None
        _print_json(doctor(client, live=args.live))
        return 0

    if args.command == "ensure":
        if not config.app_token:
            print(
                "error: FEISHU_BASE_APP_TOKEN is not configured; cannot ensure tables",
                file=sys.stderr,
            )
            return 1
        client = FeishuClient(config)
        try:
            report = ensure(client, dry_run=args.dry_run)
        except FeishuApiError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 1
        _print_json(report)
        # Only persist table ids on a real (non-dry-run) run that produced ids.
        if not args.dry_run and report["table_ids"]:
            try:
                written = write_local_config(report["table_ids"])
                # Keep the path echo out of the secrets path — it is just a repo file.
                print("wrote: %s" % written, file=sys.stderr)
            except OSError as exc:
                print("warning: could not write local config: %s" % exc, file=sys.stderr)
        return 0 if report.get("ok", True) else 1

    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FeishuApiError as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
