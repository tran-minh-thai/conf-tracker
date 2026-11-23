# SPDX-License-Identifier: MIT
"""Accuracy audit: do the published paper deadlines appear on the venues' own pages?

Draws a seeded random sample of open, confirmed conferences from data/conferences.json, fetches
each venue URL, extracts the dates printed on the page (the website watcher's extractor), and
classifies each venue:
  match         the deadline date (in any time zone from UTC-12 to UTC+14) is printed on the page
                next to a submission/paper label;
  on_page       the date is printed, but not next to such a label;
  other_date    the page labels a different paper/submission date (likely moved or extended);
  no_dates      the page was read but shows no dates (often rendered by JavaScript);
  unreachable   the page could not be fetched.
Only `other_date` points at a probable data error; the rest is reported with its count.

Usage: python scripts/audit_deadlines.py [--n 40] [--seed 1] [--out evaluation/]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import watch  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
UA = "conf-tracker-audit (+https://github.com/tran-minh-thai/conf-tracker)"


def candidate_days(iso: str) -> set[str]:
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return {(t + timedelta(hours=h)).strftime("%Y-%m-%d") for h in range(-12, 15)}


def classify(conf: dict, html: str | None) -> dict:
    paper = [d for d in conf["deadlines"] if d["type"] in ("paper", "abstract")]
    days = set().union(*(candidate_days(d["iso"]) for d in paper)) if paper else set()
    if html is None:
        return {"status": "unreachable"}
    _, text = watch.visible_text(html)
    found = watch.extract_dates(text)
    if not found:
        return {"status": "no_dates"}
    labelled = [d for d in found if d["label"] in ("paper", "abstract")]
    if any(d["date"] in days for d in labelled):
        return {"status": "match"}
    if any(d["date"] in days for d in found):
        return {"status": "on_page"}
    if labelled:
        return {"status": "other_date", "page_dates": sorted({d["date"] for d in labelled})[:6]}
    return {"status": "no_dates", "note": "dates on the page, none labelled as submission"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=REPO / "evaluation")
    a = ap.parse_args(argv)
    data = json.loads((REPO / "data" / "conferences.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pool = [c for c in data["conferences"] if c["status"] == "confirmed" and c.get("url")
            and any(d["type"] == "paper" and d["iso"] > now for d in c["deadlines"])]
    sample = random.Random(a.seed).sample(pool, min(a.n, len(pool)))
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rows = []
    for c in sample:
        try:
            r = s.get(c["url"], timeout=25)
            html = watch.decode_html(r.content, r.headers.get("content-type")) if r.status_code == 200 else None
        except requests.RequestException:
            html = None
        row = {"id": c["id"], "source": c["source"], "url": c["url"],
               "deadlines": [d["iso"] for d in c["deadlines"] if d["type"] in ("paper", "abstract")], **classify(c, html)}
        rows.append(row)
        print(f"{row['status']:12s} {c['id']:24s} {c['source']}", file=sys.stderr)
    tally = {k: sum(r["status"] == k for r in rows) for k in ("match", "on_page", "other_date", "no_dates", "unreachable")}
    out = {"kind": "data accuracy audit (machine independent)", "run": now, "seed": a.seed, "n": len(rows),
           "pool": len(pool), "data_last_updated": data["last_updated"], "tally": tally, "rows": rows}
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"deadline-audit-{now.replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(tally))
    print(path.resolve().relative_to(REPO) if path.resolve().is_relative_to(REPO) else path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
