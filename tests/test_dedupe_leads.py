import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dedupe_leads import (
    dedupe_rows,
    find_duplicate,
    lead_company,
    lead_domain,
    lead_email,
    lead_source_url,
    normalize_company,
)


class DedupeLeadTests(unittest.TestCase):
    # --- Case 3: domain dedup ---------------------------------------------

    def test_domain_duplicate(self):
        # Spec §8.2 acceptance: same Website URL (www/http/path variants) -> dup.
        existing = [{"lead_id": "LEAD-1", "website_url": "https://www.example.com/products/a"}]
        candidate = {"website_url": "http://example.com/"}
        result = find_duplicate(candidate, existing)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["duplicate_type"], "domain")
        self.assertEqual(result["master_lead_id"], "LEAD-1")

    def test_domain_duplicate_www_vs_nonwww(self):
        existing = [{"lead_id": "L1", "website_url": "https://www.brand.com"}]
        candidate = {"website_url": "https://brand.com/some/path"}
        self.assertEqual(find_duplicate(candidate, existing)["duplicate_type"], "domain")

    def test_domain_duplicate_http_vs_https(self):
        existing = [{"lead_id": "L1", "website_url": "http://brand.com"}]
        candidate = {"website_url": "https://brand.com"}
        self.assertTrue(find_duplicate(candidate, existing)["is_duplicate"])

    def test_domain_duplicate_path_vs_no_path(self):
        existing = [{"lead_id": "L1", "website_url": "https://brand.com/products/p1"}]
        candidate = {"website_url": "https://brand.com"}
        self.assertTrue(find_duplicate(candidate, existing)["is_duplicate"])

    def test_different_domains_are_not_duplicates(self):
        existing = [{"lead_id": "L1", "website_url": "https://alpha.com"}]
        candidate = {"website_url": "https://beta.com"}
        self.assertFalse(find_duplicate(candidate, existing)["is_duplicate"])

    def test_lead_domain_uses_domain_field_when_present(self):
        # If the cleaner already extracted `domain`, dedupe must prefer it.
        self.assertEqual(lead_domain({"domain": "foo.com"}), "foo.com")
        self.assertEqual(lead_domain({"website_url": "https://www.foo.com/x"}), "foo.com")

    # --- Case 4: email dedup ----------------------------------------------

    def test_email_duplicate(self):
        existing = [{"lead_id": "LEAD-1", "email": "Owner@Example.com"}]
        candidate = {"email": "owner@example.com"}
        result = find_duplicate(candidate, existing)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["duplicate_type"], "email")

    def test_email_duplicate_case_insensitive_and_trimmed(self):
        existing = [{"lead_id": "L1", "email": " Owner@Example.com "}]
        candidate = {"email": "owner@example.com"}
        result = find_duplicate(candidate, existing)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["duplicate_type"], "email")
        self.assertEqual(result["master_lead_id"], "L1")

    def test_different_emails_not_duplicate(self):
        existing = [{"lead_id": "L1", "email": "a@x.com"}]
        candidate = {"email": "b@x.com"}
        self.assertFalse(find_duplicate(candidate, existing)["is_duplicate"])

    def test_lead_email_normalizes(self):
        self.assertEqual(lead_email({"email": " Foo@Bar.com "}), "foo@bar.com")
        self.assertEqual(lead_email({"Email": "Foo@Bar.com"}), "foo@bar.com")

    # --- source_url + company ---------------------------------------------

    def test_same_source_url_is_duplicate_source(self):
        # Spec §10.2 rule 4: same source_url -> duplicate source.
        existing = [{"lead_id": "L1", "source_url": "https://reddit.example/thread/x"}]
        candidate = {"source_url": "https://reddit.example/thread/x"}
        result = find_duplicate(candidate, existing)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["duplicate_type"], "source_url")

    def test_different_source_paths_are_not_duplicates(self):
        existing = [{"lead_id": "LEAD-1", "source_url": "https://reddit.example/thread/a"}]
        candidate = {"source_url": "https://reddit.example/thread/b"}
        result = find_duplicate(candidate, existing)
        self.assertFalse(result["is_duplicate"])

    def test_company_high_similarity_flagged_for_review(self):
        # Spec §10.2 rule 3: company name similarity -> review (not hard dup).
        existing = [{"lead_id": "L1", "company_name": "Acme Trading Co"}]
        candidate = {"company_name": "Acme Trading Co."}
        result = find_duplicate(candidate, existing)
        self.assertTrue(result["is_duplicate"])
        self.assertEqual(result["duplicate_type"], "company")
        self.assertTrue(result["review_needed"])

    # --- ordering: domain takes priority over company ---------------------

    def test_domain_match_wins_over_company_similarity(self):
        # When both domain and company overlap, the harder signal (domain) wins.
        existing = [
            {"lead_id": "L1", "website_url": "https://acme.com", "company_name": "Acme Co"}
        ]
        candidate = {"website_url": "https://acme.com", "company_name": "Acme Co Ltd"}
        result = find_duplicate(candidate, existing)
        self.assertEqual(result["duplicate_type"], "domain")

    # --- dedupe_rows batch behavior ---------------------------------------

    def test_dedupe_rows_keeps_first_as_master(self):
        rows = [
            {"lead_id": "L1", "website_url": "https://acme.com"},
            {"lead_id": "L2", "website_url": "http://www.acme.com/x"},
            {"lead_id": "L3", "website_url": "https://beta.com"},
        ]
        out = dedupe_rows(rows)
        self.assertFalse(out[0]["is_duplicate"])
        self.assertTrue(out[1]["is_duplicate"])
        self.assertEqual(out[1]["master_lead_id"], "L1")
        self.assertFalse(out[2]["is_duplicate"])

    def test_normalize_company_strips_noise_words(self):
        # Noise words like "store"/"shop"/"official" must not block a match.
        self.assertEqual(
            normalize_company("The Acme Store"),
            normalize_company("Acme Shop"),
        )

    def test_lead_company_reads_alias(self):
        self.assertEqual(lead_company({"company_name": "Foo"}), "Foo")
        self.assertEqual(lead_company({"Company / Store Name": "Bar"}), "Bar")

    def test_lead_source_url_preserves_path(self):
        self.assertEqual(
            lead_source_url({"source_url": "http://reddit.example/t/x/"}),
            "https://reddit.example/t/x",
        )
        self.assertEqual(lead_source_url({"Source URL": "https://r.com/a"}), "https://r.com/a")

    def test_empty_candidate_returns_not_duplicate(self):
        self.assertFalse(find_duplicate({}, [{"lead_id": "L1"}])["is_duplicate"])


if __name__ == "__main__":
    unittest.main()
