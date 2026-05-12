#!/usr/bin/env python3
"""Refresh PostHog data for the CTR rollout report.

Two outputs:
- posthog-validation.json: per-merchant verdicts for the BQ-flagged anomaly list
- posthog-daily.json: 14-day trend of US new-platform clicks, pageviews,
  rage clicks, dead clicks on /coupons/*

Requires POSTHOG_API_KEY env var (Personal API Token from PostHog UI ->
Account Settings -> Personal API Keys). Scope: project read for project
102186 (Coupons).

Run locally with `POSTHOG_API_KEY=<token> python scripts/refresh-posthog.py`
or wire up via GH Actions secret in the daily refresh workflow.
"""

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

POSTHOG_HOST = "https://eu.posthog.com"
PROJECT_ID = 102186  # Coupons
REPO_ROOT = Path(__file__).parent.parent
VALIDATION_FILE = REPO_ROOT / "posthog-validation.json"
DAILY_FILE = REPO_ROOT / "posthog-daily.json"
FLAGGED_FILE = REPO_ROOT / "flagged-merchants.json"

# Build SSL context with certifi if available (macOS Python often missing system certs)
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

# Fallback list used only if flagged-merchants.json is missing or empty.
# The normal pipeline is: refresh-data.py computes flagged-merchants.json
# from the BQ anomaly rule -> refresh-posthog.py reads it.
FALLBACK_FLAGGED = [
    {"name": "Athleta",      "cc_merchant_id": 114950, "slug": "athleta",      "bq_new_ctr_pct": 4.3,  "bq_old_ctr_pct": 42.6, "bq_worst_day": "May 9"},
    {"name": "Oakley",       "cc_merchant_id": 144774, "slug": "oakley",       "bq_new_ctr_pct": 9.6,  "bq_old_ctr_pct": 55.7, "bq_worst_day": "May 7"},
    {"name": "Build-A-Bear", "cc_merchant_id": 134954, "slug": "build-a-bear", "bq_new_ctr_pct": 12.8, "bq_old_ctr_pct": 43.2, "bq_worst_day": "May 6"},
    {"name": "Levi's",       "cc_merchant_id": 115806, "slug": "levis",        "bq_new_ctr_pct": 13.9, "bq_old_ctr_pct": 45.2, "bq_worst_day": "May 10"},
]


def load_flagged_merchants():
    """Load the chronic-flagged merchant list written by refresh-data.py."""
    if FLAGGED_FILE.exists():
        try:
            payload = json.loads(FLAGGED_FILE.read_text())
            merchants = payload.get("merchants", [])
            if merchants:
                print(f"Loaded {len(merchants)} flagged merchants from {FLAGGED_FILE.name}")
                return merchants
            print(f"  {FLAGGED_FILE.name} exists but has 0 merchants - falling back to hardcoded list")
        except Exception as e:
            print(f"  Failed to read {FLAGGED_FILE.name}: {e} - falling back", file=sys.stderr)
    else:
        print(f"  {FLAGGED_FILE.name} missing - falling back to hardcoded list")
    return FALLBACK_FLAGGED


def hogql(query: str, api_key: str):
    req = urllib.request.Request(
        f"{POSTHOG_HOST}/api/projects/{PROJECT_ID}/query/",
        data=json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def merchant_validation(api_key: str):
    """For each flagged merchant, compute PostHog 7-day CTR and classify."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)

    def esc(s):
        # HogQL single-quote string escape: double the quote
        return s.replace("'", "''")

    merchants = load_flagged_merchants()
    results = []
    for m in merchants:
        name_lc = esc(m["name"].lower())
        slug    = esc(m["slug"])
        # Clicks: outbound_click with merchant_name (case-insensitive)
        clicks_q = f"""
            SELECT count() FROM events
            WHERE event = 'outbound_click'
              AND properties.countryCode = 'US'
              AND properties.x_service = 'coupons-ui'
              AND lower(properties.merchant_name) = '{name_lc}'
              AND timestamp >= '{start}' AND timestamp < '{end}'
        """
        # Pageviews on the merchant's coupon page
        pv_q = f"""
            SELECT count() FROM events
            WHERE event = '$pageview'
              AND properties.$pathname = '/coupons/{slug}'
              AND timestamp >= '{start}' AND timestamp < '{end}'
        """
        try:
            clicks = hogql(clicks_q, api_key).get("results", [[0]])[0][0]
            views = hogql(pv_q, api_key).get("results", [[0]])[0][0]
        except urllib.error.HTTPError as e:
            print(f"PostHog HTTP error for {m['name']}: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
            clicks, views = 0, 0

        ctr = (clicks / views * 100) if views > 0 else 0.0
        verdict, label, color, notes = classify(clicks, ctr)

        # PostHog deep-links - filtered to last 7 days, this merchant only
        # Filter format: PostHog accepts a `properties` JSON URL parameter for event filtering.
        merchant_filter = urllib.parse.quote(json.dumps([
            {"key": "merchant_name", "value": [m["name"]], "operator": "exact", "type": "event"}
        ]))
        pathname_filter = urllib.parse.quote(json.dumps([
            {"key": "$pathname", "value": [f'/coupons/{m["slug"]}'], "operator": "exact", "type": "event"}
        ]))
        # Session replay search filtered to visitors of this merchant's coupon page
        replay_url = (
            f"{POSTHOG_HOST}/project/{PROJECT_ID}/replay/home"
            f"?date_from=-7d&filters={pathname_filter}"
        )
        # Events page filtered to outbound_click for this merchant
        events_url = (
            f"{POSTHOG_HOST}/project/{PROJECT_ID}/events"
            f"?properties={merchant_filter}"
        )

        results.append({
            "name": m["name"],
            "cc_merchant_id": m["cc_merchant_id"],
            "bq_new_ctr_pct": m.get("bq_new_ctr_pct"),
            "bq_old_ctr_pct": m.get("bq_old_ctr_pct"),
            "bq_worst_day": m.get("bq_worst_day"),
            "cohort": m.get("cohort"),
            "days_flagged": m.get("days_flagged"),
            "posthog_clicks_7d": clicks,
            "posthog_pageviews_7d": views,
            "posthog_ctr_pct": round(ctr, 1),
            "verdict": verdict,
            "verdict_label": label,
            "verdict_color": color,
            "notes": notes,
            "posthog_replay_url": replay_url,
            "posthog_events_url": events_url,
        })
        print(f"  {m['name']:15s} clicks={clicks:>5} views={views:>5} CTR={ctr:>5.1f}% verdict={verdict}")

    summary = {
        "real_issues":     sum(1 for r in results if r["verdict"] == "REAL_ISSUE"),
        "false_positives": sum(1 for r in results if r["verdict"] == "FALSE_POSITIVE"),
        "inconclusive":    sum(1 for r in results if r["verdict"] == "INCONCLUSIVE"),
        "low_volume":      sum(1 for r in results if r["verdict"] == "LOW_VOLUME"),
        "tickets_to_file": sum(1 for r in results if r["verdict"] == "REAL_ISSUE"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": 7,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "rule": "PostHog new-platform CTR on /coupons/{merchant} pages. >=70% clicks/views = FALSE_POSITIVE, 30-70% = INCONCLUSIVE, <30% with <=15 clicks = LOW_VOLUME, <30% with >15 clicks = REAL_ISSUE",
        "merchants": results,
        "summary": summary,
    }


def classify(clicks, ctr):
    """Thresholds aligned with the BQ auto-rule (which fires at new CTR < 15%)
    and the Apr 27 cohort-wide PostHog cross-check (which found 45-79%
    direct-traffic CTR was the FALSE_POSITIVE band).
    """
    if clicks < 30:
        return ("LOW_VOLUME", f"Low volume - inconclusive", "#86868b",
                f"{clicks} clicks in 7 days is below the validation threshold (30+ needed). Often a sign the Cloudflare cache was still active for this merchant pre-May 8 - re-evaluate after more clean data accumulates.")
    if ctr >= 50:
        return ("FALSE_POSITIVE", f"False positive - PostHog {ctr:.0f}% CTR", "#34c759",
                f"PostHog shows {clicks} clicks at {ctr:.1f}% CTR - real users are engaging. BQ low CTR is the email/scanner artifact. Do not file a ticket.")
    if ctr >= 15:
        return ("INCONCLUSIVE", f"Inconclusive - {ctr:.1f}% CTR", "#ff9500",
                f"PostHog CTR is {ctr:.1f}% on {clicks} clicks - higher than BQ but still below the ~50% baseline. Watch for another week before filing.")
    return ("REAL_ISSUE", f"Real issue - {ctr:.1f}% CTR", "#cf222e",
            f"PostHog CTR is {ctr:.1f}% on {clicks} clicks. Real users on new platform, real low engagement. File Jira, tag Richard, link PostHog session replays.")


def daily_metrics(api_key: str):
    """Pull 14-day trends for new-platform health metrics."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=14)

    def daily_count(condition):
        q = f"""
            SELECT toDate(timestamp) AS d, count() AS c FROM events
            WHERE {condition}
              AND timestamp >= '{start}' AND timestamp <= '{end}'
            GROUP BY d ORDER BY d
        """
        try:
            rows = hogql(q, api_key).get("results", [])
            return {str(r[0]): r[1] for r in rows}
        except urllib.error.HTTPError as e:
            print(f"PostHog HTTP error: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
            return {}

    clicks_new = daily_count("event = 'outbound_click' AND properties.countryCode = 'US' AND properties.x_service = 'coupons-ui'")
    pv_us = daily_count("event = '$pageview' AND properties.$pathname LIKE '/coupons/%' AND properties.$geoip_country_code = 'US'")
    rage = daily_count("event = '$rageclick' AND properties.$pathname LIKE '/coupons/%'")
    dead = daily_count("event = '$dead_click' AND properties.$pathname LIKE '/coupons/%'")

    # Build aligned date array
    dates = []
    d = start
    while d <= end:
        dates.append(d.strftime("%b %-d"))
        d += timedelta(days=1)
    iso_dates = []
    d = start
    while d <= end:
        iso_dates.append(d.isoformat())
        d += timedelta(days=1)

    def align(daily_dict):
        return [daily_dict.get(iso, 0) for iso in iso_dates]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scope": "US, /coupons/* pages, x_service=coupons-ui where applicable",
        "caveat": "PostHog is only instrumented on the new platform for US traffic. coupons-itier-global is tagged countryCode=IE only. Pre-May 8 numbers undercounted due to Cloudflare cache suppressing the snippet.",
        "dates": dates,
        "metrics": {
            "outbound_click_us_new": align(clicks_new),
            "pageview_coupons_us": align(pv_us),
            "rageclick": align(rage),
            "dead_click": align(dead),
        },
    }


def main():
    api_key = os.environ.get("POSTHOG_API_KEY")
    if not api_key:
        print("POSTHOG_API_KEY not set - skipping refresh. To enable: create a Personal API Token at "
              "https://eu.posthog.com/settings/user-api-keys and set POSTHOG_API_KEY in env / GH secret.",
              file=sys.stderr)
        sys.exit(0)  # Don't fail the cron - just skip

    print("Validating flagged merchants against PostHog...")
    validation = merchant_validation(api_key)
    VALIDATION_FILE.write_text(json.dumps(validation, indent=2))
    print(f"Wrote {VALIDATION_FILE} - {validation['summary']}")

    print("\nPulling 14-day PostHog daily metrics...")
    daily = daily_metrics(api_key)
    DAILY_FILE.write_text(json.dumps(daily, indent=2))
    print(f"Wrote {DAILY_FILE}")


if __name__ == "__main__":
    main()
