import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_lead_pipeline import (  # noqa: E402
    generate_lead_id,
    run_pipeline,
)


# A fake Feishu client that records every call. Used to PROVE that dry_run
# never touches Feishu even when a client is supplied.
class RecordingClient:
    def __init__(self):
        self.create_calls = []
        self.update_calls = []

    def create_record(self, table_id, fields):
        self.create_calls.append((table_id, fields))
        return {"record_id": "rec-%d" % (len(self.create_calls))}

    def update_record(self, table_id, record_id, fields):
        self.update_calls.append((table_id, record_id, fields))
        return {"record": {"record_id": record_id, "fields": fields}}


def _write_csv(path: Path, rows):
    """Write a small CSV with the same header shape as sample_leads.csv."""
    fieldnames = [
        "lead_id",
        "company_name",
        "website_url",
        "source_channel",
        "source_url",
        "notes",
        "country",
        "platform",
        "category",
        "email",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


class GenerateLeadIdTests(unittest.TestCase):
    def test_format_is_zero_padded_and_dated(self):
        self.assertEqual(generate_lead_id(1, "20260621"), "LEAD-20260621-0001")
        self.assertEqual(generate_lead_id(42, "20260621"), "LEAD-20260621-0042")

    def test_rejects_non_positive_index(self):
        with self.assertRaises(ValueError):
            generate_lead_id(0, "20260621")

    def test_rejects_empty_date(self):
        with self.assertRaises(ValueError):
            generate_lead_id(1, "")


class RunPipelineDryRunTests(unittest.TestCase):
    def setUp(self):
        # Force the AI path OFF for the unit tests so we never attempt a real
        # network call even if the dev machine happens to have a key set.
        self._prev_openai = os.environ.pop("OPENAI_API_KEY", None)
        self._prev_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        if self._prev_openai is not None:
            os.environ["OPENAI_API_KEY"] = self._prev_openai
        if self._prev_anthropic is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._prev_anthropic

    def _make_csv(self, rows):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        tmp.close()
        path = Path(tmp.name)
        _write_csv(path, rows)
        self.addCleanup(path.unlink)
        return path

    def test_dry_run_returns_counts_and_result_shape(self):
        rows = [
            {
                "company_name": "Northstar Socks",
                "website_url": "https://www.northstarsocks.example/products/compression",
                "source_channel": "Manual",
                "source_url": "https://reddit.example/thread/shipping-delay",
                "notes": "Shopify store mentions shipping delay and custom packaging interest.",
                "country": "US",
                "platform": "Shopify",
                "category": "Compression socks",
                "email": "ops@northstarsocks.example",
            }
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True)

        # Required top-level keys per spec §2.A2.
        self.assertIn("summary", result)
        self.assertIn("leads", result)
        self.assertIn("scores", result)
        self.assertIn("outreach_tasks", result)
        self.assertTrue(result["dry_run"])

        summary = result["summary"]
        self.assertEqual(summary["input_rows"], 1)
        self.assertEqual(summary["cleaned"], 1)
        self.assertEqual(summary["duplicates"], 0)
        self.assertEqual(summary["unique_leads"], 1)
        self.assertEqual(summary["new_leads"], 1)
        self.assertEqual(summary["scored"], 1)
        self.assertTrue(summary["dry_run"])
        # No AI key configured in setUp -> heuristic path, ai_enabled False.
        self.assertFalse(summary["ai_enabled"])

    def test_dry_run_never_calls_feishu_even_with_client(self):
        rows = [
            {
                "company_name": "Brand X",
                "website_url": "https://brandx.example",
                "source_channel": "Manual",
                "notes": "shipping delay and sourcing",
                "country": "US",
                "platform": "Shopify",
                "email": "owner@brandx.example",
            }
        ]
        path = self._make_csv(rows)
        client = RecordingClient()

        result = run_pipeline(str(path), client=client, dry_run=True, write_feishu=True)

        # dry_run MUST win: no Feishu writes despite write_feishu=True + client.
        self.assertEqual(client.create_calls, [])
        self.assertEqual(client.update_calls, [])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["summary"]["write_feishu"])

    def test_ab_lead_with_contact_yields_pending_review_not_sent_task(self):
        rows = [
            {
                "company_name": "High Fit Store",
                "website_url": "https://highfit.example",
                "source_channel": "Manual",
                "notes": "Shopify brand. shipping delay, sourcing, custom packaging, supplier issue.",
                "country": "US",
                "platform": "Shopify",
                "category": "Apparel",
                "email": "founder@highfit.example",
            }
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True)

        # The heuristic should rank this lead A or B (tokens hit many high-value
        # signals). Regardless of which, an A/B lead with an email must yield a
        # task with the two draft-only safety statuses. Priority lives on the
        # Lead Pool entry (docs/02 §6.1) — the Lead Scoring table has no
        # Priority field of its own.
        self.assertIn(result["leads"][0]["Priority"], {"A", "B"})
        self.assertGreaterEqual(len(result["outreach_tasks"]), 1)

        task = result["outreach_tasks"][0]
        self.assertEqual(task["Approval Status"], "Pending Review")
        self.assertEqual(task["Send Status"], "Not Sent")
        self.assertEqual(task["Channel"], "Email")
        self.assertTrue(task["AI Draft"].strip())
        # Lead ID + Task ID must be traceable.
        self.assertTrue(task["Lead ID"])
        self.assertTrue(task["Task ID"])

    def test_ab_lead_without_contact_creates_no_task(self):
        rows = [
            {
                "company_name": "No Contact Store",
                "website_url": "https://nocontact.example",
                "source_channel": "Manual",
                "notes": "Shopify brand with shipping delay sourcing custom packaging supplier issue",
                "country": "US",
                "platform": "Shopify",
                # no email / linkedin / whatsapp
            }
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True)

        self.assertIn(result["leads"][0]["Priority"], {"A", "B"})
        self.assertEqual(result["outreach_tasks"], [])

    def test_duplicate_rows_are_skipped_from_unique_leads(self):
        rows = [
            {
                "company_name": "Dup Store",
                "website_url": "https://dupstore.example",
                "source_channel": "Manual",
                "notes": "shipping delay",
                "country": "US",
                "platform": "Shopify",
                "email": "a@dupstore.example",
            },
            {
                "company_name": "Dup Store",
                "website_url": "https://dupstore.example",
                "source_channel": "Google",
                "notes": "duplicate",
                "country": "US",
                "platform": "Shopify",
                "email": "b@dupstore.example",
            },
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True)

        self.assertEqual(result["summary"]["input_rows"], 2)
        self.assertEqual(result["summary"]["duplicates"], 1)
        self.assertEqual(result["summary"]["unique_leads"], 1)
        self.assertEqual(len(result["leads"]), 1)

    def test_need_manual_check_leads_are_not_scored(self):
        # Missing website_url -> clean_leads marks status "Need Manual Check",
        # which the pipeline must skip (only Status == "New" gets scored).
        rows = [
            {
                "company_name": "No Website",
                "website_url": "",
                "source_channel": "Manual",
                "notes": "missing website",
                "country": "US",
                "platform": "Unknown",
                "email": "x@example.com",
            }
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True)

        self.assertEqual(result["summary"]["new_leads"], 0)
        self.assertEqual(result["summary"]["scored"], 0)
        self.assertEqual(result["scores"], [])

    def test_no_ai_flag_forces_heuristic_review(self):
        rows = [
            {
                "company_name": "Forced Heuristic",
                "website_url": "https://forced.example",
                "source_channel": "Manual",
                "notes": "shipping delay sourcing",
                "country": "US",
                "platform": "Shopify",
                "email": "a@forced.example",
            }
        ]
        path = self._make_csv(rows)

        result = run_pipeline(str(path), dry_run=True, ai_enabled=False)

        self.assertFalse(result["summary"]["ai_enabled"])
        # Heuristic path always sets review_needed=True (spec §0 rule 6).
        self.assertTrue(result["scores"][0]["Review Needed"])


class RunPipelineFieldShapeTests(unittest.TestCase):
    def test_lead_pool_fields_match_docs_02(self):
        rows = [
            {
                "company_name": "Shape Check",
                "website_url": "https://shape.example",
                "source_channel": "Manual",
                "notes": "shipping delay",
                "country": "US",
                "platform": "Shopify",
                "category": "Apparel",
                "email": "a@shape.example",
            }
        ]
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        tmp.close()
        path = Path(tmp.name)
        _write_csv(path, rows)
        self.addCleanup(path.unlink)

        result = run_pipeline(str(path), dry_run=True)

        lead = result["leads"][0]
        # Spot-check the exact field names from docs/02 §6.1.
        for key in (
            "Lead ID",
            "Company / Store Name",
            "Website URL",
            "Platform",
            "Country / Region",
            "ASG Fit Score",
            "Priority",
            "Status",
        ):
            self.assertIn(key, lead)
        self.assertEqual(lead["Status"], "Scored")

        score = result["scores"][0]
        for key in (
            "Score ID",
            "Lead ID",
            "Total Score",
            "Sourcing Need Score",
            "Main Pain Point",
            "Recommended Offer",
            "Review Needed",
        ):
            self.assertIn(key, score)


if __name__ == "__main__":
    unittest.main()
