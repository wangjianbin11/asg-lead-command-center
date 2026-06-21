import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"

# A prompt's ```json block is its output contract. These are the keys each
# load-bearing prompt must expose so downstream parsers (score_leads,
# classify_reply, generate_outreach) stay stable.
REQUIRED_SCHEMA_KEYS = {
    "lead-scoring/lead-scoring-v1.md": {
        "total_score",
        "priority",
        "sourcing_need_score",
        "fulfillment_pain_score",
        "custom_packaging_score",
        "store_maturity_score",
        "contactability_score",
        "asg_service_fit_score",
        "main_pain_point",
        "recommended_offer",
        "reasoning_summary",
        "risk",
        "review_needed",
    },
    "sales/reply-classifier-v1.md": {
        "intent",
        "urgency",
        "summary",
        "customer_need",
        "recommended_next_action",
        "suggested_reply",
        "should_follow_up",
        "next_followup_days",
    },
    "outreach/cold-email-v1.md": {"subject", "email_body", "cta", "personalization_reason"},
    "outreach/whatsapp-message-v1.md": {"message", "reason"},
}

# Every top-level prompt category must ship at least one prompt file.
EXPECTED_CATEGORIES = {
    "lead-scoring",
    "outreach",
    "sales",
    "content",
    "reports",
}


def extract_json_block(text: str) -> str:
    match = re.search(r"```json\n(.*?)\n```", text, flags=re.S)
    if match is None:
        raise AssertionError("missing ```json block in prompt")
    return match.group(1)


class PromptSchemaTests(unittest.TestCase):
    # --- Case 9: prompt JSON schema ---------------------------------------

    def test_prompt_json_blocks_are_parseable(self):
        # Every prompt file MUST contain exactly one parseable ```json block
        # (spec §9: "明确输出 JSON").
        prompt_files = sorted(PROMPTS_DIR.glob("**/*.md"))
        self.assertGreater(len(prompt_files), 0)
        for path in prompt_files:
            text = path.read_text(encoding="utf-8")
            match = re.search(r"```json\n(.*?)\n```", text, flags=re.S)
            self.assertIsNotNone(match, "missing json block in %s" % path)
            json.loads(match.group(1))

    def test_each_prompt_has_exactly_one_json_block(self):
        # Two JSON blocks in one prompt is ambiguous for downstream parsers.
        for path in sorted(PROMPTS_DIR.glob("**/*.md")):
            text = path.read_text(encoding="utf-8")
            matches = re.findall(r"```json\n.*?\n```", text, flags=re.S)
            self.assertEqual(
                len(matches), 1, "%s should have exactly one json block" % path
            )

    def test_expected_categories_exist(self):
        categories = {p.parent.name for p in PROMPTS_DIR.glob("**/*.md")}
        for category in EXPECTED_CATEGORIES:
            self.assertIn(category, categories, "missing prompt category: %s" % category)

    def test_load_bearing_schemas_have_stable_keys(self):
        # The keys below are read by code; if a prompt drops one, parsing breaks.
        for rel_path, required in REQUIRED_SCHEMA_KEYS.items():
            full = PROMPTS_DIR / rel_path
            self.assertTrue(full.exists(), "missing load-bearing prompt: %s" % rel_path)
            block = extract_json_block(full.read_text(encoding="utf-8"))
            parsed = json.loads(block)
            self.assertIsInstance(parsed, dict, "%s schema must be an object" % rel_path)
            missing = required - set(parsed.keys())
            self.assertFalse(
                missing,
                "%s schema missing required keys: %s" % (rel_path, sorted(missing)),
            )

    def test_lead_scoring_schema_types_are_consistent(self):
        # score_leads.validate_scoring_output coerces these to ints / strings;
        # the prompt must show them as the right primitive types.
        full = PROMPTS_DIR / "lead-scoring" / "lead-scoring-v1.md"
        parsed = json.loads(extract_json_block(full.read_text(encoding="utf-8")))
        for numeric_key in (
            "total_score",
            "sourcing_need_score",
            "fulfillment_pain_score",
            "custom_packaging_score",
            "store_maturity_score",
            "contactability_score",
            "asg_service_fit_score",
        ):
            self.assertIsInstance(
                parsed[numeric_key], int, "%s must be int in schema" % numeric_key
            )
        self.assertIsInstance(parsed["review_needed"], bool)

    def test_reply_classifier_schema_types_are_consistent(self):
        full = PROMPTS_DIR / "sales" / "reply-classifier-v1.md"
        parsed = json.loads(extract_json_block(full.read_text(encoding="utf-8")))
        self.assertIsInstance(parsed["should_follow_up"], bool)
        self.assertIsInstance(parsed["next_followup_days"], int)
        for text_key in ("intent", "urgency", "summary"):
            self.assertIsInstance(parsed[text_key], str)


if __name__ == "__main__":
    unittest.main()

