#!/usr/bin/env python3
"""Refresh Phase 2 monitoring data from BigQuery and update dashboard."""

import json
import subprocess
import sys
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BQ_PROJECT = "prj-grp-coupons-prod-8892"
MERCHANTS_FILE = REPO_ROOT / "merchants.json"
DATA_FILE = REPO_ROOT / "phase2-data.json"
DASHBOARD_FILE = REPO_ROOT / "ctr-rollout-report.html"


def run_bq_query(query):
    """Run a BQ query and return parsed JSON results."""
    result = subprocess.run(
        ["bq", "query", f"--project_id={BQ_PROJECT}", "--use_legacy_sql=false",
         "--format=json", "--max_rows=200000", query],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"BQ Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    # bq output may have a status line before the JSON
    output = result.stdout.strip()
    for line in output.split('\n'):
        line = line.strip()
        if line.startswith('['):
            return json.loads(line)
    return json.loads(output)


def load_merchant_buckets():
    """Load merchant name -> bucket mapping from merchants.json."""
    merchants = json.load(open(MERCHANTS_FILE))
    mapping = {}
    for m in merchants:
        mapping[m['n'].lower()] = m['b']
    return mapping


def pull_cohort_data():
    """Pull daily merchant-level data from BQ and aggregate by cohort."""
    print("Pulling data from BigQuery...")
    raw = run_bq_query("""
        SELECT
            transaction_date,
            merchant_name,
            SUM(Clicks) as clicks,
            SUM(Unique_Views) as unique_views,
            SUM(Transactions) as transactions,
            ROUND(SUM(Commission), 2) as commission
        FROM `prj-grp-coupons-prod-8892.rep.12_offer_dashboard`
        WHERE country = "US" AND domain = "Groupon"
            AND transaction_date >= "2026-03-10"
        GROUP BY transaction_date, merchant_name
    """)
    print(f"  Got {len(raw)} rows")

    name_to_bucket = load_merchant_buckets()

    # Aggregate by date + cohort
    daily = defaultdict(lambda: defaultdict(lambda: {
        'clicks': 0, 'uv': 0, 'txn': 0, 'comm': 0.0
    }))

    for r in raw:
        date = r['transaction_date']
        name = r['merchant_name']
        bucket = name_to_bucket.get(name.lower(), '33pct')
        d = daily[date][bucket]
        d['clicks'] += int(r['clicks'] or 0)
        d['uv'] += int(r['unique_views'] or 0)
        d['txn'] += int(r['transactions'] or 0)
        d['comm'] += float(r['commission'] or 0)

    # Exclude dates with likely incomplete data (commission < 20% of recent avg)
    dates = sorted(daily.keys())
    # Keep all dates but flag incomplete ones
    result = {'dates': [], 'cohorts': {}, 'updated': '', 'incomplete_from': None}
    for cohort in ['legacy', '5050', 'phase1_100', '33pct']:
        result['cohorts'][cohort] = {
            'ctr': [], 'rpv': [], 'uv': [], 'comm': []
        }

    # Detect incomplete commission days (last 3 days often lag)
    all_comm = []
    for date in dates:
        total = sum(daily[date][c]['comm'] for c in ['legacy', '5050', '33pct'])
        all_comm.append((date, total))

    # Average of days with full data (excluding last 3)
    if len(all_comm) > 5:
        full_avg = sum(c for _, c in all_comm[:-3]) / (len(all_comm) - 3)
        for date, comm in all_comm[-3:]:
            if comm < full_avg * 0.3:
                if result['incomplete_from'] is None:
                    result['incomplete_from'] = date

    for date in dates:
        d_parts = date.split('-')
        month = int(d_parts[1])
        day = int(d_parts[2])
        month_name = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May'][month]
        result['dates'].append(f"{month_name} {day}")

        for cohort in ['legacy', '5050', 'phase1_100', '33pct']:
            d = daily[date].get(cohort, {'clicks': 0, 'uv': 0, 'txn': 0, 'comm': 0.0})
            ctr = round(d['clicks'] / d['uv'] * 100, 3) if d['uv'] > 0 else 0
            rpv = round(d['comm'] / d['uv'] * 100, 4) if d['uv'] > 0 else 0
            result['cohorts'][cohort]['ctr'].append(ctr)
            result['cohorts'][cohort]['rpv'].append(rpv)
            result['cohorts'][cohort]['uv'].append(d['uv'])
            result['cohorts'][cohort]['comm'].append(round(d['comm'], 2))

    # Compute baseline stats (Mar 10-17 = first 8 days)
    result['stats'] = {}
    for cohort in ['legacy', '5050', 'phase1_100', '33pct']:
        c = result['cohorts'][cohort]
        pre_ctr = c['ctr'][:8]
        post_ctr = c['ctr'][8:]
        pre_avg = sum(pre_ctr) / len(pre_ctr) if pre_ctr else 0
        post_avg = sum(post_ctr) / len(post_ctr) if post_ctr else 0
        ctr_delta = ((post_avg - pre_avg) / pre_avg * 100) if pre_avg > 0 else 0

        pre_rpv = c['rpv'][:8]
        post_rpv = c['rpv'][8:]
        pre_rpv_avg = sum(pre_rpv) / len(pre_rpv) if pre_rpv else 0
        post_rpv_avg = sum(post_rpv) / len(post_rpv) if post_rpv else 0
        rpv_delta = ((post_rpv_avg - pre_rpv_avg) / pre_rpv_avg * 100) if pre_rpv_avg > 0 else 0

        pre_uv = c['uv'][:8]
        post_uv = c['uv'][8:]
        pre_uv_avg = sum(pre_uv) / len(pre_uv) if pre_uv else 0
        post_uv_avg = sum(post_uv) / len(post_uv) if post_uv else 0
        uv_delta = ((post_uv_avg - pre_uv_avg) / pre_uv_avg * 100) if pre_uv_avg > 0 else 0

        result['stats'][cohort] = {
            'ctr_delta': round(ctr_delta, 1),
            'rpv_delta': round(rpv_delta, 1),
            'uv_delta': round(uv_delta, 1),
            'pre_ctr': round(pre_avg, 2),
            'post_ctr': round(post_avg, 2),
        }

    from datetime import datetime, timezone
    result['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    return result


def update_dashboard_js(data):
    """Update the JavaScript data arrays in the dashboard HTML."""
    html = DASHBOARD_FILE.read_text()

    # Build replacement JS block
    js_lines = []
    js_lines.append(f'const P2_DATES = {json.dumps(data["dates"])};')

    mapping = {
        'legacy': 'LEGACY', '5050': '5050',
        'phase1_100': 'PHASE1', '33pct': '33PCT'
    }
    for cohort, tag in mapping.items():
        c = data['cohorts'][cohort]
        js_lines.append(f'const P2_CTR_{tag} = {json.dumps(c["ctr"])};')
        js_lines.append(f'const P2_RPV_{tag} = {json.dumps(c["rpv"])};')
        js_lines.append(f'const P2_UV_{tag} = {json.dumps(c["uv"])};')
        js_lines.append(f'const P2_COMM_{tag} = {json.dumps(c["comm"])};')
    js_lines.append('const P2_ROLLOUT_IDX = 8;')

    new_js = '\n'.join(js_lines)

    # Replace between markers
    pattern = r'(// Phase 2 Monitoring Charts.*?\n// ═+\n)const P2_DATES.*?const P2_ROLLOUT_IDX = \d+;'
    replacement = r'\g<1>' + new_js
    html_new = re.sub(pattern, replacement, html, flags=re.DOTALL)

    if html_new == html:
        print("WARNING: Could not find JS data block to replace", file=sys.stderr)
        return False

    # Update stat card values
    for cohort, tag in [('legacy', 'Legacy Protected'), ('5050', '50/50 A/B'),
                         ('33pct', '33% Split'), ('phase1_100', 'Phase 1')]:
        s = data['stats'][cohort]
        # Update the "updated" timestamp in the subtitle

    html_new = re.sub(
        r'Data through Mar \d+',
        f'Data through {data["dates"][-1]}',
        html_new
    )

    DASHBOARD_FILE.write_text(html_new)
    print(f"  Updated dashboard JS ({len(data['dates'])} dates)")
    return True


def main():
    data = pull_cohort_data()

    # Save raw data
    json.dump(data, open(DATA_FILE, 'w'), indent=2)
    print(f"Saved {DATA_FILE}")

    # Print summary
    print("\nCohort Summary (baseline Mar 10-17 vs post Mar 18+):")
    for cohort in ['legacy', '5050', 'phase1_100', '33pct']:
        s = data['stats'][cohort]
        print(f"  {cohort:15s} CTR: {s['ctr_delta']:+.1f}%  RPV: {s['rpv_delta']:+.1f}%  UV: {s['uv_delta']:+.1f}%")

    # Update dashboard
    update_dashboard_js(data)
    print(f"\nLast updated: {data['updated']}")


if __name__ == '__main__':
    main()
