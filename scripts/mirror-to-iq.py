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
FOLDER_ID = os.environ.get("GROUPON_IQ_FOLDER_ID", "1bf5a4d4-ddde-4ec3-8a08-e09bf70afba8")

# Sibling JSON files that the dashboard fetches at runtime. The GIQ snapshot
# needs them inlined since only the HTML gets uploaded.
EMBED_FILES = [
    "phase2-data.json",
    "posthog-validation.json",
    "posthog-daily.json",
    "flagged-merchants.json",
]

# SSL context with certifi if available
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


def build_snapshot_html() -> bytes:
    """Read the live HTML, inline sibling JSONs as a fetch override.

    The dashboard does `fetch('phase2-data.json')` etc at runtime to render
    the dynamic cards. GIQ only stores the HTML file, so those fetches 404.
    We inject a small <script> at the top of <body> that overrides fetch()
    to return the embedded data for those specific files, falling back to
    the original fetch for everything else (CDN assets etc).

    Output is bytes (not written to disk). The live HTML on GitHub Pages
    is unchanged - this snapshot is only built in memory for upload.
    """
    html = HTML_FILE.read_text(encoding="utf-8")
    embedded = {}
    for fname in EMBED_FILES:
        p = REPO_ROOT / fname
        if p.exists():
            try:
                embedded[fname] = json.loads(p.read_text(encoding="utf-8"))
                print(f"  Inlined {fname} ({p.stat().st_size:,} bytes)")
            except json.JSONDecodeError as e:
                print(f"  Skipped {fname}: {e}", file=sys.stderr)
        else:
            print(f"  Skipped {fname}: not found", file=sys.stderr)

    embedded_js = json.dumps(embedded)
    inject = (
        '<script>\n'
        '/* GIQ snapshot override: serve inlined sibling JSONs since the '
        'GIQ-hosted report has no companion files. The live GitHub Pages '
        'version does not have this script - normal fetch hits the real '
        'JSON files on disk. */\n'
        f'window.__EMBEDDED__ = {embedded_js};\n'
        '(function(){\n'
        '  var _origFetch = window.fetch.bind(window);\n'
        '  window.fetch = function(url, opts){\n'
        '    try {\n'
        '      var clean = String(url).split(\'?\')[0].split(\'/\').pop();\n'
        '      if (window.__EMBEDDED__[clean]) {\n'
        '        return Promise.resolve({\n'
        '          ok: true,\n'
        '          status: 200,\n'
        '          json: function(){ return Promise.resolve(window.__EMBEDDED__[clean]); }\n'
        '        });\n'
        '      }\n'
        '    } catch(e) {}\n'
        '    return _origFetch(url, opts);\n'
        '  };\n'
        '})();\n'
        '</script>\n'
    )

    if "<body>" in html:
        html = html.replace("<body>", "<body>\n" + inject, 1)
    else:
        # Fall back to prepending if no <body> tag
        html = inject + html
    return html.encode("utf-8")


def build_multipart(content: bytes, filename: str, boundary: str) -> bytes:
    """Build a minimal multipart/form-data body with one file field."""
    body = []
    body.append(f"--{boundary}\r\n".encode())
    body.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    body.append(b"Content-Type: text/html\r\n\r\n")
    body.append(content)
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
    print(f"Building self-contained snapshot...")
    snapshot_bytes = build_snapshot_html()
    print(f"  Snapshot is {len(snapshot_bytes):,} bytes")
    print(f"Uploading as new version of report {report_id}")

    boundary = "----GIQMirror" + datetime.now().strftime("%Y%m%d%H%M%S")
    body = build_multipart(snapshot_bytes, HTML_FILE.name, boundary)

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
            print(f"GIQ response: {resp.status} {response[:200]}")
    except urllib.error.HTTPError as e:
        print(f"GIQ API error: {e.code} {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)

    # Pin the report to the configured folder. Idempotent - safe to re-run.
    if FOLDER_ID:
        print(f"Pinning report to folder {FOLDER_ID}")
        patch_req = urllib.request.Request(
            f"{BASE_URL}/reports/report/{report_id}",
            data=json.dumps({"folderId": FOLDER_ID}).encode(),
            headers={
                "g-api-key": token,
                "Content-Type": "application/json",
                "User-Agent": "coupons-dashboards-mirror/1.0 (+github.com/mgregor-png/coupons-dashboards)",
            },
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(patch_req, timeout=60, context=_SSL_CTX) as resp:
                pdata = json.loads(resp.read())
                print(f"  Folder set to {pdata.get('folderId')}")
        except urllib.error.HTTPError as e:
            print(f"  Folder PATCH failed: {e.code} {e.read().decode()[:300]}", file=sys.stderr)
            # Don't fail the whole mirror just because of folder placement

    # Update last_uploaded_at in report-map.json
    entry["last_uploaded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["folder_id"] = FOLDER_ID
    REPORT_MAP.write_text(json.dumps(report_map, indent=2) + "\n")
    print(f"Updated last_uploaded_at in {REPORT_MAP.name}: {entry['last_uploaded_at']}")
    print(f"Live at: {entry.get('url')}")


if __name__ == "__main__":
    main()
