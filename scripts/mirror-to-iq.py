#!/usr/bin/env python3
"""Mirror the live CTR rollout dashboard to Groupon IQ as a new version.

Designed for weekly cron in GH Actions. Reads report-map.json for the
existing report ID (slug -> id mapping), then POSTs ctr-rollout-report.html
to /reports/reports/{id}/versions to bump the version while preserving the
canonical URL.

Auth: GROUPON_IQ_TOKEN env var (set as repo secret).

Why a slim standalone instead of the full publish_html.py from the
groupon-iq-reports skill? CI doesn't have access to the user's local
.claude/ skill scripts, and a minimal self-contained script is easier
to maintain than vendoring the full skill.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
REPORT_MAP = REPO_ROOT / "report-map.json"
HTML_FILE = REPO_ROOT / "ctr-rollout-report.html"
SLUG = "ctr-rollout-report"
BASE_URL = os.environ.get("GROUPON_IQ_BASE", "https://api.enc.groupon.com")

# SSL context with certifi if available
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


def build_multipart(file_path: Path, boundary: str) -> bytes:
    """Build a minimal multipart/form-data body with one file field."""
    body = []
    body.append(f"--{boundary}\r\n".encode())
    body.append(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
    )
    body.append(b"Content-Type: text/html\r\n\r\n")
    body.append(file_path.read_bytes())
    body.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(body)


def main():
    token = os.environ.get("GROUPON_IQ_TOKEN")
    if not token:
        print("GROUPON_IQ_TOKEN not set - skipping GIQ mirror.", file=sys.stderr)
        sys.exit(0)  # Don't fail the workflow

    if not REPORT_MAP.exists():
        print(f"{REPORT_MAP} not found - aborting", file=sys.stderr)
        sys.exit(1)

    if not HTML_FILE.exists():
        print(f"{HTML_FILE} not found - aborting", file=sys.stderr)
        sys.exit(1)

    report_map = json.loads(REPORT_MAP.read_text())
    entry = report_map.get(SLUG)
    if not entry or "id" not in entry:
        print(f"No GIQ entry for slug '{SLUG}' in report-map.json - aborting", file=sys.stderr)
        sys.exit(1)

    report_id = entry["id"]
    url = f"{BASE_URL}/reports/reports/{report_id}/versions"
    print(f"Uploading {HTML_FILE.name} as new version of report {report_id}")

    boundary = "----GIQMirror" + datetime.now().strftime("%Y%m%d%H%M%S")
    body = build_multipart(HTML_FILE, boundary)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "g-api-key": token,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            # Cloudflare in front of api.enc.groupon.com blocks the default
            # Python urllib UA - send a curl-like UA to match what gpiq.sh does.
            "User-Agent": "coupons-dashboards-mirror/1.0 (+github.com/mgregor-png/coupons-dashboards)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
            response = resp.read().decode("utf-8", errors="replace")
            print(f"GIQ response: {resp.status} {response[:500]}")
    except urllib.error.HTTPError as e:
        print(f"GIQ API error: {e.code} {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)

    # Update last_uploaded_at in report-map.json
    entry["last_uploaded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    REPORT_MAP.write_text(json.dumps(report_map, indent=2) + "\n")
    print(f"Updated last_uploaded_at in {REPORT_MAP.name}: {entry['last_uploaded_at']}")
    print(f"Live at: {entry.get('url')}")


if __name__ == "__main__":
    main()
