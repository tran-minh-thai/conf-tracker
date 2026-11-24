# SPDX-License-Identifier: MIT
"""Build data/venue_channels.json (ranking channels for "find venues for a paper").

Usage:
    python scripts/build_channels.py --dump dblp.xml.gz

Titles come from the DBLP dump for the years held in data/channel_counts.json; keywords and arXiv
terms come from data/channel_counts.json (aggregated counts only). Venues ranked: those with a title
profile in data/venue_profiles.json. Method and settings: scripts/conftracker/channels.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import channel_counts as cc  # noqa: E402
from conftracker import channels, profiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "titles": {"source": "DBLP dump (dblp.xml.gz)", "licence": "CC0"},
    "keywords": {"source": "OpenAlex work keywords and topics", "licence": "CC0 (openalex.org pricing page, read 2026-11-23)"},
    "arxiv": {"source": "arXiv API abstracts, terms only", "licence": "CC0 1.0 for metadata including abstracts (arXiv API terms of use, read 2026-11-23)"},
}


def title_counts(dump, keys: set, years: range) -> dict:
    counts = defaultdict(lambda: defaultdict(Counter))
    n = Counter()
    for k, y, t in profiles.iter_dump(dump, keys, years):
        n[k] += 1
        for term in set(profiles.tokens(t)):
            counts[k][term][str(y)] += 1
    return {k: (n[k], {t: dict(ys) for t, ys in counts[k].items() if sum(ys.values()) >= 2}) for k in keys if n[k]}


def build(title_cnt: dict, counts: dict, venues: list, end_year: int) -> dict:
    out = {}
    for name in channels.ORDER:
        if name == "titles":
            src = {k: title_cnt[k] for k in venues if k in title_cnt}
        else:
            src = {}
            for k in venues:
                ch = counts["venues"].get(k, {}).get(name)
                if ch and sum(ch["n_by_year"].values()) >= channels.MIN_PAPERS:
                    src[k] = cc.to_counts(ch)
        built = channels.build_channel(src, channels.CHANNELS[name], len(venues), end_year)
        out[name] = {**{x: v for x, v in channels.CHANNELS[name].items()}, **built}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--counts", type=Path, default=REPO_ROOT / "data" / "channel_counts.json")
    ap.add_argument("--profiles", type=Path, default=REPO_ROOT / "data" / "venue_profiles.json")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "venue_channels.json")
    args = ap.parse_args(argv)
    counts = json.loads(args.counts.read_text(encoding="utf-8"))
    prof = json.loads(args.profiles.read_text(encoding="utf-8"))
    years = counts["years"]
    venues = sorted(prof["profiles"])
    tc = title_counts(args.dump, set(venues), range(years[0], years[-1] + 1))
    print(f"1. titles {years[0]}-{years[-1]} for {len(tc)} of {len(venues)} venues")
    chans = build(tc, counts, venues, years[-1])
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "years": [years[0], years[-1]],
        "tokenizer_version": profiles.TOKENIZER_VERSION,
        "stopwords": profiles.STOPWORDS,
        "sources": SOURCES,
        "counts_sha256": hashlib.sha256(args.counts.read_bytes()).hexdigest(),
        "fusion": {"method": "weighted sum of per-channel scores, each divided by the query's best score",
                   "order": channels.ORDER, "weights": channels.WEIGHTS},
        "channels": chans,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"2. wrote {args.out.relative_to(REPO_ROOT).as_posix() if args.out.is_relative_to(REPO_ROOT) else args.out.name}: "
          + ", ".join(f"{n} {len(c['venues'])} venues" for n, c in chans.items()) + f"; {args.out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
