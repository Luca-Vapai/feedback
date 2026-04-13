#!/usr/bin/env python3
"""
read_feedback.py — Read live feedback from the SideOutSticks Reviews Sheet.

The Apps Script web app's doGet returns the rows (with optional filters) as
JSON. This script is just a thin client around it. Nothing is cached to disk
on purpose — every call hits the sheet live, so a future Claude session sees
whatever was submitted up to that moment.

Usage:
    # Health check
    python3 read_feedback.py --ping

    # All comments for the cend project, manifesto piece, version 1
    python3 read_feedback.py --project cend --piece manifesto --version 1

    # All comments since 2026-04-13 from a specific reviewer
    python3 read_feedback.py --since 2026-04-13 --reviewer "Andrés Scheck"

    # Pretty-print as a markdown table for human review
    python3 read_feedback.py --project cend --since 2026-04-13 --as-markdown
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR.parent / "config.json"
LOCAL_CONFIG_PATH = SCRIPT_DIR.parent / "config.local.json"


def load_endpoint() -> str:
    """Resolve the GAS endpoint URL, preferring config.local.json."""
    for p in (LOCAL_CONFIG_PATH, CONFIG_PATH):
        if p.exists():
            cfg = json.loads(p.read_text())
            url = cfg.get("google_apps_script_endpoint")
            if url:
                return url
    raise RuntimeError(
        f"google_apps_script_endpoint not found in {LOCAL_CONFIG_PATH} or {CONFIG_PATH}"
    )


def fetch(endpoint: str, params: dict) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{endpoint}?{qs}" if qs else endpoint
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SoutsReadFeedback/1.0 (+cend; python)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "_(no rows)_"
    cols = ["timestamp", "piece_id", "version", "reviewer_name",
            "timecode_start", "timecode_end", "element", "action",
            "priority", "description"]
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        line = "| " + " | ".join(
            str(r.get(c, "")).replace("\n", " ").replace("|", "\\|")
            for c in cols
        ) + " |"
        lines.append(line)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ping", action="store_true", help="Health check, don't read sheet")
    ap.add_argument("--project", dest="project_id", help="Filter by project_id")
    ap.add_argument("--piece", dest="piece_id", help="Filter by piece_id")
    ap.add_argument("--version", help="Filter by version")
    ap.add_argument("--reviewer", dest="reviewer_name", help="Filter by reviewer name (exact, case-insensitive)")
    ap.add_argument("--since", help="ISO date or YYYY-MM-DD; rows with timestamp >= since")
    ap.add_argument("--until", help="ISO date or YYYY-MM-DD; rows with timestamp < until")
    ap.add_argument("--limit", type=int, help="Cap on rows returned")
    ap.add_argument("--as-markdown", action="store_true",
                    help="Print as markdown table instead of JSON")
    args = ap.parse_args()

    endpoint = load_endpoint()

    if args.ping:
        print(json.dumps(fetch(endpoint, {"ping": "1"}), indent=2, ensure_ascii=False))
        return

    params = {
        "project_id": args.project_id,
        "piece_id": args.piece_id,
        "version": args.version,
        "reviewer_name": args.reviewer_name,
        "since": args.since,
        "until": args.until,
        "limit": args.limit,
    }
    result = fetch(endpoint, params)

    if result.get("status") != "ok":
        print(f"ERROR: {result}", file=sys.stderr)
        sys.exit(1)

    if args.as_markdown:
        print(f"# Feedback ({result['count']} rows)\n")
        print(to_markdown(result["rows"]))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
