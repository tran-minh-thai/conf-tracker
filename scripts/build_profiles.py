# SPDX-License-Identifier: MIT
"""Build data/venue_profiles.json from the DBLP dump and evaluate the matcher.

Usage:
    python scripts/build_profiles.py --dump dblp.xml.gz [--ccfddl-zip ccf.zip] [--year 2025]

Profiles use the titles of the last five years up to --year. The evaluation
builds profiles from the five years before --year and queries with the titles
of --year itself, so no query title was seen while building the profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import ccfddl, profiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def series_names(blob: bytes) -> dict:
    confs, _ = ccfddl.read_zip(blob)
    names = {}
    for doc in confs:
        for item in doc:
            key = str(item.get("dblp") or "").strip()
            if key:
                names[key] = f"{item.get('title', '')} {item.get('description', '')}".strip()
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, required=True, help="path to dblp.xml.gz")
    ap.add_argument("--ccfddl-zip", type=Path, help="local ccfddl archive (downloaded if omitted)")
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year - 1,
                    help="last complete publication year (default: last calendar year)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "venue_profiles.json")
    ap.add_argument("--eval-dir", type=Path, default=REPO_ROOT / "evaluation")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).replace(microsecond=0)

    blob = args.ccfddl_zip.read_bytes() if args.ccfddl_zip else requests.get(ccfddl.CCFDDL_ZIP_URL, timeout=120).content
    names = series_names(blob)
    print(f"1. ccfddl series with a DBLP key: {len(names)}")

    y = args.year
    records = list(profiles.iter_dump(args.dump, set(names), range(y - 5, y + 1)))
    print(f"2. titles read from the dump for {y - 5}-{y}: {len(records)}")
    if not records:
        print("ERROR: no titles read; check the dump path and format.", file=sys.stderr)
        return 2

    train = profiles.group_titles(r for r in records if y - 5 <= r[1] <= y - 1)
    test = profiles.group_titles(r for r in records if r[1] == y)
    evaluation = profiles.evaluate(train, test, names)
    print(f"3. held-out evaluation ({y - 5}-{y - 1} profiles, {y} titles as queries): {json.dumps(evaluation)}")

    final_titles = profiles.group_titles(r for r in records if y - 4 <= r[1] <= y)
    prof, idf = profiles.build_profiles(final_titles)
    used_terms = {t for p in prof.values() for t in p["terms"]}
    missing = sorted(set(names) - set(prof))
    payload = {
        "schema_version": 1,
        "generated_at": started.isoformat(),
        "tokenizer_version": profiles.TOKENIZER_VERSION,
        "years": [y - 4, y],
        "source": "dblp.xml.gz (CC0)",
        "dump_sha256": sha256(args.dump),
        "stopwords": profiles.STOPWORDS,
        "idf": {t: round(v, 3) for t, v in sorted(idf.items()) if t in used_terms},
        "default_idf": round(max(idf.values()), 3),
        "profiles": dict(sorted(prof.items())),
        "evaluation": evaluation,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"4. wrote {args.out.as_posix()}: {len(prof)} profiles, {len(payload['idf'])} terms, "
          f"{args.out.stat().st_size} bytes; no profile (under 30 titles) for {len(missing)} series")

    args.eval_dir.mkdir(parents=True, exist_ok=True)
    tool_files = sorted((REPO_ROOT / "scripts").rglob("*.py"))
    meta = {
        "kind": "data property: matcher accuracy on held-out titles (machine independent)",
        "command": " ".join(["python", *[Path(a).name if Path(a).exists() else a for a in sys.argv]]),
        "started": started.isoformat(),
        "python": platform.python_version(),
        "dump_sha256": payload["dump_sha256"],
        "tool_sha256": {p.relative_to(REPO_ROOT).as_posix(): sha256(p) for p in tool_files},
        "tokenizer_version": profiles.TOKENIZER_VERSION,
        "train_years": [y - 5, y - 1],
        "test_year": y,
        "series_without_profile": missing,
        "result": evaluation,
    }
    # One file per run (time and tokenizer version in the name), so no result is overwritten.
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    eval_path = args.eval_dir / f"matching-{stamp}-tok{profiles.TOKENIZER_VERSION}.json"
    eval_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(f"5. wrote {eval_path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
