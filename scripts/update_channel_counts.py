# SPDX-License-Identifier: MIT
"""Add one publication year to data/channel_counts.json and drop years older than the window.

Usage:
    python scripts/update_channel_counts.py --dump dblp.xml.gz --year 2025 [--window 5]

For each venue: up to SAMPLE_PER_YEAR papers of that year (seeded by venue and year), found by DOI
(venues whose DBLP records carry DOIs) or by listing the venue's OpenAlex sources and matching DBLP
titles exactly. Keywords and topics come from OpenAlex, abstracts from arXiv; abstracts are tokenized
in memory and never written. Needs the OpenAlex key in OPENALEX_API_KEY (or ~/.config/openalex/api_key);
without it the step is skipped with a log line and the file is left unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import channel_counts as cc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--year", type=int, required=True, help="publication year to add")
    ap.add_argument("--window", type=int, default=5, help="years kept, ending at --year")
    ap.add_argument("--counts", type=Path, default=REPO_ROOT / "data" / "channel_counts.json")
    args = ap.parse_args(argv)
    data = json.loads(args.counts.read_text(encoding="utf-8"))
    y = args.year
    if y in data["years"]:
        print(f"channel counts already hold {y} (years {data['years'][0]}-{data['years'][-1]}); nothing to add")
        return 0
    oa = cc.OpenAlex()
    if not oa.has_key:
        print(f"OPENALEX_API_KEY is not set: skipping the OpenAlex and arXiv step; "
              f"data/channel_counts.json keeps years {data['years'][0]}-{data['years'][-1]}")
        return 0
    venues = data["venues"]
    rows = defaultdict(list)
    for k, yr, title, doi in cc.read_dump(args.dump, set(venues), range(y, y + 1)):
        rows[k].append((title, doi))
    print(f"1. DBLP papers of {y} for {len(rows)} of {len(venues)} venues")
    added = 0
    for k in sorted(venues):
        v = venues[k]
        papers = rows.get(k, [])
        try:
            if v["mode"] == "doi":
                dois = cc.sample([d for _, d in papers if d], f"{k}:{y}", cc.SAMPLE_PER_YEAR)
                found = cc.works_by_doi(oa, dois)
                works = [(y, found[d]) for d in dois if d in found]
            else:
                titles = {cc.norm_title(t): t for t, _ in papers}
                found = cc.works_by_source(oa, v.get("listing_sources", []), y, titles) if titles else {}
                works = [(y, found[n]) for n in cc.sample(list(found), f"{k}:{y}", cc.SAMPLE_PER_YEAR)]
        except RuntimeError as exc:
            print(f"  [error] {k}: {exc}; stopping, file not written")
            return 2
        new = cc.aggregate(works)
        for ch in cc.CHANNEL_NAMES:
            v[ch] = cc.drop_years(cc.merge(v.get(ch, {"n_by_year": {}, "terms": {}}), new[ch]), y - args.window + 1)
        added += len(works)
    data["years"] = list(range(y - args.window + 1, y + 1))
    data["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    args.counts.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(f"2. added {added} papers of {y}; years now {data['years'][0]}-{data['years'][-1]}; OpenAlex requests left {oa.remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
