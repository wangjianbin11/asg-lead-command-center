#!/usr/bin/env python3
"""Extract content opportunities from real lead / conversation pain signals.

This module turns real customer pain (from Lead Pool ``Pain Signal`` /
``Evidence Text`` or from Conversation Log messages) into structured
``Content Opportunity`` records per docs/02 §6.6.

Business rules that are not obvious from the code:
- Every opportunity MUST point back to a real signal — either a lead id or a
  conversation id (or both). An opportunity without a non-empty source id is
  dropped and the count is reported in ``review_needed`` (per design spec §2.A4
  and docs/06 "every content idea must point back to a real lead or
  conversation").
- AI extraction is OPTIONAL: when no AI key is configured (or ``ai_enabled`` is
  False) we fall back to a deterministic rule-based grouping that maps pain
  keywords -> Pain Point enum, then to a Topic / Search Intent /
  Recommended Format / Draft Brief. Rule-based output is flagged
  ``review_needed=True`` (spec §0 rule 6: never fake an AI response).
- When AI IS enabled but the call fails or returns invalid JSON, we fall back
  to the rule-based grouping for that record and flag ``review_needed=True``
  (spec §0 rule 7: never crash the pipeline).
- All field names match docs/02 §6.6 exactly (``Pain Point``, ``Topic``,
  ``Search Intent``, ``Recommended Format``, ``Draft Brief``, ``Priority``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

# A1 shared helper — prompt load / render / AI call (stdlib only).
import prompt_utils


# --- docs/02 §6.6 enums ------------------------------------------------------

# Pain Point single-select values (docs/02 §6.6 / docs/00 §6.6). NOTE this is
# the *content* pain-point set and intentionally excludes "Unknown" — every
# content opportunity must map to a concrete, named pain.
PAIN_POINTS = {"Supplier", "Shipping", "QC", "Packaging", "MOQ", "Price", "Scaling"}

# Search Intent single-select (docs/02 §6.6).
SEARCH_INTENTS = {
    "Problem",
    "Comparison",
    "How-to",
    "Checklist",
    "Case Study",
    "Pricing",
}

# Recommended Format multi-select options (docs/02 §6.6).
RECOMMENDED_FORMATS = {
    "SEO Blog",
    "LinkedIn",
    "Reddit Answer",
    "Quora Answer",
    "Short Video",
    "Email Newsletter",
}

# Priority single-select — shared High/Medium/Low vocabulary.
PRIORITIES = {"High", "Medium", "Low"}

# Keyword -> Pain Point mapping used by the rule-based extractor. Keywords are
# matched case-insensitively against the combined signal text. Order matters
# only in that the FIRST matching pain wins per signal (so put the most
# specific buckets first). Kept conservative so unrelated text yields no
# opportunity rather than a mis-classified one.
_PAIN_KEYWORDS: List[tuple] = [
    ("Supplier", ["supplier", "sourcing", "1688", "alibaba", "agent", "factory", "vendor", " sourcing "]),
    ("Shipping", ["shipping", "fulfillment", "logistics", "delivery", "tracking", "transit", "delay"]),
    ("QC", ["quality control", "qc", "defect", "inspection", "quality issue", "quality check"]),
    ("Packaging", ["packaging", "private label", "custom box", "branded box", "logo box"]),
    ("MOQ", ["moq", "minimum order", "minimum quantity"]),
    ("Price", ["price", "pricing", "expensive", "cost", "markup", "margin", "cheap"]),
    ("Scaling", ["scaling", "scale", "growth", "grow", "expansion", "expand", "more orders"]),
]

# Pain Point -> default editorial recipe (Search Intent, Recommended Format,
# Draft Brief seed, Priority). Mirrors docs/06 output-format guidance: every
# pain has a natural content angle. These are seeds — human review owns the
# final brief (review_needed=True).
_PAIN_RECIPES: Dict[str, Dict[str, Any]] = {
    "Supplier": {
        "search_intent": "Comparison",
        "recommended_format": ["SEO Blog", "Reddit Answer"],
        "draft_brief": "How to evaluate and switch sourcing suppliers without disrupting order flow.",
        "priority": "High",
    },
    "Shipping": {
        "search_intent": "Problem",
        "recommended_format": ["SEO Blog", "Short Video"],
        "draft_brief": "Common shipping / fulfillment delays for dropshipping stores and how to fix them.",
        "priority": "High",
    },
    "QC": {
        "search_intent": "How-to",
        "recommended_format": ["SEO Blog", "Quora Answer"],
        "draft_brief": "A practical quality-control checklist before bulk-fulfilling orders.",
        "priority": "Medium",
    },
    "Packaging": {
        "search_intent": "Checklist",
        "recommended_format": ["LinkedIn", "Short Video"],
        "draft_brief": "Custom packaging options and what to specify when branding your orders.",
        "priority": "Medium",
    },
    "MOQ": {
        "search_intent": "Pricing",
        "recommended_format": ["Reddit Answer", "Quora Answer"],
        "draft_brief": "How MOQ works for dropshipping and how to start with low-volume custom runs.",
        "priority": "Medium",
    },
    "Price": {
        "search_intent": "Comparison",
        "recommended_format": ["SEO Blog", "Email Newsletter"],
        "draft_brief": "Sourcing cost breakdown for dropshippers and where margins are lost.",
        "priority": "Medium",
    },
    "Scaling": {
        "search_intent": "How-to",
        "recommended_format": ["LinkedIn", "SEO Blog"],
        "draft_brief": "Scaling a dropshipping store: fulfillment, warehousing, and team handoff.",
        "priority": "High",
    },
}

PROMPT_REL_PATH = "content/content-opportunity-extractor-v1.md"


# --- helpers ----------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    """Best-effort string coercion; None / missing -> ''."""
    if value is None:
        return ""
    return str(value).strip()


def _signal_source_ids(signal: Dict[str, Any]) -> Dict[str, str]:
    """Pull lead / conversation source ids from a signal dict.

    Accepts both the snake_case keys the pipeline uses internally and the
    Title Case keys that match docs/02 field names, so callers can pass either
    shape. Returns the present ids (others are '' per docs/02 §6.6).
    """
    lead_id = (
        _coerce_str(signal.get("source_lead_id"))
        or _coerce_str(signal.get("Lead ID"))
        or _coerce_str(signal.get("lead_id"))
        or _coerce_str(signal.get("Source Lead ID"))
    )
    conversation_id = (
        _coerce_str(signal.get("source_conversation_id"))
        or _coerce_str(signal.get("Conversation ID"))
        or _coerce_str(signal.get("conversation_id"))
        or _coerce_str(signal.get("Source Conversation ID"))
    )
    return {
        "source_lead_id": lead_id,
        "source_conversation_id": conversation_id,
    }


def _signal_text(signal: Dict[str, Any]) -> str:
    """Combine every free-text field of a signal into one searchable blob."""
    keys = (
        "pain_signal",
        "Pain Signal",
        "evidence_text",
        "Evidence Text",
        "message_content",
        "Message Content",
        "notes",
        "Notes",
        "topic",
        "Topic",
    )
    return " ".join(_coerce_str(signal.get(k)) for k in keys).lower()


def _detect_pain_point(text: str) -> Optional[str]:
    """Return the first matching PAIN_POINTS bucket for ``text`` or None."""
    if not text:
        return None
    for pain, keywords in _PAIN_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return pain
    return None


def _normalize_format_list(formats: Any) -> List[str]:
    """Coerce an AI / rule list of formats into valid docs/02 §6.6 values."""
    if isinstance(formats, str):
        # Allow comma / slash separated strings from the AI.
        raw = [chunk.strip() for chunk in formats.replace("/", ",").split(",")]
    elif isinstance(formats, (list, tuple)):
        raw = [_coerce_str(item) for item in formats]
    else:
        raw = []
    cleaned: List[str] = []
    for item in raw:
        if not item:
            continue
        # Accept minor label variants ("blog" -> "SEO Blog").
        canonical = _canonical_format(item)
        if canonical and canonical not in cleaned:
            cleaned.append(canonical)
    if not cleaned:
        cleaned = ["SEO Blog"]
    return cleaned


_FORMAT_ALIASES = {
    "seo blog": "SEO Blog",
    "blog": "SEO Blog",
    "linkedin": "LinkedIn",
    "linkedin post": "LinkedIn",
    "reddit": "Reddit Answer",
    "reddit answer": "Reddit Answer",
    "quora": "Quora Answer",
    "quora answer": "Quora Answer",
    "short video": "Short Video",
    "video": "Short Video",
    "email": "Email Newsletter",
    "email newsletter": "Email Newsletter",
    "newsletter": "Email Newsletter",
}


def _canonical_format(label: str) -> Optional[str]:
    key = label.strip().lower()
    if key in _FORMAT_ALIASES:
        return _FORMAT_ALIASES[key]
    if label in RECOMMENDED_FORMATS:
        return label
    return None


def _normalize_priority(value: Any, fallback: str = "Medium") -> str:
    priority = _coerce_str(value).capitalize()
    if priority not in PRIORITIES:
        return fallback
    return priority


def _normalize_search_intent(value: Any, fallback: str = "Problem") -> str:
    intent = _coerce_str(value)
    if intent in SEARCH_INTENTS:
        return intent
    return fallback


def _normalize_pain_point(value: Any) -> Optional[str]:
    pain = _coerce_str(value)
    if pain in PAIN_POINTS:
        return pain
    return None


# --- per-signal extraction --------------------------------------------------


def extract_from_pain_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build one Content Opportunity dict per signal.

    Each output dict preserves ``source_lead_id`` and/or ``source_conversation_id``
    from the input signal plus the docs/02 §6.6 fields ``Pain Point``, ``Topic``,
    ``Search Intent``, ``Recommended Format``, ``Priority``, ``Draft Brief``.

    Signals without a detectable pain point OR without ANY source id are skipped
    (content must point back to a real lead / conversation and a concrete pain).
    Skipped signals are NOT silently lost — callers can diff input length vs
    output length to detect review candidates.
    """
    opportunities: List[Dict[str, Any]] = []
    if not isinstance(signals, list):
        return opportunities

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        source = _signal_source_ids(signal)
        # Every opportunity MUST carry a non-empty source id (spec §2.A4).
        if not source["source_lead_id"] and not source["source_conversation_id"]:
            continue

        text = _signal_text(signal)
        pain = _detect_pain_point(text)
        if pain is None:
            # Allow an explicit Pain Point on the signal itself as a fallback.
            pain = _normalize_pain_point(signal.get("Pain Point") or signal.get("pain_point"))
        if pain is None:
            continue

        recipe = _PAIN_RECIPES.get(pain, _PAIN_RECIPES["Shipping"])
        topic = (
            _coerce_str(signal.get("Topic") or signal.get("topic"))
            or _derive_topic(pain, signal)
        )
        brief_seed = _coerce_str(signal.get("Draft Brief") or signal.get("draft_brief"))

        opportunity: Dict[str, Any] = {
            "source_lead_id": source["source_lead_id"],
            "source_conversation_id": source["source_conversation_id"],
            "Pain Point": pain,
            "Topic": topic,
            "Search Intent": _normalize_search_intent(
                signal.get("Search Intent") or signal.get("search_intent"),
                fallback=recipe["search_intent"],
            ),
            "Recommended Format": _normalize_format_list(
                signal.get("Recommended Format")
                or signal.get("recommended_format")
                or recipe["recommended_format"]
            ),
            "Priority": _normalize_priority(
                signal.get("Priority") or signal.get("priority"),
                fallback=recipe["priority"],
            ),
            "Draft Brief": brief_seed or recipe["draft_brief"],
            # Rule-based output is always human-review-gated (spec §0 rule 6).
            "review_needed": True,
        }
        opportunities.append(opportunity)

    return opportunities


def _derive_topic(pain: str, signal: Dict[str, Any]) -> str:
    """Build a concise topic line from the pain + a snippet of evidence."""
    evidence = (
        _coerce_str(signal.get("Evidence Text") or signal.get("evidence_text"))
        or _coerce_str(signal.get("Message Content") or signal.get("message_content"))
        or _coerce_str(signal.get("Pain Signal") or signal.get("pain_signal"))
    )
    if evidence:
        snippet = evidence.strip().replace("\n", " ")
        if len(snippet) > 90:
            snippet = snippet[:87] + "..."
        return "%s: %s" % (pain, snippet)
    return "%s pain points for dropshipping sellers" % pain


# --- AI extraction ----------------------------------------------------------


def _record_to_signal(record: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    """Normalize an arbitrary record (lead or conversation) into a signal dict.

    Lead records carry Lead ID + Pain Signal + Evidence Text.
    Conversation records carry Conversation ID + Lead ID + Message Content.
    """
    signal: Dict[str, Any] = {}
    if source_type == "conversation":
        signal["source_conversation_id"] = (
            _coerce_str(record.get("Conversation ID"))
            or _coerce_str(record.get("conversation_id"))
            or _coerce_str(record.get("source_conversation_id"))
        )
        signal["source_lead_id"] = (
            _coerce_str(record.get("Lead ID"))
            or _coerce_str(record.get("lead_id"))
            or _coerce_str(record.get("source_lead_id"))
        )
        signal["message_content"] = _coerce_str(
            record.get("Message Content") or record.get("message_content")
        )
        signal["notes"] = _coerce_str(record.get("Notes") or record.get("notes"))
    else:
        # Default: treat as a lead-shaped record.
        signal["source_lead_id"] = (
            _coerce_str(record.get("Lead ID"))
            or _coerce_str(record.get("lead_id"))
            or _coerce_str(record.get("source_lead_id"))
        )
        signal["source_conversation_id"] = _coerce_str(
            record.get("source_conversation_id")
        )
        signal["pain_signal"] = _coerce_str(
            record.get("Pain Signal") or record.get("pain_signal")
        )
        signal["evidence_text"] = _coerce_str(
            record.get("Evidence Text") or record.get("evidence_text")
        )
        signal["notes"] = _coerce_str(record.get("Notes") or record.get("notes"))
    return signal


def _call_ai_for_record(signal: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Call the content-opportunity prompt for one signal and return raw items.

    Returns a list of dicts with snake_case keys (``pain_point``, ``topic`` ...).
    Raises prompt_utils.AIConfigError / AIRuntimeError / ValueError on failure
    so the caller can fall back to rule-based extraction.
    """
    template = prompt_utils.load_prompt(PROMPT_REL_PATH)
    variables = {
        "lead_id": signal.get("source_lead_id", ""),
        "conversation_id": signal.get("source_conversation_id", ""),
        "pain_signal": signal.get("pain_signal") or signal.get("Pain Signal") or "",
        "evidence_text": signal.get("evidence_text") or signal.get("Evidence Text") or "",
        "message_content": signal.get("message_content")
        or signal.get("Message Content")
        or "",
        "notes": signal.get("notes") or signal.get("Notes") or "",
    }
    prompt = prompt_utils.render_prompt(template, variables)
    raw = prompt_utils.call_ai(prompt)
    parsed = prompt_utils.extract_json(raw)
    items = parsed.get("opportunities")
    if not isinstance(items, list):
        raise ValueError("AI output missing 'opportunities' list")
    return [item for item in items if isinstance(item, dict)]


def _ai_items_to_opportunities(
    items: List[Dict[str, Any]],
    signal: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Normalize AI-emitted items into the docs/02 §6.6 opportunity shape.

    Source ids come from the originating signal (never trusted from AI text),
    so every emitted opportunity carries the real lead / conversation id.
    """
    source = _signal_source_ids(signal)
    opportunities: List[Dict[str, Any]] = []
    for item in items:
        pain = _normalize_pain_point(
            item.get("pain_point") or item.get("Pain Point")
        )
        if pain is None:
            # AI emitted an unknown pain — still surface it for review but
            # classify via rule so it lands in a valid bucket.
            pain = _detect_pain_point(_signal_text(signal)) or "Shipping"
        recipe = _PAIN_RECIPES.get(pain, _PAIN_RECIPES["Shipping"])
        opportunity = {
            "source_lead_id": source["source_lead_id"],
            "source_conversation_id": source["source_conversation_id"],
            "Pain Point": pain,
            "Topic": _coerce_str(item.get("topic") or item.get("Topic"))
            or _derive_topic(pain, signal),
            "Search Intent": _normalize_search_intent(
                item.get("search_intent") or item.get("Search Intent"),
                fallback=recipe["search_intent"],
            ),
            "Recommended Format": _normalize_format_list(
                item.get("recommended_format")
                or item.get("Recommended Format")
                or recipe["recommended_format"]
            ),
            "Priority": _normalize_priority(
                item.get("priority") or item.get("Priority"),
                fallback=recipe["priority"],
            ),
            "Draft Brief": _coerce_str(
                item.get("draft_brief") or item.get("Draft Brief")
            )
            or recipe["draft_brief"],
            # AI output is reviewed before it becomes content (docs/06 rule).
            "review_needed": True,
        }
        opportunities.append(opportunity)
    return opportunities


# --- public top-level extractor --------------------------------------------


def extract_content_opportunities(
    records: List[Dict[str, Any]],
    source_type: str = "lead",
    ai_enabled: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Extract content opportunities from a list of lead / conversation records.

    - ``source_type`` is ``"lead"`` (default) or ``"conversation"`` and decides
      which docs/02 fields are read from each record.
    - ``ai_enabled``: when ``True`` and an AI key is configured, each record is
      sent to ``prompts/content/content-opportunity-extractor-v1.md`` and the
      returned JSON is normalized into docs/02 §6.6 opportunities. On ANY AI
      failure (no key, network, bad JSON) we fall back to rule-based extraction
      for that record and keep ``review_needed=True`` (spec §0 rules 6 & 7).
      When ``False`` (or no key) we use the deterministic rule-based extractor.
    - Every returned opportunity carries at least one non-empty source id
      (``source_lead_id`` or ``source_conversation_id``); records with neither
      are skipped because content must point back to a real signal (docs/06).
    """
    if ai_enabled is None:
        ai_enabled = prompt_utils.has_ai_key()

    opportunities: List[Dict[str, Any]] = []
    if not isinstance(records, list):
        return opportunities

    for record in records:
        if not isinstance(record, dict):
            continue
        signal = _record_to_signal(record, source_type)
        source = _signal_source_ids(signal)
        if not source["source_lead_id"] and not source["source_conversation_id"]:
            continue

        if ai_enabled:
            try:
                items = _call_ai_for_record(signal)
                record_opps = _ai_items_to_opportunities(items, signal)
                if record_opps:
                    opportunities.extend(record_opps)
                    continue
                # AI returned nothing usable -> fall through to rule-based.
            except (
                prompt_utils.AIConfigError,
                prompt_utils.AIRuntimeError,
                ValueError,
                FileNotFoundError,
            ):
                # Fall back to deterministic extraction; keep review flag set.
                pass

        # Rule-based path (also the fallback when AI yields nothing).
        opportunities.extend(extract_from_pain_signals([signal]))

    return opportunities


# --- Feishu write path (Content Opportunity table, docs/02 §6.6) ------------


def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values before a Feishu write.

    Feishu typed fields reject empty values of the wrong shape ("" into a
    Relation field, [] into Text). Omitting the key leaves the field empty in
    Feishu instead of raising. False / 0 are kept (valid Checkbox / Number
    values). Mirrors run_lead_pipeline._clean_fields.
    """
    return {k: v for k, v in fields.items() if v not in (None, "", [], {})}


def build_content_fields(opportunity: Dict[str, Any], index: int, date_str: str) -> Dict[str, Any]:
    """Translate an opportunity dict into a Content Opportunity field dict.

    Field names match docs/02 §6.6 EXACTLY so the dict is directly writable to
    Feishu Bitable. Source ids are pulled from the snake_case keys the extractor
    emits (``source_lead_id`` / ``source_conversation_id``). A new opportunity
    always starts at ``Status="Idea"`` with no ``Owner`` — a human claims it
    during content review. ``Content ID`` mirrors the LEAD-/SCORE-/TASK- pattern
    (``CTNT-YYYYMMDD-NNNN``) so rows are traceable and sort cleanly.
    """
    if not date_str:
        raise ValueError("date_str is required (YYYYMMDD)")
    if index < 1:
        raise ValueError("index must be >= 1")
    return {
        "Content ID": "CTNT-%s-%04d" % (date_str, index),
        "Source Lead ID": _coerce_str(opportunity.get("source_lead_id")),
        "Source Conversation ID": _coerce_str(opportunity.get("source_conversation_id")),
        "Pain Point": opportunity.get("Pain Point", ""),
        "Topic": opportunity.get("Topic", ""),
        "Search Intent": opportunity.get("Search Intent", ""),
        "Recommended Format": list(opportunity.get("Recommended Format") or []),
        "Draft Brief": opportunity.get("Draft Brief", ""),
        "Priority": opportunity.get("Priority", "Medium"),
        "Status": "Idea",
        "Owner": "",
    }


def write_opportunities_to_feishu(
    opportunities: List[Dict[str, Any]],
    client: Any,
    config: Any,
    *,
    date_str: str = "",
) -> Dict[str, Any]:
    """Create one Content Opportunity record per opportunity in the content table.

    Each content idea is a NEW row (no upsert — the same pain can legitimately
    yield several distinct ideas over time, and dedup belongs to human review).
    Writes are resilient: a single failed ``create_record`` is recorded in
    ``errors`` and does NOT abort the batch (spec §0 rule 7: never crash the
    pipeline on one bad row). ``config.table_id("content")`` raises a clear
    ``ConfigError`` when the table id is unset so a missing destination fails
    loudly instead of silently no-op'ing.
    """
    import datetime as _dt  # local: only needed to derive the default date

    if not date_str:
        date_str = _dt.date.today().strftime("%Y%m%d")
    table_id = config.table_id("content")
    written = 0
    record_ids: List[str] = []
    errors: List[Dict[str, Any]] = []
    for index, opp in enumerate(opportunities, start=1):
        fields = _clean_fields(build_content_fields(opp, index, date_str))
        try:
            created = client.create_record(table_id, fields)
            record_ids.append(str((created or {}).get("record_id") or ""))
            written += 1
        except Exception as exc:  # noqa: BLE001 - record the error, keep the batch going
            errors.append({"content_index": index, "error": str(exc)})
    return {
        "total": len(opportunities),
        "written": written,
        "record_ids": record_ids,
        "errors": errors,
    }


# --- CLI --------------------------------------------------------------------


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Extract content opportunities from lead / conversation JSON."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON file: a list of records, or {\"records\": [...], \"source_type\": \"lead|conversation\"}.",
    )
    parser.add_argument(
        "--source-type",
        default="lead",
        choices=["lead", "conversation"],
        help="Shape of each record (default: lead).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Force the deterministic rule-based extractor (skip AI even if a key is set).",
    )
    parser.add_argument(
        "--write-feishu",
        action="store_true",
        help="Write extracted opportunities to the Content Opportunity Feishu table.",
    )
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        records = payload.get("records") or payload.get("leads") or payload.get("conversations") or []
        source_type = payload.get("source_type", args.source_type)
    elif isinstance(payload, list):
        records = payload
        source_type = args.source_type
    else:
        parser.error("input JSON must be a list or an object with a 'records' key")

    ai_enabled = False if args.no_ai else None
    opportunities = extract_content_opportunities(records, source_type=source_type, ai_enabled=ai_enabled)
    if args.write_feishu:
        # Real client/config built from env; missing creds/table id fail loudly at
        # the first call rather than silently no-op'ing (mirrors run_lead_pipeline).
        from config import RuntimeConfig
        from feishu_client import FeishuClient

        write_report = write_opportunities_to_feishu(
            opportunities, FeishuClient(), RuntimeConfig.from_env()
        )
        print(
            json.dumps(
                {"opportunities": opportunities, "write": write_report},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(json.dumps(opportunities, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
