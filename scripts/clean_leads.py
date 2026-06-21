#!/usr/bin/env python3
"""Clean and normalize lead rows before Feishu import."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
from typing import Any, Dict, Iterable, List


COUNTRY_ALIASES = {
    "us": "United States",
    "usa": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "gb": "United Kingdom",
    "de": "Germany",
    "germany": "Germany",
    "ca": "Canada",
    "canada": "Canada",
    "au": "Australia",
    "australia": "Australia",
    "tr": "Turkey",
    "turkey": "Turkey",
}

PLATFORM_ALIASES = {
    "shopify": "Shopify",
    "woocommerce": "WooCommerce",
    "woo": "WooCommerce",
    "tiktok": "TikTok Shop",
    "tiktok shop": "TikTok Shop",
    "amazon": "Amazon",
    "etsy": "Etsy",
}


def extract_domain(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc or parsed.path.split("/")[0]
    host = host.lower().strip().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(url: str) -> str:
    domain = extract_domain(url)
    if not domain:
        return ""
    return "https://%s" % domain


def normalize_page_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    domain = extract_domain(value)
    if not domain:
        return ""
    path = parsed.path.rstrip("/")
    query = parsed.query
    suffix = path if path else ""
    if query:
        suffix += "?" + query
    return "https://%s%s" % (domain, suffix)


def standardize_country(value: str) -> str:
    key = re.sub(r"\s+", " ", (value or "").strip().lower())
    return COUNTRY_ALIASES.get(key, value.strip() if value else "Unknown")


def standardize_platform(value: str, website_url: str = "") -> str:
    raw = (value or "").strip().lower()
    if "myshopify.com" in website_url.lower():
        return "Shopify"
    return PLATFORM_ALIASES.get(raw, value.strip() if value else "Unknown")


def clean_lead(row: Dict[str, Any]) -> Dict[str, Any]:
    company = str(row.get("company_name") or row.get("Company / Store Name") or "").strip()
    website_input = str(row.get("website_url") or row.get("Website URL") or "").strip()
    source_channel = str(row.get("source_channel") or row.get("Source Channel") or "Manual").strip()
    source_url = str(row.get("source_url") or row.get("Source URL") or "").strip()
    country = standardize_country(str(row.get("country") or row.get("Country / Region") or ""))
    platform = standardize_platform(str(row.get("platform") or row.get("Platform") or ""), website_input)
    category = str(row.get("category") or row.get("Category") or "").strip()
    notes = str(row.get("notes") or row.get("Notes") or "").strip()

    domain = extract_domain(website_input)
    missing_fields: List[str] = []
    if not company:
        missing_fields.append("company_name")
    if not domain:
        missing_fields.append("website_url")
    if not source_channel:
        missing_fields.append("source_channel")

    return {
        "company_name": company,
        "domain": domain,
        "website_url": normalize_url(website_input),
        "platform": platform,
        "country": country,
        "category": category,
        "source_channel": source_channel or "Manual",
        "source_url": normalize_page_url(source_url) if source_url else "",
        "notes": notes,
        "is_valid": not missing_fields,
        "missing_fields": missing_fields,
        "status": "New" if not missing_fields else "Need Manual Check",
    }


def clean_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [clean_lead(row) for row in rows]


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Clean lead CSV rows")
    parser.add_argument("csv_path")
    args = parser.parse_args(argv)
    with open(args.csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(json.dumps(clean_rows(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
