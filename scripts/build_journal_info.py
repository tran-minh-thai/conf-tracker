# SPDX-License-Identifier: MIT
"""Build data/journal_info.json: access model and citation figures for the journals in the finder.

Usage:
    python scripts/build_journal_info.py                       # downloads the DOAJ CSV, queries OpenAlex
    python scripts/build_journal_info.py --doaj-csv doaj.csv --year 2025

Rules and sources: scripts/conftracker/journal_info.py. Nothing is written when fewer than half of
the journals are found in OpenAlex (a source outage must not replace good data with empty data).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import journal_info as ji  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOAJ_CSV = "https://doaj.org/csv"
OPENALEX = "https://api.openalex.org"
UA = "conf-tracker (+https://github.com/tran-minh-thai/conf-tracker)"
BATCH = 50


def get(session, url, params, tries=4):
    for i in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code == 200:
                time.sleep(0.15)
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
        except requests.RequestException:
            if i == tries - 1:
                raise
        time.sleep(2 ** i)
    raise RuntimeError(f"OpenAlex kept failing: {url}")


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def counts_by_source(session, ids, year, extra=""):
    out = {}
    for part in chunks(ids, BATCH):
        flt = f"primary_location.source.id:{'|'.join(part)},publication_year:{year}{extra}"
        d = get(session, f"{OPENALEX}/works", {"filter": flt, "group_by": "primary_location.source.id", "per_page": 200})
        for g in d.get("group_by", []):
            out[g["key"].rsplit("/", 1)[-1]] = g["count"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doaj-csv", type=Path, help="use a local DOAJ journal CSV instead of downloading it")
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year - 1, help="year for article counts (default: last full year)")
    ap.add_argument("--profiles", type=Path, default=REPO / "data" / "journal_profiles.json")
    ap.add_argument("--out", type=Path, default=REPO / "data" / "journal_info.json")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    raw = a.doaj_csv.read_bytes() if a.doaj_csv else session.get(DOAJ_CSV, timeout=180).content
    doaj = ji.read_doaj(raw.decode("utf-8"))
    print(f"1. DOAJ: {len(doaj)} ISSNs ({len(raw)} bytes, sha256 {hashlib.sha256(raw).hexdigest()[:12]})")

    profiles = json.loads(a.profiles.read_text(encoding="utf-8"))["profiles"]
    issns = {k: [i for i in (ji.norm_issn(x) for x in p.get("issn", [])) if i] for k, p in profiles.items()}
    all_issns = sorted({i for v in issns.values() for i in v})
    sources = {}
    for part in chunks(all_issns, BATCH):
        d = get(session, f"{OPENALEX}/sources", {"filter": f"issn:{'|'.join(part)}", "per_page": 200,
                                                 "select": "id,display_name,issn,is_oa,is_in_doaj,apc_usd,summary_stats,works_count,type,country_code"})
        for s in d.get("results", []):
            for i in s.get("issn") or []:
                prev = sources.get(i)
                if prev is None or (s.get("works_count") or 0) > (prev.get("works_count") or 0):
                    sources[i] = s
    matched = {k: max((sources[i] for i in v if i in sources), key=lambda s: s.get("works_count") or 0, default=None)
               for k, v in issns.items()}
    found = sum(1 for s in matched.values() if s)
    print(f"2. OpenAlex: {found}/{len(profiles)} journals found by ISSN")
    if found < len(profiles) / 2:
        print("ERROR: fewer than half of the journals found in OpenAlex; nothing written.", file=sys.stderr)
        return 2

    ids = sorted({s["id"].rsplit("/", 1)[-1] for s in matched.values() if s})
    works = counts_by_source(session, ids, a.year)
    hybrid = counts_by_source(session, ids, a.year, ",oa_status:hybrid")
    print(f"3. articles in {a.year}: counts for {len(works)} sources, hybrid articles in {len(hybrid)}")

    journals = {}
    for k, s in matched.items():
        sid = s["id"].rsplit("/", 1)[-1] if s else None
        journals[k] = ji.journal_record(issns[k], doaj, s, works.get(sid, 0) if s else None, hybrid.get(sid, 0) if s else None)
    overrides = ji.load_overrides(REPO / "data" / "curated" / "journal_access.yml", set(journals))
    for k, e in overrides.items():
        journals[k] = ji.apply_override(journals[k], e)
    print(f"   hand-checked entries applied: {len(overrides)}")
    tally = {x: sum(1 for j in journals.values() if j["access"] == x) for x in ("open", "hybrid", "subscription", "unknown")}
    payload = {
        "schema_version": 1,
        "built": now.isoformat(),
        "year": a.year,
        "rules": ji.RULES,
        "sources": {
            "doaj": {"url": DOAJ_CSV, "licence": "CC0 (journal-level metadata)", "sha256": hashlib.sha256(raw).hexdigest(), "issns": len(doaj)},
            "openalex": {"url": OPENALEX, "licence": "CC0", "found": found},
        },
        "counts": {**tally, "hand_checked": len(overrides), "diamond": sum(1 for j in journals.values() if j["diamond"]), "total": len(journals)},
        "journals": journals,
    }
    a.out.write_text(json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    shown = a.out.resolve().relative_to(REPO) if a.out.resolve().is_relative_to(REPO) else a.out.name
    print(f"4. wrote {shown} {payload['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
