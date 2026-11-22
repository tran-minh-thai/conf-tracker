# SPDX-License-Identifier: MIT
"""Build data/journal_profiles.json from the DBLP dump and evaluate journal matching.

Usage:
    python scripts/build_journal_profiles.py --dump dblp.xml.gz [--year 2025]

Same method as build_profiles.py (conference venues): TF-IDF over five years of
article titles; held-out evaluation queries the latest year's titles against
profiles built from the five years before it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import crossref_meta, profiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year - 1)
    ap.add_argument("--min-titles", type=int, default=50, help="minimum articles in the five profile years")
    ap.add_argument("--top-k", type=int, default=80)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "journal_profiles.json")
    ap.add_argument("--eval-dir", type=Path, default=REPO_ROOT / "evaluation")
    ap.add_argument("--meta-cache", type=Path, default=REPO_ROOT / "data" / "journal_meta_cache.json",
                    help="cache of Crossref journal titles and ISSNs")
    ap.add_argument("--no-crossref", action="store_true", help="skip resolving full titles and ISSNs")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    y = args.year

    full = list(profiles.iter_journal_dump(args.dump, range(y - 5, y + 1), with_doi=True))
    records = [r[:4] for r in full]
    dois = {}
    for key, yr, _t, _n, doi in sorted(full, key=lambda r: -r[1]):
        if doi and len(dois.setdefault(key, [])) < 3:
            dois[key].append(doi)
    names = {}
    name_votes = {}
    for key, _yr, _t, name in records:
        name_votes.setdefault(key, Counter())[name] += 1
    for key, votes in name_votes.items():
        names[key] = votes.most_common(1)[0][0]
    print(f"1. journal articles {y - 5}-{y}: {len(records)} in {len(names)} journals")
    if not records:
        print("ERROR: no articles read", file=sys.stderr)
        return 2

    train = profiles.group_titles((k, yr, t) for k, yr, t, _ in records if y - 5 <= yr <= y - 1)
    test = profiles.group_titles((k, yr, t) for k, yr, t, _ in records if yr == y)
    train = {k: v for k, v in train.items() if len(v) >= args.min_titles}
    evaluation = profiles.evaluate(train, test, names)
    print(f"2. held-out evaluation: {json.dumps(evaluation)}")

    final = profiles.group_titles((k, yr, t) for k, yr, t, _ in records if y - 4 <= yr <= y)
    prof, idf = profiles.build_profiles(final, top_k=args.top_k, min_titles=args.min_titles)
    meta, meta_stats = ({}, {"skipped": True})
    if not args.no_crossref:
        meta, meta_stats = crossref_meta.resolve({k: dois.get(k, []) for k in prof}, args.meta_cache)
        print(f"   Crossref titles/ISSNs: {len(meta)}/{len(prof)} resolved "
              f"(cached {meta_stats['cached']}, queried {meta_stats['queried']}, failed {len(meta_stats['failed'])})")
    for k in prof:
        prof[k]["name"] = meta.get(k, {}).get("title") or names.get(k, k)
        prof[k]["abbrev"] = names.get(k, k)
        prof[k]["issn"] = meta.get(k, {}).get("issn", [])
        prof[k]["publisher"] = meta.get(k, {}).get("publisher", "")
    used = {t for p in prof.values() for t in p["terms"]}
    payload = {
        "schema_version": 1,
        "generated_at": started.isoformat(),
        "tokenizer_version": profiles.TOKENIZER_VERSION,
        "years": [y - 4, y],
        "source": "dblp.xml.gz (CC0); preprint series excluded: " + ", ".join(sorted(profiles.NOT_JOURNALS)),
        "dump_sha256": sha256(args.dump),
        "stopwords": profiles.STOPWORDS,
        "idf": {t: round(v, 3) for t, v in sorted(idf.items()) if t in used},
        "profiles": dict(sorted(prof.items())),
        "evaluation": evaluation,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"3. wrote {args.out.as_posix()}: {len(prof)} journals, {len(payload['idf'])} terms, {args.out.stat().st_size} bytes")

    args.eval_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    eval_path = args.eval_dir / f"journal-matching-{stamp}-tok{profiles.TOKENIZER_VERSION}.json"
    eval_path.write_text(json.dumps({
        "kind": "data property: journal matcher accuracy on held-out titles (machine independent)",
        "command": " ".join(["python", *[Path(a).name if Path(a).exists() else a for a in sys.argv]]),
        "started": started.isoformat(), "python": platform.python_version(),
        "dump_sha256": payload["dump_sha256"], "tokenizer_version": profiles.TOKENIZER_VERSION,
        "tool_sha256": {p.relative_to(REPO_ROOT).as_posix(): sha256(p) for p in sorted((REPO_ROOT / "scripts").rglob("*.py"))},
        "train_years": [y - 5, y - 1], "test_year": y, "min_titles": args.min_titles, "top_k": args.top_k,
        "crossref_meta": {k: v for k, v in meta_stats.items() if k != "failed"} | {"failed_count": len(meta_stats.get("failed", []))},
        "result": evaluation,
    }, indent=1) + "\n", encoding="utf-8")
    print(f"4. wrote {eval_path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
