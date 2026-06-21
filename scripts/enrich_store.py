#!/usr/bin/env python3
"""Lightweight store enrichment helpers for public data only."""

from __future__ import annotations

from typing import Dict


def guess_platform(website_url: str, html: str = "") -> str:
    text = ("%s %s" % (website_url or "", html or "")).lower()
    if "myshopify.com" in text or "cdn.shopify.com" in text or "shopify" in text:
        return "Shopify"
    if "woocommerce" in text or "wp-content/plugins/woocommerce" in text:
        return "WooCommerce"
    if "etsy.com" in text:
        return "Etsy"
    if "amazon." in text:
        return "Amazon"
    return "Unknown"


def enrich_store(website_url: str, html: str = "") -> Dict[str, str]:
    return {
        "website_url": website_url,
        "platform": guess_platform(website_url, html),
        "enrichment_source": "public_url_or_provided_html",
    }

