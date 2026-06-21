#!/usr/bin/env python3
"""Lead scoring validation and local helper logic."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


PRIORITIES = {"A", "B", "C", "D"}
PAIN_POINTS = {"Supplier", "Shipping", "QC", "Packaging", "MOQ", "Price", "Scaling", "Unknown"}
OFFERS = {
    "Supplier Switch Audit",
    "Sourcing Help",
    "Fulfillment Quote",
    "Custom Packaging",
    "Logistics Optimization",
    "Not Fit",
}
RISKS = {"Low", "Medium", "High"}
DIMENSIONS = {
    "sourcing_need_score": 20,
    "fulfillment_pain_score": 20,
    "custom_packaging_score": 15,
    "store_maturity_score": 15,
    "contactability_score": 15,
    "asg_service_fit_score": 15,
}

# Ordered so the first substring match wins. Models often paraphrase enums
# (e.g. "Shipping Delays" instead of "Shipping"); this canonicalizes those
# variants back to the schema's exact allowed values instead of rejecting and
# forcing a heuristic fallback.
_PAIN_ORDER = ["Supplier", "Shipping", "Packaging", "QC", "MOQ", "Price", "Scaling", "Unknown"]
_OFFER_ORDER = [
    "Supplier Switch Audit", "Sourcing Help", "Fulfillment Quote",
    "Custom Packaging", "Logistics Optimization", "Not Fit",
]


def _canonicalize(value: Any, order: List[str], fallback: str) -> str:
    """Canonicalize a model-emitted enum value.

    - exact (case-insensitive) match        -> that value
    - non-empty paraphrase ("Shipping Delays") -> first canonical value whose
      lowercased form is a substring of the input
    - empty / missing                       -> ``fallback``
    - non-empty but matches NOTHING         -> raise ValueError (truly bogus)

    Raising on bogus preserves the strict-rejection contract (bad AI output ->
    heuristic fallback + human review); the substring branch only rescues
    recognizable paraphrases so an otherwise-good score is not discarded.
    """
    text = str(value or "").strip().lower()
    if not text:
        return fallback
    for canonical in order:
        if text == canonical.lower():
            return canonical
    for canonical in order:
        if canonical.lower() in text:
            return canonical
    raise ValueError("unrecognized enum value: %r" % (value,))


def map_score_to_priority(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def parse_ai_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("AI output is empty")
    # Models often wrap JSON in a ```json ... ``` fence; strip it first so the
    # strict json.loads below succeeds instead of failing at the first backtick.
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    candidate = fence.group(1).strip() if fence else text
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: carve out the outermost {...} span for prose-wrapped
        # output like "Sure! Here is the result: {...}".
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("AI output is not valid JSON")
        try:
            parsed = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("AI output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("AI output must be a JSON object")
    return parsed


def _int_range(payload: Dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    try:
        value = int(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be an integer" % key) from exc
    if value < minimum or value > maximum:
        raise ValueError("%s must be between %s and %s" % (key, minimum, maximum))
    return value


def validate_scoring_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    total_score = _int_range(normalized, "total_score", 0, 100)
    for key, maximum in DIMENSIONS.items():
        normalized[key] = _int_range(normalized, key, 0, maximum)

    expected_priority = map_score_to_priority(total_score)
    priority = str(normalized.get("priority") or expected_priority)
    if priority not in PRIORITIES:
        raise ValueError("priority must be A/B/C/D")
    if priority != expected_priority:
        normalized["review_needed"] = True
        normalized["priority_mismatch"] = "expected %s from total_score" % expected_priority
        priority = expected_priority

    main_pain_point = _canonicalize(normalized.get("main_pain_point"), _PAIN_ORDER, "Unknown")
    recommended_offer = _canonicalize(normalized.get("recommended_offer"), _OFFER_ORDER, "Not Fit")
    risk = str(normalized.get("risk") or "Medium")
    if risk not in RISKS:
        raise ValueError("risk must be Low/Medium/High")

    normalized["total_score"] = total_score
    normalized["priority"] = priority
    normalized["main_pain_point"] = main_pain_point
    normalized["recommended_offer"] = recommended_offer
    normalized["risk"] = risk
    normalized["reasoning_summary"] = str(normalized.get("reasoning_summary") or "")
    normalized["review_needed"] = bool(normalized.get("review_needed", False))
    return normalized


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def local_heuristic_score(lead: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(str(lead.get(key, "")) for key in lead).lower()
    sourcing = 14 if any(token in text for token in ["sourcing", "supplier", "1688", "china"]) else 6
    fulfillment = 16 if any(token in text for token in ["shipping", "fulfillment", "delay", "tracking"]) else 5
    packaging = 12 if any(token in text for token in ["packaging", "private label", "logo"]) else 3
    maturity = 12 if any(token in text for token in ["shopify", "sku", "brand"]) else 5
    contactability = 12 if any(token in text for token in ["email", "@", "linkedin", "whatsapp"]) else 4
    fit = 12 if any(token in text for token in ["dropshipping", "ecommerce", "shopify"]) else 5
    total = sourcing + fulfillment + packaging + maturity + contactability + fit
    return validate_scoring_output(
        {
            "total_score": total,
            "priority": map_score_to_priority(total),
            "sourcing_need_score": sourcing,
            "fulfillment_pain_score": fulfillment,
            "custom_packaging_score": packaging,
            "store_maturity_score": maturity,
            "contactability_score": contactability,
            "asg_service_fit_score": fit,
            "main_pain_point": "Supplier" if sourcing >= fulfillment else "Shipping",
            "recommended_offer": "Sourcing Help" if sourcing >= fulfillment else "Logistics Optimization",
            "reasoning_summary": "Local heuristic score for offline testing. Use AI review before production.",
            "risk": "Medium",
            "review_needed": True,
        }
    )


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate ASG lead scoring JSON")
    parser.add_argument("--json", dest="json_value", help="raw scoring JSON to validate")
    args = parser.parse_args(argv)
    if not args.json_value:
        parser.error("--json is required")
    print(json.dumps(validate_scoring_output(parse_ai_json(args.json_value)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

