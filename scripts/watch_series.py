# SPDX-License-Identifier: MIT
"""Check watched conference websites and record what changed.

Usage:
    python scripts/watch_series.py                       # writes data/watch/
    python scripts/watch_series.py --issue issue.md      # also writes a review issue body

Exit code 0 even when pages are unreachable (that is recorded); 2 when the
series file is malformed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import watch  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", type=Path, default=REPO_ROOT / "data" / "watch" / "series.yml")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "watch")
    ap.add_argument("--issue", type=Path, help="write a Markdown review issue when pages changed")
    args = ap.parse_args(argv)
    try:
        series = watch.load_series(args.series)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc).replace(microsecond=0)
    report = watch.run(series, args.out, requests.Session(), now)
    print(f"checked {report['pages']} page(s) of {len(series)} series; "
          f"{len(report['changed'])} changed, {report['errors']} not reachable")
    for c in report["changed"]:
        print(f"  changed: {c['acronym']} {c['url']} ({len(c['dates'])} labelled dates)")
    if args.issue and report["changed"]:
        args.issue.write_text(watch.issue_markdown(report), encoding="utf-8")
        print(f"wrote {args.issue.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
