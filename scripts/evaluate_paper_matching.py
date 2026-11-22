# SPDX-License-Identifier: MIT
"""Held-out evaluation of "find venues for a paper" (abstract + contributions query).

Usage:
    python scripts/evaluate_paper_matching.py --dump dblp.xml.gz --ccfddl-zip ccf.zip \
        --cache-dir ~/data-local/conf-tracker-eval [--year 2025] [--no-fetch]

Protocol (same as build_profiles.py): profiles from the titles of the five years before
--year, queries from papers of --year, so no query paper is in its venue's profile.
Queries are abstracts of up to 30 papers per venue (venues with at least 5 abstracts),
taken from a fixed per-venue sample of DOIs (seeded by the venue key). Abstracts come
from Semantic Scholar, else Crossref, and are cached in --cache-dir, outside the
repository (publisher text is not redistributed; the DOI sample's hash is recorded).

Compared: the query before this change (one normalised vector per field, summed) and
profiles.paper_vector (fields joined, terms weighted by specificity). Reported per input:
abstract only (on the odd half, the even half having been used to choose the exponent),
abstract plus a short second field (the title stands in for "main contributions"), and
titles only (the published title evaluation, as a guard).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import math
import platform
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftracker import ccfddl, profiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "conf-tracker-evaluation/1.0"
REC = re.compile(r'<inproceedings\b[^>]*\bkey="conf/([^/"]+)/')
TITLE = re.compile(r"<title>(.*?)</title>")
YEAR = re.compile(r"<year>(\d{4})</year>")
DOI = re.compile(r"<ee[^>]*>https?://(?:dx\.)?doi\.org/(10\.[^<\s]+)</ee>")
TAG = re.compile(r"<[^>]+>")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_dump(path: Path, keys: set, years: range):
    """(key, year, title, doi or None) for conference papers of the wanted series."""
    key = None
    with gzip.open(path, "rt", encoding="iso-8859-1", errors="replace") as fh:
        for line in fh:
            if key is None:
                if line.startswith("<inproceedings"):
                    m = REC.match(line)
                    if m and m[1] in keys:
                        key, title, year, doi = m[1], None, None, None
                continue
            if title is None and "<title>" in line:
                m = TITLE.search(line)
                if m:
                    title = html.unescape(TAG.sub("", m[1])).strip()
            elif year is None and "<year>" in line:
                m = YEAR.search(line)
                year = int(m[1]) if m else None
            elif doi is None and "<ee" in line:
                m = DOI.search(line)
                doi = html.unescape(m[1]).strip().lower() if m else None
            if "</inproceedings>" in line:
                if title and year in years:
                    yield key, year, title, doi
                key = None


def doi_sample(rows, year: int, per_venue: int = 80) -> list:
    by = defaultdict(list)
    for k, y, t, doi in rows:
        if y == year and doi:
            by[k].append(doi)
    out = []
    for k in sorted(by):
        items = sorted(by[k])
        random.Random(k).shuffle(items)
        out += items[:per_venue]
    return out


def fetch_s2(dois, cache: dict, path: Path):
    todo = [d for d in dois if d not in cache]
    for i in range(0, len(todo), 400):
        batch = todo[i:i + 400]
        body = json.dumps({"ids": [f"DOI:{d}" for d in batch]}).encode()
        for attempt in range(30):
            try:
                req = urllib.request.Request("https://api.semanticscholar.org/graph/v1/paper/batch?fields=abstract", data=body,
                                             headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
                res = json.load(urllib.request.urlopen(req, timeout=120))
                break
            except Exception:  # rate limited (HTTP 429) or transient
                time.sleep(min(60, 3 * (attempt + 1)))
        else:
            print(f"  [warn] Semantic Scholar batch {i} failed; those DOIs stay unfetched")
            continue
        for d, r in zip(batch, res):
            cache[d] = (r or {}).get("abstract") or ""
        path.write_text(json.dumps(cache), encoding="utf-8")
        time.sleep(3)


def fetch_crossref(dois, cache: dict, path: Path):
    todo = [d for d in dois if d not in cache]
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        q = urllib.parse.urlencode({"filter": ",".join(f"doi:{d}" for d in batch), "select": "DOI,abstract", "rows": 100})
        try:
            req = urllib.request.Request(f"https://api.crossref.org/works?{q}", headers={"User-Agent": USER_AGENT})
            items = json.load(urllib.request.urlopen(req, timeout=60))["message"]["items"]
        except Exception as exc:
            print(f"  [warn] Crossref batch {i} failed: {exc}")
            continue
        got = {it["DOI"].lower(): it.get("abstract", "") for it in items}
        for d in batch:
            cache[d] = got.get(d, "")
        time.sleep(0.3)
    path.write_text(json.dumps(cache), encoding="utf-8")


def clean_abstract(text: str) -> str:
    text = html.unescape(TAG.sub(" ", text or ""))
    text = re.sub(r"^\s*(abstract|summary)\b[:.]?\s*", "", text.strip(), flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def old_query(fields, idf):
    out = {}
    for f in fields:
        if f and f.strip():
            for t, w in profiles.query_vector(f, idf).items():
                out[t] = out.get(t, 0.0) + w
    norm = math.sqrt(sum(w * w for w in out.values())) or 1.0
    return {t: w / norm for t, w in out.items()}


def rank_of(q, key, prof, inverted):
    """Rank of the true venue; a venue sharing no term ranks last (ties broken by key)."""
    sc = defaultdict(float)
    for t, w in q.items():
        for k, v in inverted.get(t, ()):
            sc[k] += w * v
    s = sc.get(key, 0.0)
    if s <= 0:
        return len(prof)
    return 1 + sum(1 for k, v in sc.items() if v > s or (v == s and k < key))


def summary(old, new, keys, areas, seed=7, n_boot=2000):
    m = len(old)
    d = [1 / y - 1 / x for x, y in zip(old, new)]
    rnd = random.Random(seed)
    means = sorted(sum(d[rnd.randrange(m)] for _ in range(m)) / m for _ in range(n_boot))
    per_area = defaultdict(lambda: [0, 0.0, 0.0])
    for k, x, y in zip(keys, old, new):
        a = per_area[areas.get(k) or "?"]
        a[0] += 1
        a[1] += 1 / x
        a[2] += 1 / y

    def block(r):
        return {"mrr": round(sum(1 / x for x in r) / m, 4), **{f"hit@{k}": round(sum(x <= k for x in r) / m, 4) for k in (1, 5, 10)}}
    return {
        "queries": m, "venues": len(set(keys)),
        "before": block(old), "after": block(new),
        "mrr_delta": round(sum(d) / m, 4),
        "mrr_delta_95ci_paired_bootstrap": [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot)], 4)],
        "queries_better": sum(y < x for x, y in zip(old, new)), "queries_worse": sum(y > x for x, y in zip(old, new)),
        "per_area_queries_mrr_before_after": {a: [v[0], round(v[1] / v[0], 4), round(v[2] / v[0], 4)] for a, v in sorted(per_area.items())},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--ccfddl-zip", type=Path, required=True)
    ap.add_argument("--cache-dir", type=Path, required=True, help="abstract caches, outside the repository")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--no-fetch", action="store_true", help="use cached abstracts only")
    ap.add_argument("--eval-dir", type=Path, default=REPO_ROOT / "evaluation")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    y = args.year

    confs, _ = ccfddl.read_zip(args.ccfddl_zip.read_bytes())
    areas = {str(it.get("dblp") or "").strip(): it.get("sub") for doc in confs for it in doc if it.get("dblp")}
    rows = list(read_dump(args.dump, set(areas), range(y - 5, y + 1)))
    print(f"1. papers {y - 5}-{y} of {len(areas)} series: {len(rows)}")

    train = profiles.group_titles((k, yr, t) for k, yr, t, _ in rows if y - 5 <= yr <= y - 1)
    prof, idf_full = profiles.build_profiles(train)
    used = {t for p in prof.values() for t in p["terms"]}
    idf = {t: round(v, 3) for t, v in idf_full.items() if t in used}  # as published
    prof = {k: {"terms": p["terms"]} for k, p in prof.items()}
    inverted = defaultdict(list)
    for k, p in prof.items():
        for t, w in p["terms"].items():
            inverted[t].append((k, w))
    spec = profiles.term_specificity(p["terms"] for p in prof.values())
    print(f"2. held-out profiles from {y - 5}-{y - 1}: {len(prof)} venues, {len(idf)} terms")

    dois = doi_sample(rows, y)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    s2_path, cr_path = args.cache_dir / "s2_abstracts.json", args.cache_dir / "crossref_abstracts.json"
    s2 = json.loads(s2_path.read_text(encoding="utf-8")) if s2_path.exists() else {}
    cr = json.loads(cr_path.read_text(encoding="utf-8")) if cr_path.exists() else {}
    if not args.no_fetch:
        fetch_s2(dois, s2, s2_path)
        fetch_crossref([d for d in dois if not s2.get(d)], cr, cr_path)
    titles = {doi: (k, t) for k, yr, t, doi in rows if yr == y and doi}
    by = defaultdict(list)
    for doi in sorted(set(dois)):
        a = clean_abstract(s2.get(doi) or cr.get(doi) or "")
        k, t = titles[doi]
        if len(a.split()) >= 40 and k in prof:
            by[k].append((doi, a, t))
    qa = [(k, a, t) for k in sorted(by) if len(by[k]) >= 5 for _, a, t in sorted(by[k])[:30]]
    n_s2 = sum(1 for d in dois if s2.get(d))
    print(f"3. DOI sample {len(dois)}, abstracts: {n_s2} Semantic Scholar, "
          f"{sum(1 for d in dois if not s2.get(d) and cr.get(d))} Crossref; queries {len(qa)} over "
          f"{len({k for k, _, _ in qa})} venues with at least 5 abstracts")

    def ranks(make, qs):
        return [rank_of(make(fields), k, prof, inverted) for k, fields in qs]
    old = lambda fields: old_query(fields, idf)  # noqa: E731
    new = lambda fields: profiles.paper_vector(fields, idf, spec)  # noqa: E731
    odd = [(k, [a, ""]) for i, (k, a, _) in enumerate(qa) if i % 2 == 1]
    two = [(k, [a, t]) for k, a, t in qa]
    tq = []
    test_titles = profiles.group_titles((k, yr, t) for k, yr, t, _ in rows if yr == y)
    for key in sorted(prof):
        ts = sorted(test_titles.get(key, []))
        if len(ts) >= 10:
            step = max(1, len(ts) // 30)
            tq += [(key, [t, ""]) for t in ts[::step][:30]]
    result = {}
    for name, qs in (("abstract_only_odd_half", odd), ("abstract_plus_title_as_second_field", two), ("title_only_guard", tq)):
        result[name] = summary(ranks(old, qs), ranks(new, qs), [k for k, _ in qs], areas)
        r = result[name]
        print(f"4. {name}: MRR {r['before']['mrr']} -> {r['after']['mrr']} (delta {r['mrr_delta']}, "
              f"95% CI {r['mrr_delta_95ci_paired_bootstrap']}), {r['queries']} queries, {r['venues']} venues")

    sample_hash = hashlib.sha256("\n".join(dois).encode()).hexdigest()
    tool_files = sorted((REPO_ROOT / "scripts").rglob("*.py"))
    meta = {
        "kind": "data property: paper-to-venue matching accuracy on held-out abstracts (machine independent)",
        "command": " ".join(["python", *[Path(a).name if Path(a).exists() else a for a in sys.argv]]),
        "started": started.isoformat(),
        "python": platform.python_version(),
        "dump_sha256": sha256_file(args.dump),
        "ccfddl_zip_sha256": sha256_file(args.ccfddl_zip),
        "tool_sha256": {p.relative_to(REPO_ROOT).as_posix(): sha256_file(p) for p in tool_files},
        "tokenizer_version": profiles.TOKENIZER_VERSION,
        "specificity_exponent": profiles.SPECIFICITY_EXPONENT,
        "train_years": [y - 5, y - 1], "test_year": y,
        "doi_sample": {"count": len(dois), "sha256": sample_hash, "per_venue": 80},
        "abstract_sources": {"semantic_scholar": n_s2, "crossref": sum(1 for d in dois if not s2.get(d) and cr.get(d))},
        "result": result,
    }
    args.eval_dir.mkdir(parents=True, exist_ok=True)
    out = args.eval_dir / f"paper-matching-{started.strftime('%Y%m%dT%H%M%SZ')}-tok{profiles.TOKENIZER_VERSION}.json"
    out.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(f"5. wrote {out.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
