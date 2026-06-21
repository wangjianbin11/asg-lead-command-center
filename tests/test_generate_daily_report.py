"""Tests for scripts/generate_daily_report.py (incl. --feishu write path, spec §2.A6)."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from config import RuntimeConfig  # noqa: E402
from generate_daily_report import (  # noqa: E402
    build_report_fields,
    compute_metrics,
    write_daily_report_to_feishu,
)


class _FakeReportClient:
    """Fake Feishu client for daily-report upsert tests.

    ``records`` seeds what ``list_records`` returns (the existing table state).
    """

    def __init__(self, records=()):
        self.records = list(records)
        self.created = []
        self.updated = []

    def list_records(self, table_id, **kwargs):
        return list(self.records)

    def create_record(self, table_id, fields):
        rec = {"record_id": "recNEW", "fields": fields}
        self.created.append((table_id, fields))
        return rec

    def update_record(self, table_id, record_id, fields):
        self.updated.append((table_id, record_id, fields))
        return {"record_id": record_id, "fields": fields}


def _report_config():
    return RuntimeConfig(table_ids={"report": "tblREPORT"})


def _metrics():
    return compute_metrics(
        [{"Priority": "A", "Status": "Contact Found"},
         {"Priority": "B", "Status": "Scored"}],
        [{"Send Status": "Sent", "Result": "Need Meeting"}],
        [{"Direction": "Inbound", "Intent": "Quote Request"}],
    )


class ComputeMetricsTests(unittest.TestCase):
    """Anchor: the existing pure metric counter still behaves (docs/02 §6.7)."""

    def test_counts_basic_signals(self):
        m = _metrics()
        self.assertEqual(m["new_leads"], 2)
        self.assertEqual(m["a_leads"], 1)
        self.assertEqual(m["b_leads"], 1)
        self.assertEqual(m["messages_sent"], 1)
        self.assertEqual(m["replies"], 1)
        self.assertEqual(m["quote_requests"], 1)


class BuildReportFieldsTests(unittest.TestCase):
    """Map metrics + sections -> Daily Report field dict (docs/02 §6.7)."""

    def test_maps_metrics_to_pascal_case_int_fields(self):
        fields = build_report_fields(
            _metrics(), "2026-06-21", ["Finding A."], ["No major blocker recorded."]
        )
        for key in (
            "New Leads", "A Leads", "B Leads", "Contacts Found",
            "Outreach Drafts Generated", "Messages Sent", "Replies",
            "Quote Requests", "Meetings", "Won Deals", "Lost Deals",
        ):
            self.assertIsInstance(fields[key], int, "%s should be int" % key)
        self.assertEqual(fields["New Leads"], 2)
        self.assertEqual(fields["A Leads"], 1)
        self.assertEqual(fields["Messages Sent"], 1)

    def test_report_date_is_utc_midnight_ms_timestamp(self):
        # Feishu DateTime fields store ms-since-epoch; a date maps to UTC midnight.
        fields = build_report_fields(_metrics(), "2026-06-21", ["x"], ["y"])
        expected = int(dt.datetime(2026, 6, 21, tzinfo=dt.timezone.utc).timestamp() * 1000)
        self.assertEqual(fields["Report Date"], expected)
        self.assertNotIsInstance(fields["Report Date"], float)

    def test_text_fields_join_findings_problems_and_actions(self):
        fields = build_report_fields(
            _metrics(), "2026-06-21",
            ["Finding one.", "Finding two."],
            ["Problem one.", "Problem two."],
        )
        self.assertIn("Finding one.", fields["Main Findings"])
        self.assertIn("Finding two.", fields["Main Findings"])
        self.assertIn("Problem one.", fields["Problems"])
        self.assertTrue(fields["Tomorrow Actions"])


class WriteDailyReportTests(unittest.TestCase):
    """write_daily_report_to_feishu: upsert by Report Date."""

    def test_creates_when_no_record_for_date(self):
        client = _FakeReportClient(records=[])  # empty table
        result = write_daily_report_to_feishu(
            _metrics(), "2026-06-21", ["F."], ["P."], client, _report_config()
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(len(client.created), 1)
        self.assertEqual(client.created[0][0], "tblREPORT")
        self.assertEqual(len(client.updated), 0)

    def test_upserts_when_record_exists_for_date(self):
        existing_ms = int(dt.datetime(2026, 6, 21, tzinfo=dt.timezone.utc).timestamp() * 1000)
        existing = {"record_id": "recEXIST", "fields": {"Report Date": existing_ms}}
        client = _FakeReportClient(records=[existing])
        result = write_daily_report_to_feishu(
            _metrics(), "2026-06-21", ["F."], ["P."], client, _report_config()
        )
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["record_id"], "recEXIST")
        self.assertEqual(len(client.updated), 1)
        self.assertEqual(client.updated[0][1], "recEXIST")
        self.assertEqual(len(client.created), 0)

    def test_does_not_match_a_different_date(self):
        # A row for a different day must NOT be overwritten; a new row is created.
        other_ms = int(dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc).timestamp() * 1000)
        existing = {"record_id": "recOTHER", "fields": {"Report Date": other_ms}}
        client = _FakeReportClient(records=[existing])
        result = write_daily_report_to_feishu(
            _metrics(), "2026-06-21", ["F."], ["P."], client, _report_config()
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(len(client.created), 1)


if __name__ == "__main__":
    unittest.main()
