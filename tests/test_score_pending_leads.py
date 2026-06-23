"""Hermetic tests for the Lead-Pool-driven scorer.

These tests read NO network and use NO real AI key. They seed a FakeClient
with Lead Pool rows, run the scorer in dry_run=False (writing to the fake),
and assert the loop is state-driven and idempotent:

* only Status == "New" leads are scored
* one Lead Scoring record is written per scored lead
* each Lead Pool row is updated: ASG Fit Score, Priority, Status -> "Scored"
* Status != "New" rows are skipped
* a failing score is captured in errors and never aborts the batch
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_lead_pipeline import _score_one_lead  # noqa: E402
from score_pending_leads import (  # noqa: E402
    fetch_pending,
    score_pending_leads,
)


LEAD_TABLE = "tblLeadPool"
SCORE_TABLE = "tblLeadScoring"


def _lead_pool_fields(
    company,
    *,
    website="https://store.example",
    platform="Shopify",
    country="US",
    category="Apparel",
    notes="Shopify brand. shipping delay, sourcing, custom packaging.",
    status="New",
    lead_id="",
):
    """Build a Lead Pool field dict using the exact docs/02 §6.1 field names."""
    return {
        "Lead ID": lead_id or "LEAD-20260621-0001",
        "Company / Store Name": company,
        "Website URL": {"link": website},
        "Platform": platform,
        "Country / Region": country,
        "Category": category,
        "Source Channel": "Manual",
        "Source URL": "",
        "Pain Signal": [],
        "Evidence Text": notes,
        "Estimated Stage": "Unknown",
        "Estimated Order Volume": "Unknown",
        "Current Supplier Guess": "",
        "ASG Fit Score": None,
        "Priority": "",
        "Status": status,
        "Owner": "",
        "Notes": notes,
    }


class FakeConfig:
    """Stand-in for RuntimeConfig: returns canned table ids."""

    def __init__(self, lead=LEAD_TABLE, score=SCORE_TABLE):
        self._ids = {"lead": lead, "score": score}

    def table_id(self, name):
        return self._ids[name]


class FakeClient:
    """Records every Feishu call and serves seeded Lead Pool rows.

    list_records honors the spec's preferred filter_expression
    ``CurrentValue.[Status]==New``: when it is passed, only New rows are
    returned (server-side filter emulation). When the caller requests no
    filter, all rows are returned so the client-side fallback path is
    exercised.
    """

    def __init__(self, rows):
        # rows: list of {'record_id':..., 'fields':...}
        self._rows = list(rows)
        self.create_calls = []
        self.update_calls = []
        self.list_calls = []

    def list_records(self, table_id, filter_expression=None, **kwargs):
        self.list_calls.append((table_id, filter_expression))
        if filter_expression and "Status" in filter_expression and "New" in filter_expression:
            return [r for r in self._rows if r["fields"].get("Status") == "New"]
        return list(self._rows)

    def iter_records(self, table_id, filter_expression=None, **kwargs):
        # Fallback path: never server-filters; returns every row.
        for r in self._rows:
            yield r

    def create_record(self, table_id, fields):
        self.create_calls.append((table_id, fields))
        rid = "recScore-%d" % (len(self.create_calls))
        return {"record_id": rid, "fields": fields}

    def update_record(self, table_id, record_id, fields):
        self.update_calls.append((table_id, record_id, fields))
        return {"record": {"record_id": record_id, "fields": fields}}


class FailingScoreClient(FakeClient):
    """A FakeClient whose first New lead has fields that make scoring raise.

    We inject the failure by monkeypatching _score_one_lead at the module
    level inside the test instead; this subclass only exists to make the
    intent obvious. Kept for symmetry with the other fakes.
    """


class FetchPendingTests(unittest.TestCase):
    def test_returns_only_new_leads_via_server_filter(self):
        rows = [
            {"record_id": "r1", "fields": _lead_pool_fields("New Co", status="New")},
            {"record_id": "r2", "fields": _lead_pool_fields("Done Co", status="Scored")},
        ]
        client = FakeClient(rows)
        pending = fetch_pending(client, LEAD_TABLE)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["record_id"], "r1")
        self.assertEqual(pending[0]["fields"]["Status"], "New")
        # The preferred server-side filter must have been requested.
        self.assertTrue(client.list_calls)
        _, filt = client.list_calls[0]
        self.assertIsNotNone(filt)

    def test_falls_back_to_client_side_filter_on_error(self):
        class NoServerFilter:
            def __init__(self, rows):
                self._rows = rows
                self.iter_calls = 0

            def list_records(self, table_id, filter_expression=None, **kwargs):
                raise RuntimeError("server filter unsupported on this base")

            def iter_records(self, table_id, **kwargs):
                self.iter_calls += 1
                for r in self._rows:
                    yield r

        rows = [
            {"record_id": "r1", "fields": _lead_pool_fields("New Co", status="New")},
            {"record_id": "r2", "fields": _lead_pool_fields("Done Co", status="Scored")},
            {"record_id": "r3", "fields": _lead_pool_fields("Skipped Co", status="Rejected")},
        ]
        client = NoServerFilter(rows)
        pending = fetch_pending(client, LEAD_TABLE)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["record_id"], "r1")


class ScorePendingLeadsTests(unittest.TestCase):
    def setUp(self):
        # Strip AI keys so ai_enabled defaults to False (heuristic), exactly
        # the way test_run_pipeline does. Determinism, no network.
        self._prev_openai = os.environ.pop("OPENAI_API_KEY", None)
        self._prev_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        self._prev_glm = os.environ.pop("GLM_API_KEY", None)
        self._prev_zai = os.environ.pop("ZHIPUAI_API_KEY", None)

    def tearDown(self):
        for key, prev in (
            ("OPENAI_API_KEY", self._prev_openai),
            ("ANTHROPIC_API_KEY", self._prev_anthropic),
            ("GLM_API_KEY", self._prev_glm),
            ("ZHIPUAI_API_KEY", self._prev_zai),
        ):
            if prev is not None:
                os.environ[key] = prev

    def _seed_client(self, statuses):
        rows = []
        for i, status in enumerate(statuses, start=1):
            rows.append(
                {
                    "record_id": "leadRec-%d" % i,
                    "fields": _lead_pool_fields(
                        "Store %d" % i,
                        status=status,
                        lead_id="LEAD-20260621-%04d" % i,
                    ),
                }
            )
        return FakeClient(rows)

    def test_scores_only_new_leads_and_writes_one_scoring_each(self):
        client = self._seed_client(["New", "Scored", "New"])
        cfg = FakeConfig()

        result = score_pending_leads(
            client, cfg, ai_enabled=False, dry_run=False
        )

        summary = result["summary"]
        self.assertEqual(summary["pending"], 2)
        self.assertEqual(summary["scored"], 2)
        self.assertEqual(summary["errors"], 0)
        self.assertFalse(summary["ai_enabled"])
        self.assertFalse(summary["dry_run"])

        # One Lead Scoring record per scored lead, on the score table.
        self.assertEqual(len(client.create_calls), 2)
        for table_id, fields in client.create_calls:
            self.assertEqual(table_id, SCORE_TABLE)
            # docs/02 §6.3 contract: these keys must exist.
            self.assertIn("Lead ID", fields)
            self.assertIn("Total Score", fields)
            self.assertIn("Risk", fields)

    def test_updates_each_lead_pool_row_status_and_score(self):
        client = self._seed_client(["New"])
        cfg = FakeConfig()

        result = score_pending_leads(
            client, cfg, ai_enabled=False, dry_run=False
        )

        self.assertEqual(len(client.update_calls), 1)
        table_id, record_id, fields = client.update_calls[0]
        self.assertEqual(table_id, LEAD_TABLE)
        self.assertEqual(record_id, "leadRec-1")
        self.assertEqual(fields["Status"], "Scored")
        # ASG Fit Score + Priority must be set (docs/02 §6.1).
        self.assertIn("ASG Fit Score", fields)
        self.assertIn(fields["Priority"], {"A", "B", "C", "D"})
        self.assertIsInstance(fields["ASG Fit Score"], int)

    def test_skips_non_new_leads(self):
        # Two Scored rows + one New. Only the New one is scored/updated.
        client = self._seed_client(["Scored", "Scored", "New"])
        cfg = FakeConfig()

        result = score_pending_leads(
            client, cfg, ai_enabled=False, dry_run=False
        )

        self.assertEqual(result["summary"]["pending"], 1)
        self.assertEqual(result["summary"]["scored"], 1)
        self.assertEqual(len(client.create_calls), 1)
        self.assertEqual(len(client.update_calls), 1)
        # The update targets the only New row (record 3).
        _, record_id, _ = client.update_calls[0]
        self.assertEqual(record_id, "leadRec-3")

    def test_failing_score_recorded_not_fatal(self):
        import score_pending_leads as mod

        client = self._seed_client(["New", "New"])
        cfg = FakeConfig()

        original = mod.run_lead_pipeline._score_one_lead
        calls = {"n": 0}

        def flaky(lead, ai_enabled):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("boom")
            return original(lead, ai_enabled)

        mod.run_lead_pipeline._score_one_lead = flaky
        try:
            result = score_pending_leads(
                client, cfg, ai_enabled=False, dry_run=False
            )
        finally:
            mod.run_lead_pipeline._score_one_lead = original

        self.assertEqual(result["summary"]["pending"], 2)
        # One failed, one succeeded.
        self.assertEqual(result["summary"]["scored"], 1)
        self.assertEqual(result["summary"]["errors"], 1)

        results = result["results"]
        statuses = sorted(r["status"] for r in results)
        self.assertEqual(statuses, ["error", "scored"])
        err = next(r for r in results if r["status"] == "error")
        self.assertIn("error", err)
        self.assertIn("boom", err["error"])

    def test_dry_run_writes_nothing_but_reports_counts(self):
        client = self._seed_client(["New", "New"])
        cfg = FakeConfig()

        result = score_pending_leads(
            client, cfg, ai_enabled=False, dry_run=True
        )

        self.assertTrue(result["summary"]["dry_run"])
        self.assertEqual(result["summary"]["pending"], 2)
        self.assertEqual(result["summary"]["scored"], 2)
        # dry_run must NEVER touch Feishu.
        self.assertEqual(client.create_calls, [])
        self.assertEqual(client.update_calls, [])


class ScoreOneLeadReuseTests(unittest.TestCase):
    """Confirms the scorer delegates to run_lead_pipeline._score_one_lead
    rather than reimplementing scoring. Verified indirectly: the score's
    `reasoning_summary` matches the heuristic signature from
    local_heuristic_score when ai_enabled=False."""

    def test_heuristic_reasoning_propagates_into_scoring_record(self):
        rows = [
            {
                "record_id": "r1",
                "fields": _lead_pool_fields(
                    "Reuse Co", notes="Shopify brand. shipping delay, sourcing."
                ),
            }
        ]
        client = FakeClient(rows)
        cfg = FakeConfig()

        result = score_pending_leads(
            client, cfg, ai_enabled=False, dry_run=False
        )

        _, fields = client.create_calls[0]
        self.assertIn("Local heuristic", fields["Reasoning Summary"])


if __name__ == "__main__":
    unittest.main()
