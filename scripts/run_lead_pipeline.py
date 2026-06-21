#!/usr/bin/env python3
"""End-to-end lead pipeline for ASG Lead Command Center.

Orchestrates the V1 acquisition loop on a single CSV of raw leads:

    read CSV  ->  clean_rows  ->  dedupe_rows  ->  assign Lead ID
    ->  (write Lead Pool if write_feishu)
    ->  score leads with Status == "New" (AI if a key is configured and --no-ai
         is not set; otherwise a deterministic local heuristic with
         review_needed=True)
    ->  (write Lead Scoring if write_feishu)
    ->  update Lead Pool ASG Fit Score / Priority / Status="Scored"
    ->  build outreach tasks (Pending Review / Not Sent) for Priority A/B leads
         that have a usable contact channel.

Business rules enforced here (see docs/superpowers/specs §0 and §2.A2):

* Outreach is DRAFT-ONLY. Every task leaves the factory with
  ``Approval Status = Pending Review`` and ``Send Status = Not Sent``. The
  pipeline never sends anything on its own.
* ``dry_run`` is the default and is TOTAL: when True no Feishu method is ever
  called, even if a client is supplied. This keeps local acceptance safe.
* AI is best-effort and auditable. When AI fails for any reason (network,
  malformed JSON, validation error) the lead is re-scored with the local
  heuristic and ``review_needed`` is forced True so a human re-checks it.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Allow ``python3 scripts/run_lead_pipeline.py`` and ``python3 -m unittest`` to
# import sibling modules without installing the repo as a package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import clean_leads  # noqa: E402
import dedupe_leads  # noqa: E402
import generate_outreach  # noqa: E402
import prompt_utils  # noqa: E402
import score_leads  # noqa: E402
from config import RuntimeConfig  # noqa: E402


# Channels scanned for a usable contact, in priority order. Email first because
# it is the cheapest cold-outreach surface; LinkedIn and WhatsApp are secondary;
# Website Form only fires when an explicit contact-form URL is present (a bare
# Website URL does NOT count as a contact — otherwise every lead with a site
# would get an outreach task, breaking the "A/B lead with a usable contact" rule
# in spec §2.A2 step 8).
CONTACT_CHANNEL_FIELDS = (
    ("Email", ("email", "Email")),
    ("LinkedIn", ("linkedin", "LinkedIn URL", "linkedin_url")),
    ("WhatsApp", ("whatsapp", "WhatsApp")),
    ("Website Form", ("contact_form_url", "Contact Form URL")),
)


def generate_lead_id(index: int, date_str: str) -> str:
    """Build a deterministic Lead ID like ``LEAD-20260621-0001``.

    ``date_str`` is expected to be ``YYYYMMDD``. ``index`` is 1-based and
    zero-padded to 4 digits so IDs sort cleanly in Feishu / spreadsheets.
    """
    if not date_str:
        raise ValueError("date_str is required (YYYYMMDD)")
    if index < 1:
        raise ValueError("index must be >= 1")
    return "LEAD-%s-%04d" % (date_str, index)


def _resolve_ai_enabled(ai_enabled: Optional[bool]) -> bool:
    """True iff the caller did not force AI off AND an AI key is configured.

    Resolution matches spec §2.A2: ``ai_enabled`` is True iff ``--no-ai`` is not
    set AND ``prompt_utils.has_ai_key()``. A caller may pass an explicit bool
    (the CLI uses this); ``None`` means "auto-resolve from the environment".
    """
    if ai_enabled is False:
        return False
    if ai_enabled is True:
        # Explicit opt-in still requires a key — without one call_ai would
        # raise AIConfigError and we would fall back anyway, but skipping the
        # round-trip keeps the failure mode cheap and explicit.
        return prompt_utils.has_ai_key()
    return prompt_utils.has_ai_key()


def _build_lead_pool_fields(lead: Dict[str, Any], lead_id: str) -> Dict[str, Any]:
    """Translate a cleaned+deduped lead row into a Lead Pool field dict.

    Field names match docs/02 §6.1 EXACTLY so the dict is directly writable to
    Feishu Bitable. Missing evidence / stage / volume values are left blank
    rather than fabricated.
    """
    fields: Dict[str, Any] = {
        "Lead ID": lead_id,
        "Company / Store Name": lead.get("company_name", ""),
        "Website URL": lead.get("website_url", "") or {"link": lead.get("website_url", "")},
        "Platform": lead.get("platform", "Unknown"),
        "Country / Region": lead.get("country", "Unknown"),
        "Category": lead.get("category", ""),
        "Source Channel": lead.get("source_channel", "Manual"),
        "Source URL": lead.get("source_url", ""),
        "Pain Signal": [],
        "Evidence Text": lead.get("evidence_text") or lead.get("notes", ""),
        "Estimated Stage": "Unknown",
        "Estimated Order Volume": "Unknown",
        "Current Supplier Guess": "",
        "ASG Fit Score": None,
        "Priority": "",
        "Status": lead.get("status", "New"),
        "Owner": "",
        "Notes": lead.get("notes", ""),
    }
    return fields


def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values before a Feishu write.

    Feishu typed fields reject empty values of the wrong shape (None into a
    Number, [] into Text, "" into Person/Link). Omitting a key leaves the field
    empty in Feishu — same intent, no type error. False/0 are kept (valid for
    Checkbox/Number).
    """
    return {k: v for k, v in fields.items() if v not in (None, "", [], {})}


def _build_scoring_fields(lead_id: str, score: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Translate a validated score dict into a Lead Scoring field dict.

    Field names match docs/02 §6.3 EXACTLY. The Score ID mirrors the lead index
    so the row is traceable back to the originating Lead ID.
    """
    return {
        "Score ID": "SCORE-%04d" % index,
        "Lead ID": lead_id,
        "Total Score": score.get("total_score", 0),
        "Sourcing Need Score": score.get("sourcing_need_score", 0),
        "Fulfillment Pain Score": score.get("fulfillment_pain_score", 0),
        "Custom Packaging Score": score.get("custom_packaging_score", 0),
        "Store Maturity Score": score.get("store_maturity_score", 0),
        "Contactability Score": score.get("contactability_score", 0),
        "ASG Service Fit Score": score.get("asg_service_fit_score", 0),
        "Reasoning Summary": score.get("reasoning_summary", ""),
        "Main Pain Point": score.get("main_pain_point", "Unknown"),
        "Recommended Offer": score.get("recommended_offer", "Not Fit"),
        "Risk": score.get("risk", "Medium"),
        "Review Needed": bool(score.get("review_needed", False)),
    }


def _render_scoring_prompt(lead: Dict[str, Any]) -> str:
    """Build the AI scoring prompt body for one lead.

    The versioned prompt at ``prompts/lead-scoring/lead-scoring-v1.md`` defines
    the role + schema; we append a concrete ``Input:`` block of the lead's
    public fields so the model scores THIS lead rather than a placeholder.
    """
    template = prompt_utils.load_prompt("lead-scoring/lead-scoring-v1.md")
    lines = [
        template,
        "",
        "Now score this specific lead. Use only the public facts below.",
        "",
        "Input:",
        "- Company / Store Name: %s" % lead.get("company_name", ""),
        "- Website URL: %s" % lead.get("website_url", ""),
        "- Platform: %s" % lead.get("platform", ""),
        "- Country: %s" % lead.get("country", ""),
        "- Product Category: %s" % lead.get("category", ""),
        "- Source Channel: %s" % lead.get("source_channel", ""),
        "- Source URL: %s" % lead.get("source_url", ""),
        "- Evidence Text: %s" % (lead.get("evidence_text") or lead.get("notes", "")),
        "- Notes: %s" % lead.get("notes", ""),
        "",
        "Return only the JSON object described above.",
    ]
    return "\n".join(lines)


def _score_one_lead(lead: Dict[str, Any], ai_enabled: bool) -> Dict[str, Any]:
    """Score a single lead, preferring AI and falling back to the heuristic.

    Failure policy (spec §0 rule 6 / §0 rule 7): ANY AI or JSON error collapses
    to ``score_leads.local_heuristic_score`` with ``review_needed=True`` so the
    pipeline never crashes on a single bad AI response.
    """
    if ai_enabled:
        try:
            prompt = _render_scoring_prompt(lead)
            raw = prompt_utils.call_ai(prompt)
            parsed = score_leads.parse_ai_json(raw)
            return score_leads.validate_scoring_output(parsed)
        except Exception:  # noqa: BLE001 - any AI/JSON/validate failure -> heuristic fallback
            score = score_leads.local_heuristic_score(lead)
            score["review_needed"] = True
            score["reasoning_summary"] = (
                "AI scoring failed; fell back to local heuristic. "
                + str(score.get("reasoning_summary", ""))
            ).strip()
            return score
    # AI disabled (--no-ai or no key): deterministic heuristic, always review.
    score = score_leads.local_heuristic_score(lead)
    score["review_needed"] = True
    return score


def _usable_contact(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a contact dict + chosen channel if the lead has any usable channel.

    Scans CONTACT_CHANNEL_FIELDS in priority order. A value counts as usable if
    it is non-empty AND (for Website Form) actually points at a URL-like string.
    Returns ``None`` when no channel is available so the caller can skip
    outreach-task creation for that lead.
    """
    for channel, keys in CONTACT_CHANNEL_FIELDS:
        for key in keys:
            value = str(lead.get(key) or "").strip()
            if not value:
                continue
            if channel == "Website Form" and "." not in value:
                # Avoid treating a bare company name as a website-form URL.
                continue
            contact = {
                "Contact ID": "",
                "Name": lead.get("contact_name") or lead.get("name") or "",
                "Email": lead.get("email") or lead.get("Email") or "",
                "Preferred Channel": channel,
            }
            return {"contact": contact, "channel": channel, "value": value}
    return None


def _draft_text_for_channel(channel: str, lead: Dict[str, Any], score: Dict[str, Any]) -> str:
    """Produce a draft-only outreach message body.

    The pipeline does NOT call an AI outreach model in V1 (that is workflow 04,
    a separate step run by a salesperson after review). Instead we emit a short,
    auditable placeholder referencing the recommended offer and CTA so the
    Outreach Task row is never empty and always clearly human-editable.
    """
    company = lead.get("company_name") or "your store"
    offer = score.get("recommended_offer", "Fulfillment Quote")
    pain = score.get("main_pain_point", "fulfillment")
    if channel == "Email":
        return (
            "Hi %s team,\n\n"
            "We help growing eCommerce brands with China sourcing, fulfillment, "
            "QC and custom packaging. Based on public signals around your %s, "
            "we think a %s could be useful.\n\n"
            "Would you be open to a quick review of your current setup?\n\n"
            "- ASG Dropshipping"
        ) % (company, pain.lower(), offer)
    if channel == "LinkedIn":
        return (
            "Hi %s — ASG helps Shopify/WooCommerce brands with sourcing, "
            "fulfillment and custom packaging. Happy to share a quick %s if useful."
        ) % (company, offer)
    if channel == "WhatsApp":
        return (
            "Hi %s! ASG here — we do China sourcing & fulfillment. "
            "Open to a quick chat about %s?"
        ) % (company, offer.lower())
    # Website Form
    return (
        "ASG Dropshipping — China sourcing, fulfillment, QC, custom packaging. "
        "Would love to help %s with %s. Please reach out if interested."
    ) % (company, offer.lower())


def run_pipeline(
    csv_path: str,
    *,
    client: Any = None,
    dry_run: bool = True,
    write_feishu: bool = False,
    ai_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run the full lead pipeline against ``csv_path`` and return a result dict.

    Parameters mirror spec §2.A2 exactly. The result dict contains::

        {
          "summary": {input_rows, cleaned, duplicates, new_leads, scored,
                      priority_a, priority_b, outreach_tasks, ai_enabled,
                      dry_run},
          "leads":        [Lead Pool field dicts],
          "scores":       [Lead Scoring field dicts],
          "outreach_tasks": [Outreach Task field dicts],
          "dry_run":      bool,
        }

    When ``dry_run`` is True the pipeline never calls any Feishu method on
    ``client``, regardless of ``write_feishu``.
    """
    if dry_run and write_feishu:
        # Defensive: the CLI enforces mutual exclusivity, but callers using the
        # Python API should also be protected from an accidental write.
        write_feishu = False

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    input_row_count = len(rows)

    cleaned = clean_leads.clean_rows(rows)

    # clean_leads intentionally returns a fixed field set and drops everything
    # else (see scripts/clean_leads.py). The pipeline still needs the original
    # contact fields (email / linkedin / whatsapp / contact_form_url) for
    # outreach-task routing, so we merge them back here WITHOUT modifying the
    # cleaned fields themselves. We do not own clean_leads.py, so this is done
    # in-place on our own copies only.
    contact_keys = (
        "email", "Email",
        "linkedin", "LinkedIn URL", "linkedin_url",
        "whatsapp", "WhatsApp",
        "contact_form_url", "Contact Form URL",
        "contact_name", "name", "Name",
        "owner", "Owner",
        "evidence_text", "Evidence Text",
    )
    for cleaned_lead, raw_row in zip(cleaned, rows):
        for key in contact_keys:
            if key in raw_row and key not in cleaned_lead:
                cleaned_lead[key] = raw_row[key]

    deduped = dedupe_leads.dedupe_rows(cleaned)

    # Only non-duplicates (or company-similarity review rows, which dedupe_rows
    # keeps in `seen`) proceed to Lead ID assignment. Hard duplicates are
    # counted but skipped from creation.
    unique_leads = [row for row in deduped if not row.get("is_duplicate")]
    duplicate_count = len(deduped) - len(unique_leads)

    date_str = datetime.utcnow().strftime("%Y%m%d")
    config = RuntimeConfig.from_env()

    lead_pool: List[Dict[str, Any]] = []
    scores_payload: List[Dict[str, Any]] = []
    outreach_tasks: List[Dict[str, Any]] = []

    # Per-lead bookkeeping kept in parallel for the summary at the end.
    scored_count = 0
    new_leads_count = 0
    priority_a = 0
    priority_b = 0

    resolved_ai_enabled = _resolve_ai_enabled(ai_enabled)

    for index, lead in enumerate(unique_leads, start=1):
        lead_id = generate_lead_id(index, date_str)
        # Carry the id back onto the lead so downstream builders (outreach,
        # scoring) can read it without re-deriving it.
        lead["Lead ID"] = lead_id
        lead["lead_id"] = lead_id

        lead_fields = _build_lead_pool_fields(lead, lead_id)
        lead_pool.append(lead_fields)

        # Step 4: optionally persist the Lead Pool row BEFORE scoring so the
        # row exists in Feishu even if scoring fails downstream.
        if write_feishu and client is not None and not dry_run:
            lead_table = config.table_id("lead")
            created = client.create_record(lead_table, _clean_fields(lead_fields))
            # Stash the Feishu record_id for the later update_record call.
            lead["_record_id"] = (created or {}).get("record_id") or (created or {}).get("Record ID") or ""

        status = (lead.get("status") or "New").strip() or "New"
        if status != "New":
            continue
        new_leads_count += 1

        score = _score_one_lead(lead, resolved_ai_enabled)
        scored_count += 1

        scoring_fields = _build_scoring_fields(lead_id, score, index)
        scores_payload.append(scoring_fields)

        if write_feishu and client is not None and not dry_run:
            score_table = config.table_id("score")
            client.create_record(score_table, _clean_fields(scoring_fields))

        # Step 7: update Lead Pool with score / priority / Status="Scored".
        lead_fields["ASG Fit Score"] = score.get("total_score", 0)
        lead_fields["Priority"] = score.get("priority", "")
        lead_fields["Status"] = "Scored"

        if write_feishu and client is not None and not dry_run:
            record_id = lead.get("_record_id") or ""
            if record_id:
                client.update_record(
                    config.table_id("lead"),
                    record_id,
                    _clean_fields({
                        "ASG Fit Score": lead_fields["ASG Fit Score"],
                        "Priority": lead_fields["Priority"],
                        "Status": lead_fields["Status"],
                    }),
                )

        priority = score.get("priority", "")
        if priority == "A":
            priority_a += 1
        elif priority == "B":
            priority_b += 1

        # Step 8: outreach tasks for A/B leads with a usable contact channel.
        if priority in ("A", "B"):
            contact_info = _usable_contact(lead)
            if contact_info is not None:
                channel = contact_info["channel"]
                contact = contact_info["contact"]
                draft = _draft_text_for_channel(channel, lead, score)
                task = generate_outreach.build_outreach_task(
                    lead=lead,
                    contact=contact,
                    channel=channel,
                    ai_draft=draft,
                    owner=lead.get("owner", ""),
                    message_type="First Touch",
                )
                # Add the required Task ID (docs/02 §6.4) for traceability.
                task["Task ID"] = "TASK-%04d" % index
                outreach_tasks.append(task)

                if write_feishu and client is not None and not dry_run:
                    outreach_table = config.table_id("outreach")
                    client.create_record(outreach_table, _clean_fields(task))

    summary = {
        "input_rows": input_row_count,
        "cleaned": len(cleaned),
        "duplicates": duplicate_count,
        "unique_leads": len(unique_leads),
        "new_leads": new_leads_count,
        "scored": scored_count,
        "priority_a": priority_a,
        "priority_b": priority_b,
        "outreach_tasks": len(outreach_tasks),
        "ai_enabled": resolved_ai_enabled,
        "dry_run": dry_run,
        "write_feishu": write_feishu and not dry_run,
    }

    return {
        "summary": summary,
        "leads": lead_pool,
        "scores": scores_payload,
        "outreach_tasks": outreach_tasks,
        "dry_run": dry_run,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the ASG lead pipeline (clean -> dedupe -> score -> outreach drafts)."
    )
    parser.add_argument("--input", required=True, help="Path to the input leads CSV.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Default. Do not write anything to Feishu even if a client exists.",
    )
    parser.add_argument(
        "--write-feishu",
        action="store_true",
        help="Persist Lead Pool / Lead Scoring / Outreach Task rows to Feishu. "
        "Mutually exclusive with --dry-run.",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Force the local heuristic scorer and skip any AI call.",
    )
    args = parser.parse_args(argv)

    if args.write_feishu and args.dry_run:
        parser.error("--write-feishu and --dry-run are mutually exclusive")

    # When --write-feishu is requested we build a real client from the
    # environment; if credentials are missing feishu_client will raise a clear
    # error at the first call rather than silently no-op. For --dry-run we pass
    # no client at all so there is zero chance of a stray write.
    client = None
    if args.write_feishu:
        from feishu_client import FeishuClient  # local import: only needed for writes

        client = FeishuClient()

    result = run_pipeline(
        args.input,
        client=client,
        dry_run=not args.write_feishu,
        write_feishu=args.write_feishu,
        ai_enabled=False if args.no_ai else None,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
