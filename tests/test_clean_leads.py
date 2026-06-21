import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clean_leads import (
    clean_lead,
    clean_rows,
    extract_domain,
    normalize_page_url,
    normalize_url,
    standardize_country,
    standardize_platform,
)


class CleanLeadTests(unittest.TestCase):
    # --- Case 1: URL normalization ----------------------------------------

    def test_extract_domain_normalizes_common_url_variants(self):
        # Spec §8.2 acceptance: https://www.example.com/products/a -> example.com
        # and http://example.com/ -> example.com.
        self.assertEqual(extract_domain("https://www.example.com/products/a"), "example.com")
        self.assertEqual(extract_domain("http://example.com/"), "example.com")
        self.assertEqual(extract_domain("example.com/path"), "example.com")

    def test_normalize_url_returns_root_https_url(self):
        # Root URL must drop scheme, www, and any trailing path; always https.
        self.assertEqual(normalize_url("http://www.example.com/products/a"), "https://example.com")
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com")
        self.assertEqual(normalize_url("example.com"), "https://example.com")

    def test_normalize_url_strips_www_and_upgrades_http_to_https(self):
        # www + http must collapse to https://<bare-domain> so dedup sees one form.
        self.assertEqual(normalize_url("http://www.example.com/"), "https://example.com")
        self.assertEqual(normalize_url("HTTPS://WWW.Example.com/Products"), "https://example.com")

    def test_normalize_url_empty_input_returns_empty(self):
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(normalize_url("   "), "")

    def test_extract_domain_handles_uppercase_and_port(self):
        self.assertEqual(extract_domain("HTTP://WWW.EXAMPLE.COM:8080/x"), "example.com")
        self.assertEqual(extract_domain("Example.com/Path"), "example.com")

    # --- Case 2: source URL preserves path --------------------------------

    def test_normalize_page_url_preserves_source_path(self):
        # Source URL must keep its path so the originating page stays reachable.
        self.assertEqual(
            normalize_page_url("http://www.reddit.example/thread/shipping-delay"),
            "https://reddit.example/thread/shipping-delay",
        )

    def test_normalize_page_url_strips_www_but_keeps_path_and_query(self):
        # www is dropped (canonical domain) while path + query are preserved.
        self.assertEqual(
            normalize_page_url("http://www.reddit.example/t/123?sort=new"),
            "https://reddit.example/t/123?sort=new",
        )

    def test_normalize_page_url_upgrades_to_https_without_losing_path(self):
        self.assertEqual(
            normalize_page_url("http://example.com/path/to/page"),
            "https://example.com/path/to/page",
        )

    def test_normalize_page_url_strips_trailing_slash_on_path(self):
        # A bare trailing slash is not informative; keep the page canonical.
        self.assertEqual(
            normalize_page_url("https://reddit.example/thread/abc/"),
            "https://reddit.example/thread/abc",
        )

    def test_normalize_page_url_empty_returns_empty(self):
        self.assertEqual(normalize_page_url(""), "")
        self.assertEqual(normalize_page_url("   "), "")

    # --- clean_lead / clean_rows ------------------------------------------

    def test_clean_lead_marks_missing_website_for_manual_check(self):
        cleaned = clean_lead({"company_name": "Example Store", "website_url": ""})
        self.assertFalse(cleaned["is_valid"])
        self.assertEqual(cleaned["status"], "Need Manual Check")
        self.assertIn("website_url", cleaned["missing_fields"])

    def test_clean_lead_valid_row_status_new_and_normalizes_website(self):
        cleaned = clean_lead(
            {
                "company_name": "Acme",
                "website_url": "http://www.acme.com/products/x",
                "source_channel": "Reddit",
                "source_url": "https://reddit.example/r/shipping/q1",
            }
        )
        self.assertTrue(cleaned["is_valid"])
        self.assertEqual(cleaned["status"], "New")
        self.assertEqual(cleaned["website_url"], "https://acme.com")
        # source_url keeps the path so we can still find the originating page.
        self.assertEqual(cleaned["source_url"], "https://reddit.example/r/shipping/q1")
        self.assertEqual(cleaned["missing_fields"], [])

    def test_clean_lead_accepts_feishu_field_name_aliases(self):
        # docs/02 uses "Company / Store Name", "Website URL", "Source Channel",
        # "Source URL" — clean_lead must read both CSV-style and Feishu-style keys.
        cleaned = clean_lead(
            {
                "Company / Store Name": "Brand X",
                "Website URL": "https://www.brandx.com",
                "Source Channel": "Manual",
            }
        )
        self.assertEqual(cleaned["company_name"], "Brand X")
        self.assertEqual(cleaned["website_url"], "https://brandx.com")
        self.assertTrue(cleaned["is_valid"])

    def test_clean_lead_missing_company_flagged(self):
        cleaned = clean_lead({"company_name": "", "website_url": "https://x.com"})
        self.assertFalse(cleaned["is_valid"])
        self.assertIn("company_name", cleaned["missing_fields"])

    def test_clean_lead_defaults_source_channel_to_manual(self):
        # Spec §8.1 input sample treats an empty source_channel as Manual.
        cleaned = clean_lead({"company_name": "X", "website_url": "https://x.com"})
        self.assertEqual(cleaned["source_channel"], "Manual")

    def test_clean_rows_maps_over_each_row(self):
        rows = [
            {"company_name": "A", "website_url": "https://a.com"},
            {"company_name": "", "website_url": ""},
        ]
        cleaned = clean_rows(rows)
        self.assertEqual(len(cleaned), 2)
        self.assertTrue(cleaned[0]["is_valid"])
        self.assertFalse(cleaned[1]["is_valid"])

    def test_clean_lead_standardizes_country_and_platform(self):
        cleaned = clean_lead(
            {
                "company_name": "X",
                "website_url": "https://x.myshopify.com",
                "country": "us",
                "platform": "shopify",
            }
        )
        self.assertEqual(cleaned["country"], "United States")
        self.assertEqual(cleaned["platform"], "Shopify")

    def test_standardize_country_unknown(self):
        self.assertEqual(standardize_country(""), "Unknown")
        self.assertEqual(standardize_country("us"), "United States")
        self.assertEqual(standardize_country("uk"), "United Kingdom")

    def test_standardize_platform_detects_myshopify_domain(self):
        self.assertEqual(standardize_platform("", "https://brands.myshopify.com"), "Shopify")
        self.assertEqual(standardize_platform("woo", "https://x.com"), "WooCommerce")
        self.assertEqual(standardize_platform("", ""), "Unknown")


if __name__ == "__main__":
    unittest.main()
