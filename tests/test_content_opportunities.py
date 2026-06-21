"""Tests for scripts/generate_content_opportunities.py (spec §2.A4)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from config import RuntimeConfig  # noqa: E402
from generate_content_opportunities import (  # noqa: E402
    PAIN_POINTS,
    PRIORITIES,
    RECOMMENDED_FORMATS,
    SEARCH_INTENTS,
    _normalize_format_list,
    build_content_fields,
    extract_content_opportunities,
    extract_from_pain_signals,
    write_opportunities_to_feishu,
)


SAMPLE_PAIN_SIGNALS = [
    {
        "source_lead_id": "LEAD-20260621-0001",
        "pain_signal": "shipping delay",
        "evidence_text": "Customer complains orders take 3 weeks and tracking is broken.",
    },
    {
        "source_lead_id": "LEAD-20260621-0002",
        "pain_signal": "supplier issue",
        "evidence_text": "Looking for a new China sourcing agent after factory QC problems.",
    },
    {
        "source_lead_id": "LEAD-20260621-0003",
        "pain_signal": "custom packaging",
        "evidence_text": "Wants branded boxes and private label logo for SKUs.",
    },
    {
        # Conversation-sourced signal (no lead id, only conversation id).
        "source_conversation_id": "CONV-20260621-0007",
        "message_content": "Our MOQ is too high and we can't scale past 30 orders/day.",
        "notes": "Mentioned pricing concerns too.",
    },
    {
        # No source id at all -> MUST be skipped.
        "pain_signal": "shipping delay",
        "evidence_text": "Anonymous complaint with no lead.",
    },
    {
        # Source id present but no detectable pain keyword -> skipped.
        "source_lead_id": "LEAD-20260621-0009",
        "pain_signal": "",
        "evidence_text": "Just saying hello.",
    },
]


class PainPointSetTests(unittest.TestCase):
    """docs/02 §6.6 Pain Point enum (spec §2.A4)."""

    def test_pain_points_excludes_unknown(self):
        # Content Opportunity Pain Point is a strict set; "Unknown" is NOT
        # allowed here (unlike Lead Scoring's Main Pain Point).
        self.assertEqual(
            PAIN_POINTS,
            {"Supplier", "Shipping", "QC", "Packaging", "MOQ", "Price", "Scaling"},
        )

    def test_search_intents_match_docs(self):
        self.assertEqual(
            SEARCH_INTENTS,
            {"Problem", "Comparison", "How-to", "Checklist", "Case Study", "Pricing"},
        )

    def test_recommended_formats_match_docs(self):
        self.assertEqual(
            RECOMMENDED_FORMATS,
            {
                "SEO Blog",
                "LinkedIn",
                "Reddit Answer",
                "Quora Answer",
                "Short Video",
                "Email Newsletter",
            },
        )

    def test_priorities_match_docs(self):
        self.assertEqual(PRIORITIES, {"High", "Medium", "Low"})


class ExtractFromPainSignalsTests(unittest.TestCase):
    """Per-signal extraction preserving source ids (spec §2.A4 / §3 test row)."""

    def test_yields_at_least_one_opportunity_with_non_empty_source_id(self):
        # The mandatory acceptance case (spec §3): rule-based extraction from
        # sample pain signals yields >=1 opportunity, each with a non-empty
        # source id.
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        self.assertGreaterEqual(len(opportunities), 1)
        for opp in opportunities:
            ids = [opp.get("source_lead_id", ""), opp.get("source_conversation_id", "")]
            self.assertTrue(any(ids), "opportunity missing a non-empty source id: %r" % opp)

    def test_shipping_signal_maps_to_shipping_pain(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        shipping = [o for o in opportunities if o["Pain Point"] == "Shipping"]
        self.assertTrue(shipping, "expected a Shipping opportunity")
        self.assertEqual(shipping[0]["source_lead_id"], "LEAD-20260621-0001")

    def test_supplier_signal_maps_to_supplier_pain(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        supplier = [o for o in opportunities if o["Pain Point"] == "Supplier"]
        self.assertTrue(supplier)
        self.assertEqual(supplier[0]["source_lead_id"], "LEAD-20260621-0002")

    def test_packaging_signal_maps_to_packaging_pain(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        packaging = [o for o in opportunities if o["Pain Point"] == "Packaging"]
        self.assertTrue(packaging)

    def test_conversation_source_id_preserved(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        conv = [o for o in opportunities if o.get("source_conversation_id") == "CONV-20260621-0007"]
        # First matching pain keyword in the message is "MOQ" -> that wins.
        self.assertTrue(conv)
        self.assertEqual(conv[0]["Pain Point"], "MOQ")

    def test_signal_without_source_id_is_skipped(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        for opp in opportunities:
            # Spec §2.A4: every opportunity MUST carry a non-empty source id.
            # A conversation-sourced opp may legitimately have an empty
            # source_lead_id, so the contract is "at least one id non-empty".
            ids = [opp.get("source_lead_id", ""), opp.get("source_conversation_id", "")]
            self.assertTrue(any(ids), "anonymous signal leaked into output: %r" % opp)

    def test_signal_without_pain_keyword_is_skipped(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        ids = {o.get("source_lead_id") for o in opportunities}
        self.assertNotIn("LEAD-20260621-0009", ids)

    def test_each_opportunity_has_all_required_fields(self):
        opportunities = extract_from_pain_signals(SAMPLE_PAIN_SIGNALS)
        for opp in opportunities:
            for field in (
                "source_lead_id",
                "source_conversation_id",
                "Pain Point",
                "Topic",
                "Search Intent",
                "Recommended Format",
                "Priority",
                "Draft Brief",
            ):
                self.assertIn(field, opp, "missing field %s" % field)
            self.assertIn(opp["Pain Point"], PAIN_POINTS)
            self.assertIn(opp["Search Intent"], SEARCH_INTENTS)
            self.assertIsInstance(opp["Recommended Format"], list)
            self.assertGreater(len(opp["Recommended Format"]), 0)
            for fmt in opp["Recommended Format"]:
                self.assertIn(fmt, RECOMMENDED_FORMATS)
            self.assertIn(opp["Priority"], PRIORITIES)
            self.assertTrue(opp["Draft Brief"])
            # Rule-based path is always human-review-gated (spec §0 rule 6).
            self.assertTrue(opp["review_needed"])

    def test_explicit_pain_point_on_signal_used_when_no_keyword(self):
        # When the signal has no keyword in evidence but an explicit Pain
        # Point, we still extract (do not lose the human-tagged pain).
        signal = [
            {
                "source_lead_id": "LEAD-X-1",
                "Pain Point": "Price",
                "evidence_text": "General chat, no keywords here.",
            }
        ]
        opportunities = extract_from_pain_signals(signal)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["Pain Point"], "Price")

    def test_non_list_input_returns_empty(self):
        self.assertEqual(extract_from_pain_signals("not a list"), [])  # type: ignore[arg-type]
        self.assertEqual(extract_from_pain_signals(None), [])  # type: ignore[arg-type]

    def test_title_case_source_keys_accepted(self):
        # Callers may pass docs/02 Title Case keys directly.
        signal = [
            {
                "Lead ID": "LEAD-TC-1",
                "Pain Signal": "quality control issues",
                "Evidence Text": "Defect rate too high.",
            }
        ]
        opportunities = extract_from_pain_signals(signal)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["source_lead_id"], "LEAD-TC-1")
        self.assertEqual(opportunities[0]["Pain Point"], "QC")


class FormatNormalizationTests(unittest.TestCase):
    def test_alias_canonicalization(self):
        self.assertEqual(_normalize_format_list(["blog", "video"]), ["SEO Blog", "Short Video"])

    def test_comma_string_split(self):
        self.assertEqual(
            _normalize_format_list("SEO Blog / LinkedIn"),
            ["SEO Blog", "LinkedIn"],
        )

    def test_empty_falls_back_to_seo_blog(self):
        self.assertEqual(_normalize_format_list([]), ["SEO Blog"])
        self.assertEqual(_normalize_format_list("garbage"), ["SEO Blog"])


class ExtractContentOpportunitiesTests(unittest.TestCase):
    """Top-level extractor: rule-based path (no AI key in test env)."""

    def setUp(self):
        # Hermetic: strip any real AI key (e.g. GLM via ANTHROPIC_API_KEY) so
        # these tests exercise the deterministic rule-based path regardless of
        # the environment, matching the test_run_pipeline pattern.
        self._prev_openai = os.environ.pop("OPENAI_API_KEY", None)
        self._prev_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        if self._prev_openai is not None:
            os.environ["OPENAI_API_KEY"] = self._prev_openai
        if self._prev_anthropic is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._prev_anthropic

    def test_lead_records_extract_to_opportunities(self):
        records = [
            {
                "Lead ID": "LEAD-20260621-0001",
                "Pain Signal": "shipping delay",
                "Evidence Text": "Tracking broken, 3 week delivery.",
            },
            {
                "Lead ID": "LEAD-20260621-0002",
                "Pain Signal": "sourcing",
                "Evidence Text": "Need a better supplier in China.",
            },
        ]
        opportunities = extract_content_opportunities(records, ai_enabled=False)
        self.assertEqual(len(opportunities), 2)
        pains = {o["Pain Point"] for o in opportunities}
        self.assertEqual(pains, {"Shipping", "Supplier"})

    def test_conversation_source_type(self):
        records = [
            {
                "Conversation ID": "CONV-1",
                "Lead ID": "LEAD-1",
                "Message Content": "Your packaging options look limited, can we do custom boxes?",
            }
        ]
        opportunities = extract_content_opportunities(records, source_type="conversation", ai_enabled=False)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["Pain Point"], "Packaging")
        self.assertEqual(opportunities[0]["source_conversation_id"], "CONV-1")
        self.assertEqual(opportunities[0]["source_lead_id"], "LEAD-1")

    def test_ai_enabled_with_no_key_falls_back_to_rule_based(self):
        # ai_enabled=True but no key configured -> must NOT crash, must fall
        # back to rule-based extraction with review_needed=True (spec §0 rule 6).
        records = [
            {
                "Lead ID": "LEAD-NOAI-1",
                "Pain Signal": "moq too high",
                "Evidence Text": "Can't meet minimum order quantity.",
            }
        ]
        opportunities = extract_content_opportunities(records, ai_enabled=True)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["Pain Point"], "MOQ")
        self.assertTrue(opportunities[0]["review_needed"])

    def test_ai_enabled_none_uses_key_detection(self):
        # With no env key set in the test runner, None should resolve to
        # rule-based (deterministic) extraction. Use evidence text that only
        # matches the Scaling keyword (avoid "fulfillment"/"shipping" which
        # would win under _PAIN_KEYWORDS ordering).
        records = [
            {
                "Lead ID": "LEAD-AUTO-1",
                "Pain Signal": "scaling growth",
                "Evidence Text": "Store is growing fast and we want to scale.",
            }
        ]
        opportunities = extract_content_opportunities(records)  # ai_enabled=None
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["Pain Point"], "Scaling")

    def test_records_without_source_id_skipped(self):
        records = [
            {"Pain Signal": "shipping delay", "Evidence Text": "no id here"},
            {"Lead ID": "LEAD-OK", "Pain Signal": "shipping delay", "Evidence Text": "has id"},
        ]
        opportunities = extract_content_opportunities(records, ai_enabled=False)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["source_lead_id"], "LEAD-OK")

    def test_non_list_records_returns_empty(self):
        self.assertEqual(extract_content_opportunities("nope"), [])  # type: ignore[arg-type]
        self.assertEqual(extract_content_opportunities(None), [])  # type: ignore[arg-type]

    def test_priority_signal_overrides_recipe(self):
        # An explicit Priority on the record should win over the recipe default.
        signal = [
            {
                "source_lead_id": "LEAD-P-1",
                "pain_signal": "shipping delay",
                "evidence_text": "Minor delay, not urgent.",
                "priority": "Low",
            }
        ]
        opportunities = extract_from_pain_signals(signal)
        self.assertEqual(opportunities[0]["Priority"], "Low")


class _FakeContentClient:
    """Records create_record calls; can inject failures by 0-based CALL index.

    Uses a monotonic call counter (not len(created)) so a failed call still
    advances the index — otherwise a retry-like re-entry at the same length
    would re-trigger the failure.
    """

    def __init__(self, *, create_fail_indices=()):
        self.created = []
        self.create_fail_indices = set(create_fail_indices)
        self._calls = 0

    def create_record(self, table_id, fields):
        call_index = self._calls
        self._calls += 1
        if call_index in self.create_fail_indices:
            raise RuntimeError("simulated Feishu error")
        record = {"record_id": "rec%d" % (len(self.created) + 1), "fields": fields}
        self.created.append((table_id, fields))
        return record


def _content_config():
    # Real config with only the content table id populated.
    return RuntimeConfig(table_ids={"content": "tblCONTENT"})


class BuildContentFieldsTests(unittest.TestCase):
    """Map an opportunity dict -> Content Opportunity Feishu field dict (docs/02 §6.6)."""

    def _sample_opp(self):
        return {
            "source_lead_id": "LEAD-20260621-0001",
            "source_conversation_id": "",
            "Pain Point": "Shipping",
            "Topic": "Shipping: tracking broken, 3-week delivery",
            "Search Intent": "Problem",
            "Recommended Format": ["SEO Blog", "Short Video"],
            "Priority": "High",
            "Draft Brief": "Common shipping delays and how to fix them.",
            "review_needed": True,
        }

    def test_maps_to_pascal_case_feishu_fields(self):
        fields = build_content_fields(self._sample_opp(), 1, "20260621")
        self.assertEqual(fields["Content ID"], "CTNT-20260621-0001")
        self.assertEqual(fields["Source Lead ID"], "LEAD-20260621-0001")
        self.assertEqual(fields["Pain Point"], "Shipping")
        self.assertEqual(fields["Topic"], "Shipping: tracking broken, 3-week delivery")
        self.assertEqual(fields["Search Intent"], "Problem")
        self.assertEqual(fields["Recommended Format"], ["SEO Blog", "Short Video"])
        self.assertEqual(fields["Priority"], "High")
        self.assertEqual(fields["Draft Brief"], "Common shipping delays and how to fix them.")
        self.assertEqual(fields["Status"], "Idea")  # new content idea default
        self.assertEqual(fields["Owner"], "")  # unassigned until a human picks it up

    def test_content_id_zero_pads_and_increments(self):
        fields_a = build_content_fields(self._sample_opp(), 7, "20260621")
        fields_b = build_content_fields(self._sample_opp(), 42, "20260622")
        self.assertEqual(fields_a["Content ID"], "CTNT-20260621-0007")
        self.assertEqual(fields_b["Content ID"], "CTNT-20260622-0042")

    def test_conversation_sourced_opportunity_maps_source_ids(self):
        opp = self._sample_opp()
        opp["source_lead_id"] = ""
        opp["source_conversation_id"] = "CONV-20260621-0007"
        fields = build_content_fields(opp, 1, "20260621")
        self.assertEqual(fields["Source Lead ID"], "")
        self.assertEqual(fields["Source Conversation ID"], "CONV-20260621-0007")


class WriteOpportunitiesToFeishuTests(unittest.TestCase):
    """write_opportunities_to_feishu: create-only writes (each idea = new row)."""

    def test_writes_one_record_per_opportunity(self):
        client = _FakeContentClient()
        opps = [extract_from_pain_signals([{
            "source_lead_id": "LEAD-1", "pain_signal": "shipping delay", "evidence_text": "x",
        }])[0]]
        opps.append(extract_from_pain_signals([{
            "source_lead_id": "LEAD-2", "pain_signal": "moq", "evidence_text": "y",
        }])[0])
        report = write_opportunities_to_feishu(opps, client, _content_config(), date_str="20260621")
        self.assertEqual(report["written"], 2)
        self.assertEqual(len(client.created), 2)
        self.assertEqual(client.created[0][0], "tblCONTENT")  # correct table id
        self.assertEqual(client.created[0][1]["Content ID"], "CTNT-20260621-0001")
        self.assertEqual(client.created[1][1]["Content ID"], "CTNT-20260621-0002")
        self.assertEqual(len(report["record_ids"]), 2)

    def test_omits_falsy_empty_fields_so_feishu_typed_fields_do_not_reject(self):
        # A conversation-sourced opp has an empty Source Lead ID; the write must
        # OMIT that key (not send "") so the Relation/Text field is not rejected.
        client = _FakeContentClient()
        opp = extract_from_pain_signals([{
            "source_conversation_id": "CONV-1", "message_content": "shipping delay",
        }])[0]
        write_opportunities_to_feishu([opp], client, _content_config(), date_str="20260621")
        written_fields = client.created[0][1]
        self.assertNotIn("Source Lead ID", written_fields)
        self.assertIn("Source Conversation ID", written_fields)

    def test_continues_on_per_record_error_and_reports_it(self):
        # The 2nd create fails; the 1st and 3rd must still land, and the error
        # recorded (never crash the whole batch on one bad row).
        client = _FakeContentClient(create_fail_indices=(1,))
        opps = [
            {"source_lead_id": "LEAD-1", "Pain Point": "Shipping", "Topic": "t",
             "Search Intent": "Problem", "Recommended Format": ["SEO Blog"],
             "Priority": "High", "Draft Brief": "b"},
            {"source_lead_id": "LEAD-2", "Pain Point": "QC", "Topic": "t",
             "Search Intent": "How-to", "Recommended Format": ["SEO Blog"],
             "Priority": "Medium", "Draft Brief": "b"},
            {"source_lead_id": "LEAD-3", "Pain Point": "Price", "Topic": "t",
             "Search Intent": "Comparison", "Recommended Format": ["SEO Blog"],
             "Priority": "Medium", "Draft Brief": "b"},
        ]
        report = write_opportunities_to_feishu(opps, client, _content_config(), date_str="20260621")
        self.assertEqual(report["written"], 2)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["total"], 3)


if __name__ == "__main__":
    unittest.main()
