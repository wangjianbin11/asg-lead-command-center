"""Tests for scripts/crawl_leads.py — Shopify public-data lead crawler.

Hermetic: NO network access anywhere. ``enrich_store`` is monkeypatched so the
tests never touch the internet. A FakeClient mirrors the recording-client
pattern used in tests/test_feishu_client.py.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crawl_leads  # noqa: E402


# --- sample public data -------------------------------------------------------

SAMPLE_PRODUCTS_JSON = json.dumps(
    {
        "products": [
            {
                "title": "Wool Runners",
                "tags": ["shoes", "footwear", "sustainable"],
                "body_html": "We ship worldwide with fast logistics.",
                "vendor": "Demo Brand",
            },
            {
                "title": "Eco T-Shirt",
                "tags": ["apparel", "organic"],
                "body_html": "Custom packaging available for wholesale.",
                "vendor": "Demo Brand",
            },
        ]
    }
)

SAMPLE_HOMEPAGE_HTML = (
    "<!doctype html><html lang=\"en-US\"><head>"
    "<meta property=\"og:site_name\" content=\"Demo Brand Store\" />"
    "<title>Demo Brand Store - Sustainable Apparel</title>"
    "<meta name=\"description\" content=\"Worldwide shipping and fulfillment.\" />"
    "</head><body>"
    "<a href=\"mailto:hello@demobrand.com\">Contact us</a>"
    "<a href=\"https://instagram.com/demobrand\">IG</a>"
    "<a href=\"https://facebook.com/demobrand\">FB</a>"
    "<a href=\"https://tiktok.com/@demobrand\">TT</a>"
    "<a href=\"https://x.com/demobrand\">X</a>"
    "<address>Brooklyn, NY, USA</address>"
    "</body></html>"
)


class ParseProductsJsonTests(unittest.TestCase):
    def test_parses_product_count_and_niche(self):
        parsed = crawl_leads._parse_products_json(SAMPLE_PRODUCTS_JSON)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["product_count"], 2)
        # Niche / category derived from tag + title words.
        self.assertTrue(parsed["category"])
        # Text blob scanned for pain signals.
        self.assertIn("product_text", parsed)

    def test_returns_none_on_invalid_json(self):
        self.assertIsNone(crawl_leads._parse_products_json("not json"))
        self.assertIsNone(crawl_leads._parse_products_json('{"foo": "bar"}'))
        self.assertIsNone(crawl_leads._parse_products_json('{"products": []}'))


class ParseHomepageTests(unittest.TestCase):
    def test_extracts_site_name_email_socials_country(self):
        parsed = crawl_leads._parse_homepage(SAMPLE_HOMEPAGE_HTML)
        # og:site_name wins over <title>.
        self.assertEqual(parsed["site_name"], "Demo Brand Store")
        self.assertEqual(parsed["email"], "hello@demobrand.com")
        socials = parsed["social_links"]
        self.assertIn("instagram", socials)
        self.assertIn("facebook", socials)
        self.assertIn("tiktok", socials)
        self.assertIn("x", socials)
        # Country derived from <html lang="en-US"> -> US.
        self.assertEqual(parsed["country"], "US")

    def test_falls_back_to_title_when_no_og_site_name(self):
        html = "<html lang=\"fr\"><head><title>Other Shop</title></head><body></body></html>"
        parsed = crawl_leads._parse_homepage(html)
        self.assertEqual(parsed["site_name"], "Other Shop")

    def test_handles_empty_homepage(self):
        parsed = crawl_leads._parse_homepage("")
        self.assertEqual(parsed["site_name"], "")
        self.assertEqual(parsed["email"], "")
        self.assertEqual(parsed["social_links"], {})
        self.assertEqual(parsed["country"], "")


class DetectPainTests(unittest.TestCase):
    def test_finds_shipping_and_packaging_keywords(self):
        pains = crawl_leads._detect_pain(
            "We struggle with shipping delays and need custom packaging for our brand."
        )
        # Both shipping + packaging should be detected (order-independent).
        self.assertIn("shipping", pains)
        self.assertIn("packaging", pains)

    def test_finds_sourcing_and_qc(self):
        pains = crawl_leads._detect_pain(
            "Looking for a new sourcing agent; QC has been poor."
        )
        self.assertIn("sourcing", pains)
        self.assertIn("qc", pains)

    def test_empty_text_yields_empty_list(self):
        self.assertEqual(crawl_leads._detect_pain(""), [])


class LeadToLeadPoolFieldsTests(unittest.TestCase):
    def test_maps_with_status_new_and_crawler_source(self):
        lead = {
            "company_name": "Demo Brand Store",
            "website_url": "https://demobrand.com",
            "source_url": "https://demobrand.com/products.json",
            "country": "US",
            "category": "apparel",
            "email": "hello@demobrand.com",
            "pain_signals": ["shipping", "packaging"],
            "notes": "Public crawl; product_count=2",
        }
        fields = crawl_leads.lead_to_leadpool_fields(lead, "LEAD-CRAWL-abc123")
        # Mirrors run_lead_pipeline._build_lead_pool_fields field names EXACTLY.
        self.assertEqual(fields["Lead ID"], "LEAD-CRAWL-abc123")
        self.assertEqual(fields["Company / Store Name"], "Demo Brand Store")
        self.assertEqual(fields["Platform"], "Shopify")
        self.assertEqual(fields["Country / Region"], "US")
        self.assertEqual(fields["Category"], "apparel")
        self.assertEqual(fields["Source Channel"], "Crawler")
        self.assertEqual(fields["Source URL"], "https://demobrand.com/products.json")
        self.assertEqual(fields["Status"], "New")
        # Pain Signal is the list of detected pains.
        self.assertEqual(fields["Pain Signal"], ["shipping", "packaging"])
        # Email is mirrored onto Notes / Evidence for outreach routing.
        self.assertIn("hello@demobrand.com", fields.get("Notes", ""))


class FakeClient:
    """Recording FeishuClient double (mirrors tests/test_feishu_client.py)."""

    def __init__(self, existing_records=None):
        self.created = []
        # existing_records: list of {"fields": {...}} dicts already in Lead Pool.
        self.listed = list(existing_records or [])

    def list_records(self, table_id, **kwargs):
        return list(self.listed)

    def create_record(self, table_id, fields):
        record = {"record_id": "rec-%d" % (len(self.created) + 1), "fields": dict(fields)}
        self.created.append((table_id, fields))
        return record


class ExistingWebsiteDomainsTests(unittest.TestCase):
    def test_returns_set_of_website_domains(self):
        records = [
            {"fields": {"Website URL": {"link": "https://allbirds.com/"}}},
            {"fields": {"Website URL": "https://gymshark.com"}},
            {"fields": {"Website URL": ""}},  # missing -> skipped
        ]
        domains = crawl_leads.existing_website_domains(FakeClient(records), "tblXXX")
        self.assertIn("allbirds.com", domains)
        self.assertIn("gymshark.com", domains)
        self.assertNotIn("", domains)


class CrawlDomainsTests(unittest.TestCase):
    def test_crawl_uses_fakeclient_and_skips_existing(self):
        # enrich_store is monkeypatched so NO network is touched.
        def fake_enrich(domain):
            return {
                "company_name": "Demo Brand Store",
                "website_url": "https://%s" % domain,
                "platform": "Shopify",
                "source_channel": "Crawler",
                "source_url": "https://%s/products.json" % domain,
                "country": "US",
                "category": "apparel",
                "email": "hello@%s" % domain,
                "pain_signals": ["shipping"],
                "notes": "Public crawl",
            }

        original = crawl_leads.enrich_store
        crawl_leads.enrich_store = fake_enrich
        try:
            # 'existing.com' is already in Lead Pool -> skipped.
            client = FakeClient(existing_records=[
                {"fields": {"Website URL": "https://existing.com"}},
            ])
            result = crawl_leads.crawl_domains(
                ["newstore.com", "existing.com"],
                client=client,
                write_feishu=True,
                lead_table_id="tblXXX",
            )
        finally:
            crawl_leads.enrich_store = original

        summary = result["summary"]
        self.assertEqual(summary["total_domains"], 2)
        self.assertEqual(summary["enriched"], 1)
        self.assertEqual(summary["skipped_existing"], 1)
        self.assertEqual(len(result["leads"]), 1)
        # Only one record written to Feishu.
        self.assertEqual(len(client.created), 1)
        _, written_fields = client.created[0]
        self.assertEqual(written_fields["Status"], "New")
        self.assertEqual(written_fields["Source Channel"], "Crawler")
        self.assertEqual(written_fields["Platform"], "Shopify")
        self.assertTrue(written_fields["Lead ID"].startswith("LEAD-CRAWL-"))

    def test_crawl_dry_run_does_not_write_feishu(self):
        def fake_enrich(domain):
            return {
                "company_name": "Demo Brand Store",
                "website_url": "https://%s" % domain,
                "platform": "Shopify",
                "source_channel": "Crawler",
                "source_url": "https://%s/products.json" % domain,
                "country": "US",
                "category": "apparel",
                "email": "",
                "pain_signals": [],
                "notes": "",
            }

        original = crawl_leads.enrich_store
        crawl_leads.enrich_store = fake_enrich
        try:
            client = FakeClient()
            result = crawl_leads.crawl_domains(
                ["newstore.com"], client=client, write_feishu=False
            )
        finally:
            crawl_leads.enrich_store = original

        self.assertEqual(len(result["leads"]), 1)
        self.assertEqual(client.created, [])  # nothing written

    def test_crawl_lead_id_is_idempotent(self):
        """Re-running the same domain produces the SAME Lead ID (idempotent)."""

        def fake_enrich(domain):
            return {
                "company_name": "Demo",
                "website_url": "https://%s" % domain,
                "platform": "Shopify",
                "source_channel": "Crawler",
                "source_url": "https://%s/products.json" % domain,
                "country": "US",
                "category": "x",
                "email": "",
                "pain_signals": [],
                "notes": "",
            }

        original = crawl_leads.enrich_store
        crawl_leads.enrich_store = fake_enrich
        try:
            r1 = crawl_leads.crawl_domains(["allbirds.com"], client=FakeClient())
            r2 = crawl_leads.crawl_domains(["allbirds.com"], client=FakeClient())
        finally:
            crawl_leads.enrich_store = original

        self.assertEqual(r1["leads"][0]["Lead ID"], r2["leads"][0]["Lead ID"])


if __name__ == "__main__":
    unittest.main()
