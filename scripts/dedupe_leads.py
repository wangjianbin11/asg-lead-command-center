#!/usr/bin/env python3
"""Lead deduplication helpers."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from typing import Any, Dict, Iterable, List

try:
    from clean_leads import extract_domain, normalize_page_url
except ImportError:  # pragma: no cover - package import path
    from .clean_leads import extract_domain, normalize_page_url


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_company(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    words = [word for word in value.split() if word not in {"the", "store", "shop", "official"}]
    return " ".join(words)


def company_similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, normalize_company(left), normalize_company(right)).ratio()


def lead_id(row: Dict[str, Any]) -> str:
    return str(row.get("lead_id") or row.get("Lead ID") or row.get("id") or "")


def lead_domain(row: Dict[str, Any]) -> str:
    return str(row.get("domain") or extract_domain(str(row.get("website_url") or row.get("Website URL") or "")))


def lead_email(row: Dict[str, Any]) -> str:
    return normalize_email(str(row.get("email") or row.get("Email") or ""))


def lead_source_url(row: Dict[str, Any]) -> str:
    return normalize_page_url(str(row.get("source_url") or row.get("Source URL") or ""))


def lead_company(row: Dict[str, Any]) -> str:
    return str(row.get("company_name") or row.get("Company / Store Name") or "")


def find_duplicate(
    candidate: Dict[str, Any],
    existing_rows: Iterable[Dict[str, Any]],
    company_threshold: float = 0.88,
) -> Dict[str, Any]:
    candidate_domain = lead_domain(candidate)
    candidate_email = lead_email(candidate)
    candidate_source_url = lead_source_url(candidate)
    candidate_company = lead_company(candidate)

    likely_company_match: Dict[str, Any] = {}
    for existing in existing_rows:
        master_id = lead_id(existing)
        if candidate_domain and candidate_domain == lead_domain(existing):
            return {"is_duplicate": True, "duplicate_type": "domain", "master_lead_id": master_id}
        if candidate_email and candidate_email == lead_email(existing):
            return {"is_duplicate": True, "duplicate_type": "email", "master_lead_id": master_id}
        if candidate_source_url and candidate_source_url == lead_source_url(existing):
            return {"is_duplicate": True, "duplicate_type": "source_url", "master_lead_id": master_id}
        similarity = company_similarity(candidate_company, lead_company(existing))
        if candidate_company and similarity >= company_threshold:
            likely_company_match = {
                "is_duplicate": True,
                "duplicate_type": "company",
                "master_lead_id": master_id,
                "similarity": round(similarity, 3),
                "review_needed": True,
            }

    if likely_company_match:
        return likely_company_match
    return {"is_duplicate": False, "duplicate_type": "", "master_lead_id": ""}


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    for row in rows:
        result = find_duplicate(row, seen)
        merged = dict(row)
        merged.update(result)
        results.append(merged)
        if not result["is_duplicate"] or result["duplicate_type"] == "company":
            seen.append(row)
    return results


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Deduplicate lead CSV rows")
    parser.add_argument("csv_path")
    args = parser.parse_args(argv)
    with open(args.csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(json.dumps(dedupe_rows(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
