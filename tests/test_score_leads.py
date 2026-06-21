import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from score_leads import (
    local_heuristic_score,
    map_score_to_priority,
    parse_ai_json,
    validate_scoring_output,
)


VALID_PAYLOAD = {
    "total_score": 86,
    "priority": "A",
    "sourcing_need_score": 18,
    "fulfillment_pain_score": 17,
    "custom_packaging_score": 12,
    "store_maturity_score": 13,
    "contactability_score": 14,
    "asg_service_fit_score": 12,
    "main_pain_point": "Supplier",
    "recommended_offer": "Supplier Switch Audit",
    "reasoning_summary": "Evidence suggests a mature store with sourcing needs.",
    "risk": "Low",
    "review_needed": False,
}


class ScoreLeadTests(unittest.TestCase):
    # --- Case 5: score -> priority ----------------------------------------

    def test_priority_mapping(self):
        # Spec §7.2 boundaries: 80=A, 60=B, 40=C, 0-39=D.
        self.assertEqual(map_score_to_priority(80), "A")
        self.assertEqual(map_score_to_priority(60), "B")
        self.assertEqual(map_score_to_priority(40), "C")
        self.assertEqual(map_score_to_priority(39), "D")

    def test_priority_mapping_boundaries(self):
        # Exact edges and just-below edges per docs/00 §7.2.
        self.assertEqual(map_score_to_priority(100), "A")
        self.assertEqual(map_score_to_priority(79), "B")
        self.assertEqual(map_score_to_priority(59), "C")
        self.assertEqual(map_score_to_priority(0), "D")

    def test_validate_scoring_output(self):
        normalized = validate_scoring_output(VALID_PAYLOAD)
        self.assertEqual(normalized["priority"], "A")
        self.assertFalse(normalized["review_needed"])

    def test_validate_coerces_string_total_score_to_int(self):
        # AI sometimes returns numbers as strings; we coerce, not crash.
        payload = dict(VALID_PAYLOAD)
        payload["total_score"] = "86"
        payload["sourcing_need_score"] = "18"
        normalized = validate_scoring_output(payload)
        self.assertEqual(normalized["total_score"], 86)
        self.assertEqual(normalized["sourcing_need_score"], 18)
        self.assertEqual(normalized["priority"], "A")

    def test_validate_defaults_priority_from_total_when_missing(self):
        payload = dict(VALID_PAYLOAD)
        del payload["priority"]
        normalized = validate_scoring_output(payload)
        self.assertEqual(normalized["priority"], "A")

    def test_validate_rejects_total_score_out_of_range(self):
        for bad in (-1, 101, 150):
            payload = dict(VALID_PAYLOAD)
            payload["total_score"] = bad
            with self.assertRaises(ValueError):
                validate_scoring_output(payload)

    def test_validate_rejects_dimension_out_of_range(self):
        # Sourcing cap is 20 (DIMENSIONS); above must raise.
        payload = dict(VALID_PAYLOAD)
        payload["sourcing_need_score"] = 25
        with self.assertRaises(ValueError):
            validate_scoring_output(payload)

    def test_validate_rejects_invalid_risk(self):
        # risk is a strict 3-value classification (Low/Medium/High); a truly
        # invalid value still rejects. main_pain_point / recommended_offer no
        # longer reject here — see the non-canonical tests below — because a
        # single paraphrased enum must never discard an otherwise-valid AI
        # score (the prior behavior silently replaced real GLM scores with the
        # heuristic whenever GLM phrased an offer/pain point as a synonym).
        payload = dict(VALID_PAYLOAD)
        payload["risk"] = "Critical"
        with self.assertRaises(ValueError):
            validate_scoring_output(payload)

    def test_noncanonical_recommendation_is_preserved_with_review(self):
        # GLM phrases offers freely (e.g. "Supplier Comparison & Sourcing Audit"
        # instead of the canonical "Supplier Switch Audit"). A non-canonical
        # RECOMMENDATION must never discard the whole AI score: keep the raw
        # wording and flag review_needed so a human checks it (spec §0 rule 6/7).
        payload = dict(VALID_PAYLOAD)
        payload["recommended_offer"] = "Supplier Comparison & Sourcing Audit"
        normalized = validate_scoring_output(payload)
        self.assertEqual(normalized["total_score"], 86)
        self.assertEqual(normalized["priority"], "A")
        self.assertEqual(normalized["recommended_offer"], "Supplier Comparison & Sourcing Audit")
        self.assertTrue(normalized["review_needed"])

    def test_noncanonical_pain_point_defaults_unknown_with_review(self):
        # A pain point GLM phrases as "Logistics" matches no canonical pain
        # point substring; default to Unknown + review instead of discarding
        # an otherwise-valid score.
        payload = dict(VALID_PAYLOAD)
        payload["main_pain_point"] = "Logistics"
        normalized = validate_scoring_output(payload)
        self.assertEqual(normalized["main_pain_point"], "Unknown")
        self.assertTrue(normalized["review_needed"])

    def test_priority_mismatch_forces_review(self):
        # Spec §8.3 acceptance: when AI priority != score-derived priority,
        # the derived priority wins and review_needed is forced True.
        payload = dict(VALID_PAYLOAD)
        payload["total_score"] = 61
        payload["priority"] = "A"
        normalized = validate_scoring_output(payload)
        self.assertEqual(normalized["priority"], "B")
        self.assertTrue(normalized["review_needed"])
        self.assertIn("priority_mismatch", normalized)

    def test_validate_rejects_invalid_priority_label(self):
        payload = dict(VALID_PAYLOAD)
        payload["priority"] = "E"
        with self.assertRaises(ValueError):
            validate_scoring_output(payload)

    # --- Case 6: AI JSON parse --------------------------------------------

    def test_parse_ai_json_rejects_non_json(self):
        # Spec §8.3 acceptance: unparseable AI output raises -> human review.
        with self.assertRaises(ValueError):
            parse_ai_json("not json")

    def test_parse_ai_json_accepts_dict(self):
        parsed = parse_ai_json('{"total_score": 86, "priority": "A"}')
        self.assertEqual(parsed["total_score"], 86)
        self.assertEqual(parsed["priority"], "A")

    def test_parse_ai_json_rejects_list(self):
        # Must be an object, not a JSON array.
        with self.assertRaises(ValueError):
            parse_ai_json("[1, 2, 3]")

    def test_parse_ai_json_rejects_string(self):
        with self.assertRaises(ValueError):
            parse_ai_json('"just a string"')

    def test_parse_ai_json_rejects_number(self):
        with self.assertRaises(ValueError):
            parse_ai_json("42")

    def test_full_pipeline_ai_json_to_validated_output(self):
        # End-to-end: raw AI text -> parse -> validate -> auditable dict.
        raw_ai_output = (
            '{"total_score": 72, "priority": "B", '
            '"sourcing_need_score": 14, "fulfillment_pain_score": 14, '
            '"custom_packaging_score": 10, "store_maturity_score": 11, '
            '"contactability_score": 12, "asg_service_fit_score": 11, '
            '"main_pain_point": "Shipping", "recommended_offer": "Fulfillment Quote", '
            '"reasoning_summary": "Store shows fulfillment pain.", '
            '"risk": "Medium", "review_needed": false}'
        )
        parsed = parse_ai_json(raw_ai_output)
        normalized = validate_scoring_output(parsed)
        self.assertEqual(normalized["total_score"], 72)
        self.assertEqual(normalized["priority"], "B")
        self.assertEqual(normalized["main_pain_point"], "Shipping")
        self.assertFalse(normalized["review_needed"])

    # --- local heuristic fallback (no-AI path) ----------------------------

    def test_local_heuristic_score_is_valid_and_flags_review(self):
        # When AI is unavailable, the heuristic must still produce a schema-valid
        # score and mark review_needed=True (spec §0 rule 6).
        lead = {
            "company_name": "Brand X",
            "website_url": "https://brandx.myshopify.com",
            "evidence_text": "shipping delay, looking for a new supplier in China",
            "email": "owner@brandx.com",
        }
        result = local_heuristic_score(lead)
        # Re-validate to prove the heuristic output is schema-conformant.
        re_validated = validate_scoring_output(dict(result))
        self.assertEqual(re_validated["total_score"], result["total_score"])
        self.assertIn(re_validated["priority"], {"A", "B", "C", "D"})
        self.assertTrue(re_validated["review_needed"])
        self.assertIn(re_validated["main_pain_point"], {"Supplier", "Shipping"})


if __name__ == "__main__":
    unittest.main()

