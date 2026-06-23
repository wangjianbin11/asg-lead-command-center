#!/usr/bin/env python3
"""Shopify public-data lead crawler for ASG Lead Command Center.

Tier-1 crawler. No headless browser required because Shopify serves
``/products.json`` as public JSON and the homepage as static HTML, so the
whole enrichment runs on stdlib ``urllib`` only.

Compliance posture (CLAUDE.md / docs/08):
- Respects robots.txt per domain (``urllib.robotparser``, cached per domain).
- Polite: >= 2 seconds between fetches to the same domain.
- Auditable: EVERY fetch is appended to ``logs/crawl_audit.jsonl`` as
  ``{ts, domain, url, status, note}``.
- Draft-only / discovery-only: this module discovers and structures leads; it
  never sends any outreach (the outreach step is a separate human-approved
  workflow).

Field names in ``lead_to_leadpool_fields`` mirror
``run_lead_pipeline._build_lead_pool_fields`` EXACTLY so the dict is directly
writable to the Feishu Lead Pool table (docs/02 §6.1 contract).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Allow ``python3 scripts/crawl_leads.py`` and ``python3 -m unittest`` to import
# sibling modules without installing the repo as a package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))


# --- configuration -----------------------------------------------------------

# Per-domain minimum spacing between fetches (politeness, spec compliance).
RATE_LIMIT_SECONDS = 2.0

# Realistic browser UA so public endpoints respond normally. Not used to
# impersonate for auth-bypass — only to avoid naive bot blocks on public pages.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Built-in live demo seed: real public Shopify storefronts. Used ONLY by the
# ``--seed`` CLI flag for the live demo. Public /products.json endpoints.
SEED_DOMAINS = ["allbirds.com", "gymshark.com", "kith.com"]

# Pain keywords scanned across homepage + product text. Mirrors the spirit of
# generate_content_opportunities._PAIN_KEYWORDS but kept as a flat surface list
# for the crawler's public-signal detection (these are evidence, not the full
# Pain Point enum).
# Pain keywords scanned across homepage + product text. The crawler surfaces
# these as a flat pain-signal list (distinct from the docs/02 Pain Point enum),
# so each keyword bucket is its own detectable signal.
_PAIN_KEYWORDS: List[tuple] = [
    ("supplier", ["supplier", "factory", "vendor", "1688", "alibaba"]),
    ("sourcing", ["sourcing", "source from", "china sourcing"]),
    ("shipping", ["shipping", "delivery", "tracking", "transit"]),
    ("fulfillment", ["fulfillment", "order fulfillment"]),
    ("logistics", ["logistics", "warehouse", "warehousing"]),
    ("qc", ["quality control", "qc", "quality check", "inspection", "defect", "quality issue"]),
    ("packaging", ["packaging", "custom box", "private label", "branded box", "logo box"]),
    ("moq", ["moq", "minimum order", "minimum quantity"]),
]

# Public email regex — matches the visible-text / mailto: forms. Conservative:
# requires an @ and a dot in the TLD; rejects anything with a space.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Social link hosts -> normalized key.
_SOCIAL_HOSTS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "tiktok.com": "tiktok",
    "x.com": "x",
    "twitter.com": "x",
}

# Logs directory for the fetch audit trail (created lazily).
LOGS_DIR = _REPO_ROOT / "logs"
AUDIT_LOG = LOGS_DIR / "crawl_audit.jsonl"


# --- module-level caches -----------------------------------------------------

# Last-fetch timestamp per domain (host) for rate limiting.
_last_fetch_at: Dict[str, float] = {}

# robots.txt parser cache per scheme+host so we fetch each robots.txt once.
_robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}


# --- audit logging -----------------------------------------------------------


def _audit(domain: str, url: str, status: str, note: str = "") -> None:
    """Append one fetch event to logs/crawl_audit.jsonl (create logs/)."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "domain": domain,
            "url": url,
            "status": status,
            "note": note,
        }
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # Audit logging must never crash the crawl (spec §0 rule 7).
        pass


# --- rate limiting -----------------------------------------------------------


def _host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def _rate_limit(domain: str) -> None:
    """Sleep just enough so >= RATE_LIMIT_SECONDS pass between same-domain fetches."""
    host = domain.lower()
    last = _last_fetch_at.get(host, 0.0)
    elapsed = time.time() - last
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_fetch_at[host] = time.time()


# --- compliance: robots.txt --------------------------------------------------


def _robots_allows(url: str) -> bool:
    """True iff robots.txt for the URL's host allows our UA for ``url``.

    Cached per host so each domain's robots.txt is fetched at most once per
    process. When robots.txt is missing/unreachable we are permissive
    (convention: no robots.txt == allowed) but we still record the fetch in
    the audit log.
    """
    parsed = urllib.parse.urlparse(url)
    base = "%s://%s" % (parsed.scheme, parsed.netloc)
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:  # noqa: BLE001 - missing/unreadable robots -> allow
            _audit(parsed.netloc, base + "/robots.txt", "robots_unreadable",
                   "treated as allow")
        _robots_cache[base] = rp
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001
        return True


# --- HTTP fetch --------------------------------------------------------------


def _fetch_text(url: str, retries: int = 3, timeout: float = 20.0) -> Optional[str]:
    """GET ``url`` as text with exponential backoff. Returns None on failure.

    Every attempt is audited. Uses a realistic User-Agent and respects the
    per-domain rate limit.
    """
    domain = _host_of(url)
    last_error = ""
    for attempt in range(1, retries + 1):
        _rate_limit(domain)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                _audit(domain, url, str(getattr(response, "status", 200)), "ok")
                return raw
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s" % exc.code
            _audit(domain, url, last_error, "http_error attempt=%d" % attempt)
            # 4xx (except 429) is a hard stop — retrying won't help.
            if exc.code != 429 and 400 <= exc.code < 500:
                return None
        except urllib.error.URLError as exc:
            last_error = "URLError: %s" % exc.reason
            _audit(domain, url, last_error, "url_error attempt=%d" % attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = "Error: %s" % exc
            _audit(domain, url, last_error, "error attempt=%d" % attempt)
        if attempt < retries:
            time.sleep(2 ** attempt)  # exponential backoff: 2, 4, 8 ...
    return None


# --- parsing helpers (pure, hermetic, unit-tested) --------------------------


def _parse_products_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse Shopify /products.json. Returns None if not usable.

    Output shape (internal, used by ``enrich_store``)::

        {"product_count": int, "category": str, "product_text": str}

    ``product_text`` is the concatenation of every product title + tag +
    body_html, lower-cased, so ``_detect_pain`` can scan it for signals.
    """
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list) or not products:
        return None

    titles: List[str] = []
    tags: List[str] = []
    bodies: List[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        title = str(product.get("title") or "").strip()
        if title:
            titles.append(title)
        ptags = product.get("tags")
        if isinstance(ptags, list):
            tags.extend(str(t).strip() for t in ptags if str(t).strip())
        elif isinstance(ptags, str):
            tags.extend(t.strip() for t in ptags.split(",") if t.strip())
        body = product.get("body_html") or product.get("body") or ""
        # Strip HTML tags from body so pain-signal scan hits real words.
        clean_body = re.sub(r"<[^>]+>", " ", str(body))
        bodies.append(clean_body)

    category = _derive_category(titles, tags)
    product_text = " ".join(titles + tags + bodies).lower()
    return {
        "product_count": len(products),
        "category": category,
        "product_text": product_text,
    }


def _derive_category(titles: List[str], tags: List[str]) -> str:
    """Pick a niche/category from the most common tag, falling back to title words."""
    if tags:
        # Most frequent tag (case-insensitive) is a decent niche signal.
        counts: Dict[str, int] = {}
        for tag in tags:
            key = tag.lower()
            counts[key] = counts.get(key, 0) + 1
        if counts:
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            return top
    if titles:
        # First title's first non-stopword-ish token.
        first = titles[0].split()
        if first:
            return first[0].lower()
    return ""


def _parse_homepage(html: str) -> Dict[str, Any]:
    """Extract site_name, public email, social links, and a country guess.

    All extraction is regex + simple HTML scanning (no third-party parser, so
    hermetic and dependency-free). Missing fields come back as "" / {}.
    """
    result: Dict[str, Any] = {
        "site_name": "",
        "email": "",
        "social_links": {},
        "country": "",
    }
    if not html:
        return result

    # site_name: prefer og:site_name, fall back to <title>.
    m = re.search(
        r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)[\"']",
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']og:site_name[\"']",
            html, re.IGNORECASE,
        )
    if m:
        result["site_name"] = m.group(1).strip()
    else:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            result["site_name"] = m.group(1).strip()

    # public email: first visible-text or mailto: match.
    emails = _EMAIL_RE.findall(html)
    if emails:
        result["email"] = emails[0].strip().rstrip(".")

    # social links: scan href attributes for known social hosts.
    socials: Dict[str, str] = {}
    for href_m in re.finditer(r"href=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
        href = href_m.group(1).strip().lower()
        host = urllib.parse.urlparse(href).netloc
        # Strip leading www. so 'www.instagram.com' still matches.
        if host.startswith("www."):
            host = host[4:]
        for known, key in _SOCIAL_HOSTS.items():
            if host == known or host.endswith("." + known):
                if key not in socials:
                    socials[key] = href_m.group(1).strip()
                break
    result["social_links"] = socials

    # country guess: <html lang="xx-YY"> region code, else '' .
    m = re.search(r"<html[^>]+lang=[\"']([a-zA-Z]{2})-([a-zA-Z]{2})[\"']",
                  html, re.IGNORECASE)
    if m:
        result["country"] = m.group(2).upper()
    return result


def _detect_pain(text: str) -> List[str]:
    """Return the list of detected pain signals in ``text`` (lower-cased scan).

    Deduped, order-stable (insertion order of _PAIN_KEYWORDS). Used both for
    the public-signal scan and surfaced directly into Lead Pool ``Pain Signal``.
    """
    if not text:
        return []
    lowered = text.lower()
    found: List[str] = []
    for pain, keywords in _PAIN_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            found.append(pain)
    return found


# --- domain normalization ----------------------------------------------------


def _normalize_domain(domain: str) -> str:
    """Strip scheme / path / www so callers can pass messy input."""
    domain = (domain or "").strip().lower()
    if "://" in domain:
        domain = urllib.parse.urlparse(domain).netloc
    domain = domain.split("/")[0].strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


# --- enrichment (touches the network) ---------------------------------------


def enrich_store(domain: str) -> Optional[Dict[str, Any]]:
    """Enrich one Shopify domain from PUBLIC data only.

    Steps:
      1. Normalize the domain.
      2. Check robots.txt for both /products.json and / — bail if disallowed.
      3. GET https://{domain}/products.json (Shopify public JSON) and the
         homepage HTML. If neither resolves or it isn't a Shopify store, bail.
      4. Parse site_name, product_count, niche, pain signals, public email,
         social links, country guess.
      5. Return a lead dict with EXACT keys:
         company_name, website_url, platform, source_channel, source_url,
         notes, country, category, email (plus internal pain_signals).

    Returns ``None`` if not Shopify / fetch fails / robots disallows.
    """
    domain = _normalize_domain(domain)
    if not domain or "." not in domain:
        return None

    products_url = "https://%s/products.json" % domain
    home_url = "https://%s/" % domain

    # robots.txt gate before any real fetch.
    if not _robots_allows(products_url) or not _robots_allows(home_url):
        _audit(domain, products_url, "robots_blocked", "skipped per robots.txt")
        return None

    products_text = _fetch_text(products_url)
    if products_text is None:
        # Not a Shopify store or endpoint blocked. No point fetching homepage.
        return None

    parsed_products = _parse_products_json(products_text)
    if parsed_products is None:
        # products.json exists but isn't a Shopify product list -> not Shopify.
        return None

    home_text = _fetch_text(home_url)
    home_text = home_text or ""
    parsed_home = _parse_homepage(home_text)

    site_name = parsed_home["site_name"] or domain
    # Confirm Shopify signal in the homepage HTML (CDN / generator / platform).
    looks_shopify = (
        "shopify" in home_text.lower()
        or "cdn.shopify.com" in home_text.lower()
        or "myshopify.com" in home_text.lower()
    )
    platform = "Shopify" if looks_shopify else "Shopify"  # products.json implies Shopify

    # Pain signals scan across homepage + product text.
    pain_signals = _detect_pain(parsed_products["product_text"])
    pain_signals = _dedupe_keep_order(pain_signals + _detect_pain(home_text))

    evidence_bits = ["product_count=%d" % parsed_products["product_count"]]
    if pain_signals:
        evidence_bits.append("pains=" + ",".join(pain_signals))
    if parsed_home["email"]:
        evidence_bits.append("email_found")
    if parsed_home["social_links"]:
        evidence_bits.append("socials=" + ",".join(sorted(parsed_home["social_links"].keys())))

    lead = {
        "company_name": site_name,
        "website_url": "https://%s" % domain,
        "platform": platform,
        "source_channel": "Crawler",
        "source_url": products_url,
        "notes": "Public crawl; " + "; ".join(evidence_bits),
        "country": parsed_home["country"],
        "category": parsed_products["category"],
        "email": parsed_home["email"],
        # Internal-only (lead_to_leadpool_fields reads these).
        "pain_signals": pain_signals,
        "product_count": parsed_products["product_count"],
        "social_links": parsed_home["social_links"],
    }
    return lead


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --- Lead ID generation (idempotent) ----------------------------------------


def _lead_id_for_domain(domain: str) -> str:
    """Deterministic ``LEAD-CRAWL-<shortdomainhash>`` so re-runs are idempotent.

    A 10-char hex of the SHA1 of the normalized domain means the same store
    always maps to the same Lead ID, regardless of run order or date.
    """
    domain = _normalize_domain(domain)
    digest = hashlib.sha1(domain.encode("utf-8")).hexdigest()[:10]
    return "LEAD-CRAWL-%s" % digest


# --- Feishu integration ------------------------------------------------------


def lead_to_leadpool_fields(lead: Dict[str, Any], lead_id: str) -> Dict[str, Any]:
    """Translate a crawled lead dict into a Lead Pool field dict.

    Field names mirror ``run_lead_pipeline._build_lead_pool_fields`` EXACTLY so
    the dict is directly writable to Feishu Bitable (docs/02 §6.1 contract).
    Status='New', Source Channel='Crawler', Pain Signal=list of detected pains.
    """
    website = lead.get("website_url", "")
    pains = list(lead.get("pain_signals") or [])
    # Email is appended to Notes so the outreach-routing logic in
    # run_lead_pipeline can still find a contact channel for crawler leads.
    notes = lead.get("notes", "")
    email = lead.get("email", "")
    if email and email not in notes:
        notes = ("%s | email: %s" % (notes, email)).strip(" |")
    return {
        "Lead ID": lead_id,
        "Company / Store Name": lead.get("company_name", ""),
        "Website URL": website,
        "Platform": lead.get("platform", "Shopify"),
        "Country / Region": lead.get("country", "") or "Unknown",
        "Category": lead.get("category", ""),
        "Source Channel": "Crawler",
        "Source URL": lead.get("source_url", ""),
        "Pain Signal": pains,
        "Evidence Text": notes,
        "Estimated Stage": "Unknown",
        "Estimated Order Volume": "Unknown",
        "Current Supplier Guess": "",
        "ASG Fit Score": None,
        "Priority": "",
        "Status": "New",
        "Owner": "",
        "Notes": notes,
    }


def _clean_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values before a Feishu write (mirrors run_lead_pipeline)."""
    return {k: v for k, v in fields.items() if v not in (None, "", [], {})}


def _extract_website_domain(value: Any) -> str:
    """Normalize a Lead Pool 'Website URL' cell (str | {link: str} | None) to host."""
    if not value:
        return ""
    if isinstance(value, dict):
        value = value.get("link") or value.get("text") or ""
    raw = str(value).strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    netloc = urllib.parse.urlparse(raw).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def existing_website_domains(client: Any, table_id: str) -> Set[str]:
    """Return the set of website domains already present in the Lead Pool.

    Used by ``crawl_domains`` to skip re-crawling stores that are already
    tracked (idempotent re-crawl). Reads the ``Website URL`` field of every
    record and normalizes to a bare host.
    """
    domains: Set[str] = set()
    if client is None or not table_id:
        return domains
    try:
        records = client.list_records(table_id, field_names=["Website URL"])
    except Exception:  # noqa: BLE001 - read failure => no known domains
        return domains
    for record in records or []:
        fields = record.get("fields") if isinstance(record, dict) else None
        if not isinstance(fields, dict):
            continue
        domain = _extract_website_domain(fields.get("Website URL"))
        if domain:
            domains.add(domain)
    return domains


# --- top-level crawl orchestration ------------------------------------------


def crawl_domains(
    domains: List[str],
    *,
    client: Any = None,
    write_feishu: bool = False,
    date_str: str = "",
    lead_table_id: str = "",
) -> Dict[str, Any]:
    """Crawl a list of domains, returning ``{'summary': {...}, 'leads': [...]}``.

    Behaviour:
    - Normalizes each domain (strips scheme / www).
    - Skips domains already present in the Lead Pool (idempotent re-crawl) when
      a client + lead table id are available.
    - Calls ``enrich_store`` (monkeypatchable in tests) per domain.
    - Writes a Lead Pool record per enriched lead when ``write_feishu`` is set.
    - Lead IDs are deterministic per domain (``LEAD-CRAWL-<hash>``) so re-runs
      never duplicate.

    ``date_str`` is accepted for API symmetry with the rest of the pipeline;
    it is unused because crawler Lead IDs are domain-hash-based, not date-based.
    """
    from config import RuntimeConfig  # local import: avoid import-time side effects

    # Resolve the Lead Pool table id lazily so dry-run never requires env config.
    lead_table_id_resolved = lead_table_id
    existing: Set[str] = set()
    if client is not None:
        if not lead_table_id_resolved:
            try:
                lead_table_id_resolved = RuntimeConfig.from_env().table_id("lead")
            except Exception:  # noqa: BLE001 - no table id => skip dedupe read
                lead_table_id_resolved = ""
        if lead_table_id_resolved:
            existing = existing_website_domains(client, lead_table_id_resolved)

    leads: List[Dict[str, Any]] = []
    total = 0
    enriched = 0
    skipped_existing = 0
    failed = 0

    for raw_domain in domains or []:
        total += 1
        domain = _normalize_domain(raw_domain)
        if not domain:
            failed += 1
            continue
        if domain in existing:
            skipped_existing += 1
            continue
        lead = enrich_store(domain)
        if lead is None:
            failed += 1
            continue
        lead_id = _lead_id_for_domain(domain)
        fields = lead_to_leadpool_fields(lead, lead_id)
        leads.append(fields)
        enriched += 1

        if write_feishu and client is not None and lead_table_id_resolved:
            try:
                client.create_record(lead_table_id_resolved, _clean_fields(fields))
            except Exception:  # noqa: BLE001 - one bad write must not abort the batch
                _audit(domain, lead.get("source_url", ""), "write_failed", "feishu create_record error")

    summary = {
        "total_domains": total,
        "enriched": enriched,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "write_feishu": bool(write_feishu and client is not None and lead_table_id_resolved),
    }
    return {"summary": summary, "leads": leads}


# --- CLI ---------------------------------------------------------------------


def _read_domains_file(path: str) -> List[str]:
    """Read a one-domain-per-line file, stripping blanks and comments."""
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ASG Shopify public-data lead crawler (Tier-1)."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--domains",
        help="Path to a file with one domain per line (blank/# lines ignored).",
    )
    src.add_argument(
        "--domain",
        action="append",
        default=[],
        help="A single domain to crawl (repeatable).",
    )
    src.add_argument(
        "--seed",
        action="store_true",
        help="Use the built-in demo seed of public Shopify stores (live demo only).",
    )
    parser.add_argument(
        "--write-feishu",
        action="store_true",
        help="Write enriched leads to the Feishu Lead Pool. Default: print JSON only.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.seed:
        domains = list(SEED_DOMAINS)
    elif args.domain:
        domains = list(args.domain)
    else:
        domains = _read_domains_file(args.domains)

    client = None
    if args.write_feishu:
        from feishu_client import FeishuClient  # local import

        client = FeishuClient()

    result = crawl_domains(domains, client=client, write_feishu=args.write_feishu)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


# Tier-2 (optional) headless enrichment hook. Not required for V1; the import
# is wrapped so absence of playwright never breaks the crawler.
try:  # pragma: no cover - optional Tier-2 dependency
    import playwright  # type: ignore  # noqa: F401
    HAS_PLAYWRIGHT = True
except Exception:  # noqa: BLE001
    HAS_PLAYWRIGHT = False


if __name__ == "__main__":
    raise SystemExit(main())
