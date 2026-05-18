#!/usr/bin/env python3
"""
co-pay-hub/scripts/search-greenhouse.py
Greenhouse job board scraper — Colorado edition.

CO EPEWA (C.R.S. § 8-5-201): ALL employers must include pay rate/range +
benefits + other compensation. Strictest US law — "DOE" listings violate EPEWA.
Effective Jan 1, 2023 (enhanced from original 2021 law).

Run: python3 ~/co-pay-hub/scripts/search-greenhouse.py
"""

import html as html_mod
import json
import os
import re
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    make_logger, acquire_lock, load_existing_keys,
    write_job, TODAY, OUTPUT_FILE, CO_TERMS,
)

from scrapling import Fetcher

LOG_FILE  = os.path.expanduser("~/co-pay-hub/scripts/greenhouse.log")
LOCK_FILE = os.path.expanduser("~/co-pay-hub/scripts/.greenhouse.lock")
LOOKBACK_DATE = (date.today() - timedelta(days=60)).isoformat() + "T00:00:00.000Z"

log = make_logger(LOG_FILE)
fetcher = Fetcher()

SEED_SLUGS = [
    # ── Denver HQ / Native ────────────────────────────────────────────────────
    ("checkr", None),                        # Checkr — Denver HQ (background screening)
    ("gusto", None),                         # Gusto — Denver HQ (payroll/HR SaaS)
    ("palantir", None),                      # Palantir — Denver HQ (data analytics)
    ("wovencare", None),                     # Woven Care — Denver (care management)
    ("creditunionofcolorado", None),         # Credit Union of Colorado — Denver
    ("climatecabinet", None),                # Climate Cabinet — Denver (civic tech)
    ("codepath", None),                      # CodePath — Denver (tech education)
    ("greenthumbindustries", None),          # Green Thumb Industries — Denver (cannabis)
    ("communityreachcenter", None),          # Community Reach Center — Denver
    ("centerforemploymentopportunities", None),  # Center for Employment Opportunities — Denver
    ("divergent", None),                     # Divergent Technologies — Denver
    ("smartrent", None),                     # SmartRent — Scottsdale/CO presence
    ("betterhelpcom", None),                 # BetterHelp — Denver/remote
    ("c3ascend", None),                      # C3 AI Ascend — Denver
    ("doordashusa", None),                   # DoorDash — Denver office, posts CO salary
    ("ibotta", None),                        # Ibotta — Denver HQ (rewards/advertising)
    ("gympass", None),                       # Gympass — Denver office (wellness)
    ("themjcos", None),                      # The MJ Companies — Denver (cannabis)
    ("evolenthealth", None),                 # Evolent Health — Denver (health IT)
    ("ping", None),                          # Ping Identity — Denver (auth/security)
    ("vertafore", None),                     # Vertafore — Denver (insurance software)
    ("logrhythm", None),                     # LogRhythm — Boulder (cybersecurity)
    ("zayo", None),                          # Zayo Group — Denver (fiber/bandwidth)
    ("sphero", None),                        # Sphero — Boulder (robotics)
    ("sendgrid", None),                      # SendGrid (Twilio) — Denver/Boulder
    # ── Colorado Healthcare / Nonprofit ──────────────────────────────────────
    ("centura", None),                       # Centura Health — Englewood CO
    ("davita", None),                        # DaVita — Denver HQ (dialysis)
    ("adolfcoorsfoundation", None),          # Coors — Golden CO (try)
    ("nationaljewish", None),                # National Jewish Health — Denver
    # ── National companies with CO salary disclosure (EPEWA-compliant) ───────
    ("databricks", None),                    # Databricks — posts CO salary
    ("datadog", None),                       # Datadog — posts CO salary
    ("confluent", None),                     # Confluent — posts CO salary
    ("cloudflare", None),                    # Cloudflare — posts CO salary
    ("gitlab", None),                        # GitLab — remote, CO-eligible
    ("hashicorp", None),                     # HashiCorp — remote/CO
    ("snowflake", None),                     # Snowflake — posts CO salary
    ("twilio", None),                        # Twilio — posts CO salary (Denver)
    ("stripe", None),                        # Stripe — posts CO salary
    ("pagerduty", None),                     # PagerDuty — posts CO salary
    ("elastic", None),                       # Elastic — remote CO-eligible
    ("okta", None),                          # Okta — CO office
    ("zendesk", None),                       # Zendesk — CO office
    ("newrelic", None),                      # New Relic — remote CO
    ("mongodb", None),                       # MongoDB — posts CO salary
    ("atlassian", None),                     # Atlassian — remote CO-eligible
    ("reddit", None),                        # Reddit — posts CO salary
    ("lyft", None),                          # Lyft — posts CO salary
    ("doordash", None),                      # DoorDash corporate (vs doordashusa)
    ("robinhood", None),                     # Robinhood — posts CO salary
]


SALARY_PATTERNS = [
    r'\$\s*([\d,]+)\s*[-–—]\s*\$\s*([\d,]+)',
    r'([\d,]+)\s*[-–—]\s*([\d,]+)\s*(?:USD|usd)',
    r'salary[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'compensation[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'pay range[:\s]+\$?([\d,]+)[kK]?\s*[-–—]\s*\$?([\d,]+)[kK]?',
    r'"salary_min":\s*(\d+).*?"salary_max":\s*(\d+)',
    r'"min_salary":\s*(\d+).*?"max_salary":\s*(\d+)',
    # Colorado EPEWA often uses "Colorado" label before the range
    r'colorado[^$\n]{0,80}\$\s*([\d,]+)\s*[-–—]\s*\$\s*([\d,]+)',
]


def parse_salary_from_text(text: str):
    if not text:
        return None, None
    text = html_mod.unescape(html_mod.unescape(text))
    for pat in SALARY_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                raw_min = m.group(1).replace(",", "")
                raw_max = m.group(2).replace(",", "")
                val_min = int(float(raw_min))
                val_max = int(float(raw_max))
                if val_min < 1000:
                    val_min *= 1000
                if val_max < 1000:
                    val_max *= 1000
                if 30_000 <= val_min < val_max <= 1_500_000:
                    return val_min, val_max
            except (ValueError, IndexError):
                continue
    return None, None


_CANADA_EXCL = [
    "british columbia", "ontario, canada", "alberta, canada", "quebec, canada",
    "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton",
    ", canada", "canada,", "remote - canada", "remote - ontario",
    "remote - british columbia", "remote - alberta", "remote - quebec",
]

_REMOTE_TERMS = ("remote", "distributed", "virtual", "anywhere", "work from", "wfh")


def is_co_job(title: str, location: str, content: str) -> bool:
    loc_low = location.lower()
    content_low = (content or "").lower()

    # Exclude Canadian locations
    if any(t in loc_low for t in _CANADA_EXCL):
        return False
    # Exclude DC explicitly (separate site)
    if "washington, dc" in loc_low or "washington dc" in loc_low or "district of columbia" in loc_low:
        return False

    # Include if explicitly CO location
    if any(t in loc_low for t in CO_TERMS):
        return True

    # Include if content specifically mentions Colorado salary range (EPEWA compliance)
    if "colorado" in content_low and ("salary range" in content_low or "pay range" in content_low or "compensation range" in content_low):
        return True

    # Include remote/unspecified from CO-seeded companies
    if not loc_low or any(r in loc_low for r in _REMOTE_TERMS):
        return True

    return False


def parse_location(location: str) -> str:
    city_map = {
        "denver": "Denver, CO",
        "boulder": "Boulder, CO",
        "fort collins": "Fort Collins, CO",
        "colorado springs": "Colorado Springs, CO",
        "aurora": "Aurora, CO",
        "lakewood": "Lakewood, CO",
        "arvada": "Arvada, CO",
        "westminster": "Westminster, CO",
        "thornton": "Thornton, CO",
        "highlands ranch": "Highlands Ranch, CO",
        "littleton": "Littleton, CO",
        "centennial": "Centennial, CO",
        "englewood": "Englewood, CO",
        "broomfield": "Broomfield, CO",
        "golden": "Golden, CO",
        "pueblo": "Pueblo, CO",
        "greeley": "Greeley, CO",
        "longmont": "Longmont, CO",
    }
    loc = (location or "").lower()
    for key, label in city_map.items():
        if key in loc:
            return label
    if "remote" in loc:
        return "Remote (CO)"
    return "Denver, CO"


def fetch_company_jobs(slug: str, company_name_override=None):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = fetcher.get(url, timeout=20)
        data = resp.json()
    except Exception as e:
        log(f"  [{slug}] API error: {e}")
        return []

    jobs_raw = data.get("jobs", [])
    if not jobs_raw:
        return []

    company_name = company_name_override or data.get("company", {}).get("name") or slug.title()
    results = []

    for j in jobs_raw:
        updated_at = j.get("updated_at", "")
        if updated_at and updated_at < LOOKBACK_DATE:
            continue

        title = j.get("title", "").strip()
        location_obj = j.get("location", {})
        location = location_obj.get("name", "") if isinstance(location_obj, dict) else str(location_obj)
        content_html = j.get("content", "")
        content_text = re.sub(r'<[^>]+>', ' ', content_html)
        content_text = html_mod.unescape(content_text)

        if not is_co_job(title, location, content_text):
            continue

        val_min, val_max = parse_salary_from_text(content_html + " " + content_text)
        if val_min is None:
            val_min, val_max = parse_salary_from_text(str(j))

        if val_min is None:
            continue

        posted_date = updated_at[:10] if updated_at else TODAY
        job_url = j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{j.get('id','')}"

        results.append({
            "role": title,
            "company": company_name,
            "min": val_min,
            "max": val_max,
            "location": parse_location(location),
            "source_url": job_url,
            "posted": posted_date,
            "source_platform": "greenhouse",
        })

    return results


def main():
    if not acquire_lock(LOCK_FILE, log):
        return

    log("=== CO Greenhouse scraper started ===")
    existing = load_existing_keys()
    log(f"Existing dedup keys: {len(existing)}")

    new_count = 0
    for slug, name_override in SEED_SLUGS:
        log(f"[{slug}] fetching...")
        jobs = fetch_company_jobs(slug, name_override)
        for job in jobs:
            key = f"{job['role'].lower().strip()}|{job['company'].lower().strip()}"
            if key in existing:
                continue
            write_job(OUTPUT_FILE, job)
            existing.add(key)
            new_count += 1
            log(f"  + {job['role']} @ {job['company']} | ${job['min']:,}–${job['max']:,} | {job['location']}")
        time.sleep(0.5)

    log(f"=== Done. {new_count} new CO jobs written to {OUTPUT_FILE} ===")


if __name__ == "__main__":
    main()
