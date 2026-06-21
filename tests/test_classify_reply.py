"""Tests for scripts/classify_reply.py (spec §2.A3 — workflow 5)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import classify_reply as cr  # noqa: E402
import prompt_utils  # noqa: E402


def _force_offline(test_case: unittest.TestCase) -> None:
    """Patch the AI boundary so dispatch/CLI tests stay hermetic + deterministic.

    A real AI key in the environment (e.g. GLM via ANTHROPIC_API_KEY) would
    otherwise make classify_reply hit the network and return non-deterministic
    output. These tests assert the rule-based fallback, so both has_ai_key and
    call_ai are neutralized.
    """
    for patcher in (
        mock.patch("prompt_utils.has_ai_key", return_value=False),
        mock.patch(
            "prompt_utils.call_ai",
            side_effect=prompt_utils.AIConfigError("offline unit test"),
        ),
    ):
        patcher.start()
        test_case.addCleanup(patcher.stop)


class ClassifyReplyConstantsTests(unittest.TestCase):
    """Spec §2.A3: REPLY_INTENTS / URGENCIES must match docs/00 §8.5 exactly."""

    def test_reply_intents_match_spec(self):
        self.assertEqual(
            cr.REPLY_INTENTS,
            {
                "Inquiry",
                "Quote Request",
                "Objection",
                "Not Interested",
                "Need More Info",
                "Meeting Request",
                "Complaint",
                "Cooperation",
                "Other",
            },
        )

    def test_urgencies_match_spec(self):
        self.assertEqual(cr.URGENCIES, {"High", "Medium", "Low"})


class ValidateReplyOutputTests(unittest.TestCase):
    """validate_reply_output must coerce types and enforce allowed sets."""

    def _valid_payload(self):
        return {
            "intent": "Inquiry",
            "urgency": "Medium",
            "summary": "Asking about shipping.",
            "customer_need": "Logistics info",
            "recommended_next_action": "Send shipping FAQ.",
            "suggested_reply": "Draft reply.",
            "should_follow_up": True,
            "next_followup_days": 3,
        }

    def test_valid_payload_passes_through(self):
        result = cr.validate_reply_output(self._valid_payload())
        self.assertEqual(result["intent"], "Inquiry")
        self.assertEqual(result["urgency"], "Medium")
        self.assertTrue(result["should_follow_up"])
        self.assertEqual(result["next_followup_days"], 3)

    def test_missing_keys_get_defaults(self):
        result = cr.validate_reply_output({})
        for key in (
            "intent",
            "urgency",
            "summary",
            "customer_need",
            "recommended_next_action",
            "suggested_reply",
            "should_follow_up",
            "next_followup_days",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["intent"], "Other")
        self.assertEqual(result["urgency"], "Medium")

    def test_unknown_intent_defaults_to_other(self):
        payload = self._valid_payload()
        payload["intent"] = "Bogus"
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["intent"], "Other")

    def test_unknown_urgency_defaults_to_medium(self):
        payload = self._valid_payload()
        payload["urgency"] = "Critical"
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["urgency"], "Medium")

    def test_quote_request_forces_urgency_high(self):
        # Spec §8.5 acceptance rule 1: a quote request must be High urgency,
        # even if the model/heuristic said otherwise.
        payload = self._valid_payload()
        payload["intent"] = "Quote Request"
        payload["urgency"] = "Low"
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["intent"], "Quote Request")
        self.assertEqual(result["urgency"], "High")

    def test_quote_request_forces_urgency_high_when_missing(self):
        payload = self._valid_payload()
        payload["intent"] = "Quote Request"
        del payload["urgency"]
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["urgency"], "High")

    def test_should_follow_up_coerced_from_string(self):
        payload = self._valid_payload()
        payload["should_follow_up"] = "false"
        result = cr.validate_reply_output(payload)
        self.assertIs(result["should_follow_up"], False)

    def test_next_followup_days_coerced_and_non_negative(self):
        payload = self._valid_payload()
        payload["next_followup_days"] = "5"
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["next_followup_days"], 5)
        # Negative values clamp to 0.
        payload["next_followup_days"] = -3
        result = cr.validate_reply_output(payload)
        self.assertEqual(result["next_followup_days"], 0)

    def test_not_interested_stops_followup(self):
        # Spec §8.5 acceptance rule 2: not-interested replies must stop
        # high-frequency follow-up.
        payload = self._valid_payload()
        payload["intent"] = "Not Interested"
        payload["should_follow_up"] = True
        payload["next_followup_days"] = 7
        result = cr.validate_reply_output(payload)
        self.assertIs(result["should_follow_up"], False)
        self.assertEqual(result["next_followup_days"], 0)

    def test_non_dict_payload_raises(self):
        with self.assertRaises(ValueError):
            cr.validate_reply_output("not a dict")  # type: ignore[arg-type]


class RuleBasedClassifyTests(unittest.TestCase):
    """rule_based_classify: deterministic keyword fallback."""

    def test_quote_request_keyword_classifies_as_quote_high(self):
        # Spec acceptance for test_classify_reply: a reply asking for a
        # quote/price must classify as intent=Quote Request + urgency=High
        # WITHOUT any AI key configured.
        result = cr.rule_based_classify("Hi, can you send me a quote and the price list?")
        self.assertEqual(result["intent"], "Quote Request")
        self.assertEqual(result["urgency"], "High")
        # Fallback path always flags human review.
        self.assertTrue(result["review_needed"])
        self.assertTrue(result["should_follow_up"])

    def test_price_alone_also_triggers_quote_request(self):
        result = cr.rule_based_classify("What's your price for 500 units?")
        self.assertEqual(result["intent"], "Quote Request")
        self.assertEqual(result["urgency"], "High")

    def test_not_interested_stops_followup(self):
        result = cr.rule_based_classify("Thanks but I'm not interested right now.")
        self.assertEqual(result["intent"], "Not Interested")
        self.assertFalse(result["should_follow_up"])
        self.assertEqual(result["next_followup_days"], 0)

    def test_meeting_request(self):
        result = cr.rule_based_classify("Can we schedule a quick call next week?")
        self.assertEqual(result["intent"], "Meeting Request")
        self.assertEqual(result["urgency"], "High")

    def test_complaint(self):
        result = cr.rule_based_classify("My last order arrived broken and late, this is terrible.")
        self.assertEqual(result["intent"], "Complaint")
        self.assertEqual(result["urgency"], "High")

    def test_inquiry_general_shipping(self):
        result = cr.rule_based_classify("Do you offer shipping to the US and custom packaging?")
        self.assertEqual(result["intent"], "Inquiry")

    def test_unknown_reply_defaults_to_other(self):
        result = cr.rule_based_classify("Hello there.")
        self.assertEqual(result["intent"], "Other")
        self.assertTrue(result["review_needed"])

    def test_rule_based_output_is_schema_valid(self):
        # Round-trip: the heuristic output must pass validate_reply_output.
        result = cr.rule_based_classify("please send a quote")
        re_validated = cr.validate_reply_output(dict(result))
        self.assertEqual(re_validated["intent"], result["intent"])
        self.assertEqual(re_validated["urgency"], result["urgency"])

    def test_empty_reply_does_not_crash(self):
        result = cr.rule_based_classify("")
        self.assertEqual(result["intent"], "Other")
        self.assertTrue(result["review_needed"])

    def test_summary_truncates_long_replies(self):
        long_reply = " ".join(["word"] * 50)
        result = cr.rule_based_classify(long_reply)
        self.assertTrue(result["summary"].endswith("..."))
        # Truncated to 20 words; the trailing "..." is glued to the last token
        # ("word..."), so split() yields exactly 20 tokens.
        self.assertEqual(len(result["summary"].split()), 20)


class ClassifyReplyDispatchTests(unittest.TestCase):
    """classify_reply must dispatch to AI or rule-based per ai_enabled."""

    def setUp(self):
        _force_offline(self)

    def test_ai_disabled_uses_rule_based(self):
        result = cr.classify_reply("send me a quote", ai_enabled=False)
        self.assertEqual(result["intent"], "Quote Request")
        self.assertEqual(result["urgency"], "High")
        # No AI key in the test env -> rule-based always flags review.
        self.assertTrue(result["review_needed"])

    def test_ai_enabled_without_key_falls_back_to_rule_based(self):
        # No key configured in the test env, so even ai_enabled=True must
        # gracefully fall back (spec §0 rule 6/7).
        result = cr.classify_reply("send me a price", ai_enabled=True)
        self.assertEqual(result["intent"], "Quote Request")
        self.assertEqual(result["urgency"], "High")

    def test_default_dispatch_without_ai_key(self):
        # ai_enabled=None + no key -> rule-based path.
        result = cr.classify_reply("not interested, thanks")
        self.assertEqual(result["intent"], "Not Interested")
        self.assertFalse(result["should_follow_up"])


class CLITests(unittest.TestCase):
    """CLI --reply TEXT prints validated JSON."""

    def setUp(self):
        _force_offline(self)

    def test_cli_prints_validated_json(self):
        import io
        import contextlib

        buf = io.StringIO()
        argv = ["--reply", "Hi, can you send me a quote?"]
        with contextlib.redirect_stdout(buf):
            rc = cr.main(argv)
        self.assertEqual(rc, 0)
        import json as _json

        printed = _json.loads(buf.getvalue())
        self.assertEqual(printed["intent"], "Quote Request")
        self.assertEqual(printed["urgency"], "High")

    def test_cli_no_ai_flag(self):
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr.main(["--reply", "not interested", "--no-ai"])
        self.assertEqual(rc, 0)
        import json as _json

        printed = _json.loads(buf.getvalue())
        self.assertEqual(printed["intent"], "Not Interested")


if __name__ == "__main__":
    unittest.main()
