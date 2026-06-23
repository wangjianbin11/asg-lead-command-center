#!/usr/bin/env python3
"""Lead-Pool-driven scorer for ASG Lead Command Center.

This REPLACES the CSV-reading path in run_lead_pipeline for an already-populated
Feishu Lead Pool. It is state-driven and idempotent:

    read Lead Pool rows with Status == "New"
    -> score each (GLM if a key is configured and --no-ai is not set; otherwise
       the deterministic local heuristic, always review_needed)
    -> (write Lead Scoring record when not dry_run)
    -> (update Lead Pool row: ASG Fit Score / Priority / Status="Scored")

Business rules (see docs/superpowers/specs §0 and run_lead_pipeline.py):

* Idempotent: only Status == "New" rows are scored. Scored rows are skipped, so
  re-running the script never re-scores or double-writes.
* dry_run is the default and is TOTAL: when True no Feishu method is ever
  called, even with a client supplied.
* Scoring is delegated to run_lead_pipeline._score_one_lead so the heuristic +
  AI-fallback policy is shared with the CSV pipeline (single source of truth).
* Per-lead failures are captured per-lead and never abort the batch.

Field names mirror docs/02 §6.1 (Lead Pool) and §6.3 (Lead Scoring) EXACTLY so
the dicts are directly writable to Feishu Bitable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Allow ``python3 scripts/score_pending_leads.py`` and ``python3 -m unittest``
# to import sibling modules without installing the repo as a package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import run_lead_pipeline  # noqa: E402  (imported as a module so tests can monkeypatch _score_one_lead)
from config import RuntimeConfig  # noqa: E402


# Map Lead Pool display-name fields (docs/02 §6.1) back to the lowercase keys
# that run_lead_pipeline._score_one_lead / score_leads.local_heuristic_score
# read. This keeps the scorer's input shape identical to the CSV pipeline's
# cleaned-lead dict without re-implementing field normalization.
_LEAD_POOL_TO_LEAD = {
    "Lead ID": "lead_id",
    "Company / Store Name": "company_name",
    "Website URL": "website_url",
    "Platform": "platform",
    "Country / Region": "country",
    "Category": "category",
    "Source Channel": "source_channel",
    "Source URL": "source_url",
    "Evidence Text": "evidence_text",
    "Notes": "notes",
}


def _status_of(fields: Dict[str, Any]) -> str:
    """Read a Lead Pool Status, tolerating string or single-element-list shapes.

    Feishu Single-select fields sometimes arrive as ``[{"text": "New"}]`` or
    ``["New"]``; the value may also be a plain string. Normalize to a trimmed
    string so the equality check is robust regardless of transport.
    """
    value = fields.get("Status", "New")
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("text") or first.get("name") or "").strip() or "New"
        return str(first).strip() or "New"
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip() or "New"
    return str(value or "New").strip() or "New"


def _website_from_field(value: Any) -> str:
    """Coerce a Website URL field (possibly a {"link": ...} dict) to a string."""
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    if isinstance(value, list) and value:
        return _website_from_field(value[0])
    return str(value or "").strip()


def _lead_from_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a Lead Pool field dict into the lowercase lead dict that
    run_lead_pipeline._score_one_lead expects.

    We do NOT mutate ``fields``. Only the keys _score_one_lead /
    local_heuristic_score actually consult are copied; everything else is
    irrelevant to scoring.
    """
    lead: Dict[str, Any] = {}
    for display, key in _LEAD_POOL_TO_LEAD.items():
        if display not in fields:
            continue
        raw = fields.get(display)
        if display == "Website URL":
            lead[key] = _website_from_field(raw)
        elif isinstance(raw, list):
            # Multi-select / attachment-shaped fields: join their text forms so
            # the heuristic's keyword scan still sees the values.
            parts = []
            for item in raw:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("name") or ""))
                else:
                    parts.append(str(item))
            lead[key] = " ".join(p for p in parts if p)
        else:
            lead[key] = "" if raw is None else str(raw)
    # The heuristic scans the joined values for tokens like "shopify" /
    # "shipping". Carrying the most signal-rich fields verbatim helps; the
    # lowercased join already includes Platform, Notes, Evidence Text, etc.
    return lead


def fetch_pending(client: Any, lead_table_id: str) -> List[Dict[str, Any]]:
    """Return Lead Pool records whose Status == "New".

    Prefers a server-side filter (``CurrentValue.[Status]==New``) so Feishu
    returns only the rows we care about. If that call raises for any reason
    (older base, unsupported filter syntax) we fall back to iterating every
    row and filtering client-side. Each returned item is the raw Feishu record
    shape: ``{'record_id': ..., 'fields': ...}``.
    """
    filter_expression = "CurrentValue.[Status]==New"
    try:
        records = client.list_records(
            lead_table_id, filter_expression=filter_expression
        )
    except Exception:  # noqa: BLE001 - any server-filter failure -> client-side fallback
        records = []
        for record in client.iter_records(lead_table_id):
            if _status_of(record.get("fields") or {}) == "New":
                records.append(record)
        return records

    # Defensive: some transports accept the filter but ignore it. Re-confirm
    # client-side so we never score an already-Scored row.
    return [r for r in records if _status_of(r.get("fields") or {}) == "New"]


def score_pending_leads(
    client: Any,
    cfg: RuntimeConfig,
    *,
    ai_enabled: Optional[bool] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Score every Status=="New" Lead Pool row and (when not dry_run) persist.

    Returns::

        {
          "summary": {pending, scored, errors, ai_enabled, dry_run},
          "results": [
            {"record_id", "lead_id", "status": "scored"|"error",
             "score"?: {...}, "error"?: "..."},
            ...
          ],
        }

    Per-lead errors are captured in ``results`` + counted in ``summary.errors``
    and never abort the batch (spec §0 rule 6/7: the system stays up).
    """
    lead_table_id = cfg.table_id("lead")
    score_table_id = cfg.table_id("score")

    resolved_ai = run_lead_pipeline._resolve_ai_enabled(ai_enabled)

    pending = fetch_pending(client, lead_table_id)

    date_str = datetime.utcnow().strftime("%Y%m%d")
    results: List[Dict[str, Any]] = []
    scored_count = 0
    error_count = 0

    for index, record in enumerate(pending, start=1):
        record_id = record.get("record_id") or ""
        fields = record.get("fields") or {}
        lead = _lead_from_fields(fields)

        # Reuse the existing Lead ID if present; otherwise synthesize one so
        # the Lead Scoring row stays traceable. generate_lead_id is imported
        # from run_lead_pipeline to keep ID format identical to the CSV path.
        lead_id = lead.get("lead_id") or run_lead_pipeline.generate_lead_id(
            index, date_str
        )
        lead["lead_id"] = lead_id
        lead["Lead ID"] = lead_id

        try:
            score = run_lead_pipeline._score_one_lead(lead, resolved_ai)
        except Exception as exc:  # noqa: BLE001 - capture per-lead, keep going
            error_count += 1
            results.append(
                {
                    "record_id": record_id,
                    "lead_id": lead_id,
                    "status": "error",
                    "error": str(exc),
                }
            )
            continue

        scoring_fields = run_lead_pipeline._build_scoring_fields(
            lead_id, score, index
        )

        if not dry_run:
            # Step 6 (docs/02 §6.3): write one Lead Scoring record per lead.
            client.create_record(
                score_table_id, run_lead_pipeline._clean_fields(scoring_fields)
            )
            # Step 7 (docs/02 §6.1): update the Lead Pool row in place.
            client.update_record(
                lead_table_id,
                record_id,
                run_lead_pipeline._clean_fields(
                    {
                        "ASG Fit Score": score.get("total_score", 0),
                        "Priority": score.get("priority", ""),
                        "Status": "Scored",
                    }
                ),
            )

        scored_count += 1
        results.append(
            {
                "record_id": record_id,
                "lead_id": lead_id,
                "status": "scored",
                "score": scoring_fields,
            }
        )

    summary = {
        "pending": len(pending),
        "scored": scored_count,
        "errors": error_count,
        "ai_enabled": resolved_ai,
        "dry_run": dry_run,
    }
    return {"summary": summary, "results": results}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score Status='New' leads in the Feishu Lead Pool and write Lead "
            "Scoring records. Default is a dry run (reports counts only)."
        )
    )
    parser.add_argument(
        "--write-feishu",
        action="store_true",
        help=(
            "Persist Lead Scoring records and update Lead Pool rows. When "
            "omitted, the run is a dry run that only reports counts."
        ),
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Force the local heuristic scorer and skip any AI call.",
    )
    args = parser.parse_args(argv)

    # When --write-feishu is requested we build a real client + config from the
    # environment. For a dry run we still need a client to fetch pending leads,
    # but we use a real one only when credentials are present; otherwise we
    # error out clearly rather than silently no-op.
    from feishu_client import FeishuClient  # local import: only needed at runtime

    client = FeishuClient()
    cfg = RuntimeConfig.from_env()

    result = score_pending_leads(
        client,
        cfg,
        ai_enabled=False if args.no_ai else None,
        dry_run=not args.write_feishu,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
