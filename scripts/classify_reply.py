#!/usr/bin/env python3
"""Classify inbound customer replies for ASG Dropshipping sales workflows.

This module implements spec §2.A3 (workflow 5: reply classification). It takes a
free-text customer reply and produces a structured, auditable classification:

  * intent           -> one of REPLY_INTENTS (docs/00 §8.5)
  * urgency          -> High / Medium / Low
  * summary          -> short human-readable summary of the reply
  * customer_need    -> the underlying need/problem the customer expressed
  * recommended_next_action -> the next concrete step for the salesperson
  * suggested_reply  -> a *draft* suggested reply (review-only; never auto-sent)
  * should_follow_up -> whether to continue follow-up cadence
  * next_followup_days -> suggested days until next follow-up

Business rules that are not obvious from the code:
  * When no AI key is configured (or AI is explicitly disabled), we fall back to
    a deterministic keyword classifier and set ``review_needed = True`` so a
    human reviews the result (spec §0 rule 6 — never silently fake an AI call).
  * A "Quote Request" intent ALWAYS forces urgency = High, regardless of what
    the model/heuristic said (docs/00 §8.5 acceptance rule 1).
  * When the customer is clearly not interested, ``should_follow_up`` is set to
    False so high-frequency follow-up stops (docs/00 §8.5 acceptance rule 2).
  * All outputs flow through ``validate_reply_output`` so the payload shape is
    guaranteed even when the AI returns partial/malformed JSON.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from typing import Any, Dict, List, Optional

# A1 shared helper (prompt loading + AI calls). Imported lazily-safe: importing
# this module never triggers a network call or reads env vars at import time.
import prompt_utils


# Allowed intent labels — must mirror docs/00 §8.5 exactly.
REPLY_INTENTS = {
    "Inquiry",
    "Quote Request",
    "Objection",
    "Not Interested",
    "Need More Info",
    "Meeting Request",
    "Complaint",
    "Cooperation",
    "Other",
}

# Allowed urgency labels.
URGENCIES = {"High", "Medium", "Low"}

# Prompt path (relative to the prompts/ directory) for AI classification.
PROMPT_REL_PATH = "sales/reply-classifier-v1.md"

# Keys every classified payload must carry after validation.
_REQUIRED_KEYS = (
    "intent",
    "urgency",
    "summary",
    "customer_need",
    "recommended_next_action",
    "suggested_reply",
    "should_follow_up",
    "next_followup_days",
)


def _coerce_str(value: Any, default: str = "") -> str:
    """Coerce a value to a stripped string, defaulting on None/non-string."""
    if value is None:
        return default
    return str(value).strip()


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """Coerce truthy/falsy values to a strict bool.

    Accepts native bools, common string spellings ("true"/"false"), and ints.
    Falls back to ``default`` for anything unrecognized.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "y"}:
            return True
        if lowered in {"false", "no", "0", "n"}:
            return False
    return default


def _coerce_int(value: Any, default: int = 0, minimum: int = 0) -> int:
    """Coerce a value to a non-negative int, defaulting on failure."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < minimum:
        return minimum
    return result


def validate_reply_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a reply-classification payload.

    Guarantees:
      * Every key in ``_REQUIRED_KEYS`` is present.
      * ``intent`` is in ``REPLY_INTENTS`` (unknown/missing -> "Other").
      * ``urgency`` is in ``URGENCIES`` (unknown/missing -> "Medium").
      * A ``Quote Request`` intent always forces ``urgency = "High"``
        (docs/00 §8.5 acceptance rule 1).
      * ``should_follow_up`` is a strict bool and ``next_followup_days`` an int.
      * Text fields are stripped strings.

    Never raises for unknown enum values — it coerces to the safe default so the
    pipeline can continue and flag the record for human review.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    normalized: Dict[str, Any] = dict(payload)

    # Intent: must be a known label, else default to "Other".
    intent = _coerce_str(normalized.get("intent"))
    if intent not in REPLY_INTENTS:
        intent = "Other"

    # Urgency: must be a known label, else default to "Medium".
    urgency = _coerce_str(normalized.get("urgency"))
    if urgency not in URGENCIES:
        urgency = "Medium"

    # Business rule: a quote request is inherently time-sensitive.
    if intent == "Quote Request":
        urgency = "High"

    should_follow_up = _coerce_bool(normalized.get("should_follow_up"), default=True)
    next_followup_days = _coerce_int(normalized.get("next_followup_days"), default=0, minimum=0)

    # If the heuristic/model said "not interested", stop the cadence
    # (docs/00 §8.5 acceptance rule 2).
    if intent == "Not Interested":
        should_follow_up = False
        next_followup_days = 0

    normalized["intent"] = intent
    normalized["urgency"] = urgency
    normalized["summary"] = _coerce_str(normalized.get("summary"))
    normalized["customer_need"] = _coerce_str(normalized.get("customer_need"))
    normalized["recommended_next_action"] = _coerce_str(
        normalized.get("recommended_next_action")
    )
    normalized["suggested_reply"] = _coerce_str(normalized.get("suggested_reply"))
    normalized["should_follow_up"] = should_follow_up
    normalized["next_followup_days"] = next_followup_days

    # Preserve any explicit review_needed flag from upstream (e.g. rule-based
    # fallback sets it True). Default to False for AI-produced payloads.
    normalized["review_needed"] = _coerce_bool(normalized.get("review_needed"), default=False)

    return normalized


# --- Keyword fallback -------------------------------------------------------
# Keyword groups are ordered so the most actionable signals win. Quote Request
# is checked first because docs/00 §8.5 mandates High urgency for it.
_KEYWORD_GROUPS: List[Dict[str, Any]] = [
    {
        "intent": "Quote Request",
        "urgency": "High",
        "should_follow_up": True,
        "next_followup_days": 1,
        "keywords": [
            "quote",
            "price",
            "pricing",
            "how much",
            "cost",
            "moq",
            "minimum order",
            "rate",
            "rates",
            "estimate",
            "quotation",
        ],
        "customer_need": "Pricing / quote details",
        "next_action": "Send a tailored quote: confirm product, MOQ, and shipping terms.",
    },
    {
        "intent": "Meeting Request",
        "urgency": "High",
        "should_follow_up": True,
        "next_followup_days": 2,
        "keywords": ["meeting", "call", "schedule", "zoom", "google meet", "chat"],
        "customer_need": "Wants a live conversation",
        "next_action": "Propose two meeting slots and confirm the agenda.",
    },
    {
        "intent": "Complaint",
        "urgency": "High",
        "should_follow_up": True,
        "next_followup_days": 1,
        "keywords": [
            "complaint",
            "angry",
            "unhappy",
            "broken",
            "defective",
            "late delivery",
            "refund",
            "terrible",
            "worst",
        ],
        "customer_need": "Service/product problem",
        "next_action": "Acknowledge the issue fast and escalate to QA/logistics owner.",
    },
    {
        "intent": "Not Interested",
        "urgency": "Low",
        "should_follow_up": False,
        "next_followup_days": 0,
        "keywords": [
            "not interested",
            "no thanks",
            "no thank you",
            "stop",
            "unsubscribe",
            "do not contact",
            "remove me",
            "not now",
            "pass",
        ],
        "customer_need": "No current interest",
        "next_action": "Stop high-frequency follow-up; archive for re-engagement later.",
    },
    {
        "intent": "Objection",
        "urgency": "Medium",
        "should_follow_up": True,
        "next_followup_days": 5,
        "keywords": [
            "too expensive",
            "too pricey",
            "already have",
            "existing supplier",
            "not sure",
            "concerned",
            "worried",
            "risk",
        ],
        "customer_need": "Hesitation / objection to address",
        "next_action": "Address the specific objection with proof points / case studies.",
    },
    {
        "intent": "Need More Info",
        "urgency": "Medium",
        "should_follow_up": True,
        "next_followup_days": 3,
        "keywords": [
            "more info",
            "more information",
            "details",
            "tell me more",
            "how does",
            "what is",
            "explain",
            "spec",
            "specs",
        ],
        "customer_need": "Wants more product/service detail",
        "next_action": "Share a short FAQ + relevant capability one-pager.",
    },
    {
        "intent": "Cooperation",
        "urgency": "Medium",
        "should_follow_up": True,
        "next_followup_days": 3,
        "keywords": [
            "partner",
            "partnership",
            "collaborate",
            "collaboration",
            "resell",
            "affiliate",
            "agency",
            "wholesale",
        ],
        "customer_need": "Partnership / collaboration opportunity",
        "next_action": "Clarify the proposed cooperation model and mutual value.",
    },
    {
        "intent": "Inquiry",
        "urgency": "Medium",
        "should_follow_up": True,
        "next_followup_days": 3,
        "keywords": [
            "shipping",
            "fulfillment",
            "logistics",
            "packaging",
            "custom packaging",
            "private label",
            "sourcing",
            "warehouse",
            "warehousing",
            "shopify",
            "quality control",
            "qc",
        ],
        "customer_need": "General service question",
        "next_action": "Reply with the matching FAQ + relevant capability snippet.",
    },
]


def rule_based_classify(reply_text: str) -> Dict[str, Any]:
    """Deterministic keyword classifier used when AI is unavailable.

    Sets ``review_needed = True`` because keyword matching is a fallback, not a
    substitute for human-validated AI output (spec §0 rule 6).
    """
    text = (reply_text or "").strip().lower()
    matched_intent = "Other"
    urgency = "Medium"
    should_follow_up = True
    next_followup_days = 3
    customer_need = "Unclear — needs human review"
    next_action = "Read the reply manually and decide the next step."

    for group in _KEYWORD_GROUPS:
        if any(keyword in text for keyword in group["keywords"]):
            matched_intent = group["intent"]
            urgency = group["urgency"]
            should_follow_up = group["should_follow_up"]
            next_followup_days = group["next_followup_days"]
            customer_need = group["customer_need"]
            next_action = group["next_action"]
            break

    summary = _summarize(reply_text)
    suggested_reply = _rule_based_suggested_reply(matched_intent)

    return validate_reply_output(
        {
            "intent": matched_intent,
            "urgency": urgency,
            "summary": summary,
            "customer_need": customer_need,
            "recommended_next_action": next_action,
            "suggested_reply": suggested_reply,
            "should_follow_up": should_follow_up,
            "next_followup_days": next_followup_days,
            "review_needed": True,
        }
    )


def _summarize(reply_text: str, max_words: int = 20) -> str:
    """Build a short summary by truncating the reply to a word budget."""
    cleaned = " ".join((reply_text or "").split())
    if not cleaned:
        return ""
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    return " ".join(words[:max_words]) + "..."


def _rule_based_suggested_reply(intent: str) -> str:
    """Draft-only suggested reply snippets per intent (review required)."""
    templates = {
        "Quote Request": (
            "Thanks for reaching out! To prepare an accurate quote, could you "
            "confirm the product, target MOQ, and destination? I'll send pricing "
            "right after. (Draft — please review before sending.)"
        ),
        "Meeting Request": (
            "Happy to hop on a call. Would Tuesday 10:00 or Thursday 15:00 "
            "(your timezone) work? I'll send a calendar invite once confirmed. "
            "(Draft — please review before sending.)"
        ),
        "Complaint": (
            "I'm sorry about the trouble — I want to make this right. Could you "
            "share the order details so I can escalate immediately? "
            "(Draft — please review before sending.)"
        ),
        "Not Interested": (
            "Understood, thanks for letting me know. I won't follow up frequently. "
            "Feel free to reach out whenever the timing is better. "
            "(Draft — please review before sending.)"
        ),
        "Objection": (
            "Appreciate the honesty. Let me address that specifically — would a "
            "short comparison or a recent case study help? "
            "(Draft — please review before sending.)"
        ),
        "Need More Info": (
            "Glad to share more detail. Here's a quick overview — happy to send "
            "a deeper FAQ on request. (Draft — please review before sending.)"
        ),
        "Cooperation": (
            "Interesting — let's explore it. Could you share how you picture the "
            "cooperation working? (Draft — please review before sending.)"
        ),
        "Inquiry": (
            "Thanks for the question! Here's the short answer — I can follow up "
            "with specifics. (Draft — please review before sending.)"
        ),
        "Other": (
            "Thanks for your message. I'll review and get back to you shortly. "
            "(Draft — please review before sending.)"
        ),
    }
    return templates.get(intent, templates["Other"])


def _render_classifier_prompt(reply_text: str, context: Optional[Dict[str, Any]]) -> str:
    """Load + render the reply-classifier prompt template."""
    template = prompt_utils.load_prompt(PROMPT_REL_PATH)
    variables: Dict[str, Any] = {
        "reply": reply_text or "",
        "customer_reply": reply_text or "",
        "lead_profile": "",
        "previous_outreach": "",
        "current_status": "",
    }
    if context:
        # Map common context keys into the prompt variables; leave unknown
        # tokens untouched (render_prompt leaves them as-is).
        variables["lead_profile"] = json.dumps(
            context.get("lead_profile") or context.get("lead") or {},
            ensure_ascii=False,
        )
        variables["previous_outreach"] = str(context.get("previous_outreach") or "")
        variables["current_status"] = str(context.get("current_status") or context.get("status") or "")
    return prompt_utils.render_prompt(template, variables)


def classify_reply(
    reply_text: str,
    context: Optional[Dict[str, Any]] = None,
    ai_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Classify a customer reply into a structured, auditable payload.

    Resolution:
      * If ``ai_enabled`` is explicitly False -> rule-based fallback.
      * If ``ai_enabled`` is None or True AND an AI key is configured -> AI call
        via ``prompt_utils.call_ai``.
      * If no AI key is available -> rule-based fallback with ``review_needed``.

    Any AI error (config/network/JSON) is caught and we fall back to the
    rule-based classifier with ``review_needed = True`` so the pipeline never
    crashes on a flaky model response (spec §0 rule 7).
    """
    if ai_enabled is None:
        ai_enabled = prompt_utils.has_ai_key()

    if ai_enabled:
        try:
            prompt = _render_classifier_prompt(reply_text, context)
            raw = prompt_utils.call_ai(prompt)
            payload = prompt_utils.extract_json(raw)
            return validate_reply_output(payload)
        except (prompt_utils.AIConfigError, prompt_utils.AIRuntimeError, ValueError):
            # Fall through to deterministic fallback.
            pass

    return rule_based_classify(reply_text)


# --- Feishu write path (Conversation Log table, docs/02 §6.5) ---------------


def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values before a Feishu write.

    Feishu typed fields reject empty values of the wrong shape (None into a
    Number, [] into Text, "" into Person/Link). Omitting the key leaves the
    field empty in Feishu — same intent, no type error. False/0 are kept
    (valid for Checkbox/Number). Mirrors run_lead_pipeline._clean_fields.
    """
    return {k: v for k, v in fields.items() if v not in (None, "", [], {})}


def build_conversation_fields(
    classification: Dict[str, Any],
    *,
    lead_id: str = "",
    conversation_id: str = "",
    channel: str = "",
    direction: str = "",
    message_content: str = "",
    owner: str = "",
) -> Dict[str, Any]:
    """Translate a classified reply payload into a Conversation Log field dict.

    Field names match docs/02 §6.5 EXACTLY so the dict is directly writable to
    Feishu Bitable. The classification payload uses snake_case keys (the shape
    emitted by ``validate_reply_output``); this maps them onto the PascalCase
    Conversation Log fields:

      * ``summary``             -> ``AI Summary``
      * ``intent``              -> ``Intent``
      * ``urgency``             -> ``Urgency``
      * ``recommended_next_action`` -> ``Next Action``
      * context kwargs          -> Conversation ID / Lead ID / Contact ID ('') /
                                    Channel / Direction / Message Content / Owner /
                                    Created Time

    Business rule (docs/02 §6.5): when the classification says to keep the
    follow-up cadence (``should_follow_up`` True), a short hint is appended to
    ``Next Action`` (`` (follow-up in N days)``) so the salesperson sees the
    recommended cadence inline.
    """
    next_action = _coerce_str(classification.get("recommended_next_action"))
    if _coerce_bool(classification.get("should_follow_up"), default=False):
        days = _coerce_int(
            classification.get("next_followup_days"), default=0, minimum=0
        )
        next_action = "%s (follow-up in %d days)" % (next_action, days)

    return {
        "Conversation ID": _coerce_str(conversation_id),
        "Lead ID": _coerce_str(lead_id),
        "Contact ID": "",
        "Channel": _coerce_str(channel),
        "Direction": _coerce_str(direction),
        "Message Content": _coerce_str(message_content),
        "AI Summary": _coerce_str(classification.get("summary")),
        "Intent": _coerce_str(classification.get("intent")) or "Other",
        "Urgency": _coerce_str(classification.get("urgency")) or "Medium",
        "Next Action": next_action,
        "Owner": _coerce_str(owner),
        "Created Time": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_classification_to_feishu(
    classification: Dict[str, Any],
    client: Any,
    cfg: Any,
    **ctx: Any,
) -> Dict[str, Any]:
    """Create one Conversation Log record from a classified reply.

    Builds the docs/02 §6.5 field dict via ``build_conversation_fields``,
    drops empty values (``_clean_fields``), and calls
    ``client.create_record(cfg.table_id("conversation"), fields)``. Returns the
    created record id (``{"record_id": ...}``) so callers can link / log it.

    ``ctx`` is forwarded verbatim to ``build_conversation_fields`` so callers
    pass ``lead_id=``, ``conversation_id=``, ``channel=`` etc. as keyword args.
    """
    table_id = cfg.table_id("conversation")
    fields = _clean_fields(
        build_conversation_fields(classification, **ctx)
    )
    created = client.create_record(table_id, fields)
    return {"record_id": str((created or {}).get("record_id") or "")}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify a customer reply and recommend the next action.",
    )
    parser.add_argument(
        "--reply",
        required=True,
        help="The customer reply text to classify.",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Force the rule-based classifier (skip AI even if a key is set).",
    )
    args = parser.parse_args(argv)

    result = classify_reply(args.reply, ai_enabled=not args.no_ai)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
