# SPDX-License-Identifier: MIT
"""Fetch conference deadlines and write data/conferences.json and data/deadlines.ics.

Usage:
    python scripts/fetch_conferences.py                 # full run (network)
    python scripts/fetch_conferences.py --ccfddl-zip ccf.zip --no-wikicfp
    python scripts/fetch_conferences.py --force         # accept a large drop in venues
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import build, ccfddl, curated, wikicfp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ccfddl-zip", type=Path, help="use a local copy of the ccfddl archive instead of downloading")
    ap.add_argument("--no-wikicfp", action="store_true", help="skip the WikiCFP supplement")
    ap.add_argument("--wikicfp-pages", type=int, default=2, help="listing pages per WikiCFP category (default 2)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data", help="output directory (default: data/)")
    ap.add_argument("--force", action="store_true", help="write even if the venue count dropped by half")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    print(f"Run at {now.isoformat()}")

    if args.ccfddl_zip:
        blob = args.ccfddl_zip.read_bytes()
        print(f"1. ccfddl: read {args.ccfddl_zip} ({len(blob)} bytes)")
    else:
        print(f"1. ccfddl: downloading {ccfddl.CCFDDL_ZIP_URL}")
        resp = requests.get(ccfddl.CCFDDL_ZIP_URL, timeout=120)
        resp.raise_for_status()
        blob = resp.content
    conf_docs, rate_docs = ccfddl.read_zip(blob)
    ccf_eds, ccf_stats = ccfddl.build_editions(conf_docs, rate_docs, now)
    print(f"   series {ccf_stats['series']}, confirmed editions {ccf_stats['confirmed']}, "
          f"estimated editions {ccf_stats['estimated']}")
    if ccf_stats["unknown_tz"]:
        print(f"   [warn] unknown time zones (shown as AoE and flagged): {ccf_stats['unknown_tz']}")
    if not ccf_eds:
        print("ERROR: ccfddl produced no editions; refusing to write.", file=sys.stderr)
        return 2

    wiki_eds, wiki_stats = [], {"skipped": True}
    if not args.no_wikicfp:
        print("2. WikiCFP: fetching listing pages")
        wiki_eds, wiki_stats = wikicfp.fetch(now, max_pages=args.wikicfp_pages)
        print(f"   pages {wiki_stats['pages']}, rows {wiki_stats['rows']}, open calls {len(wiki_eds)}")
        for err in wiki_stats["errors"]:
            print(f"   [warn] {err}")
    else:
        print("2. WikiCFP: skipped (--no-wikicfp)")

    curated_dir = args.out / "curated"
    try:
        cur_eds, cur_stats = curated.load_venues(curated_dir / "venues.yml", now)
        fees = curated.load_fees(curated_dir / "fees.yml")
    except curated.CuratedError as exc:
        print(f"ERROR: curated data: {exc}", file=sys.stderr)
        return 5
    print(f"3. curated: {cur_stats}, fee records {len(fees)}")
    if cur_stats["past"]:
        print(f"   [warn] {cur_stats['past']} curated venue(s) have only old deadlines; update or remove them")
    base, cur_merge = build.merge_curated(ccf_eds, cur_eds)
    merged, merge_stats = build.merge(base, wiki_eds)
    merge_stats.update(cur_merge)
    merge_stats["fees_attached"] = curated.apply_fees(merged, fees)
    print(f"4. merge: {merge_stats}")
    payload = build.build_payload(merged, now, {"ccfddl": ccf_stats, "wikicfp": wiki_stats,
                                                "curated": cur_stats, "merge": merge_stats})

    problems = build.validate(payload)
    if problems:
        print(f"ERROR: {len(problems)} validation problem(s); nothing written:", file=sys.stderr)
        for p in problems[:30]:
            print(f"   {p}", file=sys.stderr)
        return 3
    if not args.force:
        try:
            build.check_shrink(args.out / "conferences.json", payload["total"])
        except build.ShrinkGuard as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 4

    written = build.write_outputs(payload, args.out, now)
    print(f"5. wrote {written['json']} ({payload['total']} editions, counts {payload['counts']})")
    print(f"   wrote {written['ics']} ({written['feed_events']} deadline events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
