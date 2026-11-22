# SPDX-License-Identifier: MIT
"""Full title and ISSNs of a journal, from the Crossref record of one of its articles.

DBLP records give a journal's abbreviation only; Crossref (public, no key) gives
the container title and ISSNs, which let the web app join Scimago ranks by ISSN.
Results are cached in a JSON file so monthly rebuilds only query new journals.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://api.crossref.org/works/"
HEADERS = {"User-Agent": "conf-tracker/2.0 (+https://github.com/tran-minh-thai/conf-tracker)"}


def fmt_issn(s: str) -> str:
    d = "".join(ch for ch in str(s).upper() if ch.isdigit() or ch == "X")
    return f"{d[:4]}-{d[4:]}" if len(d) == 8 else ""


def meta_from_work(msg: dict) -> dict:
    issn = sorted({fmt_issn(x) for x in (msg.get("ISSN") or []) if fmt_issn(x)})
    return {"title": (msg.get("container-title") or [""])[0], "issn": issn, "publisher": msg.get("publisher", "")}


def fetch_one(doi: str, session: requests.Session, tries: int = 3):
    for attempt in range(tries):
        try:
            r = session.get(API + quote(doi, safe="/"), headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(2 + 2 * attempt)
                continue
            r.raise_for_status()
            return meta_from_work(r.json()["message"])
        except requests.RequestException:
            time.sleep(1 + attempt)
    return None


def resolve(candidates: dict, cache_path: Path, workers: int = 4) -> tuple[dict, dict]:
    """candidates: journal key -> list of DOIs (newest first). Returns (meta, stats)."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = {k: dois for k, dois in candidates.items() if k not in cache or not cache[k].get("issn")}
    stats = {"cached": len(candidates) - len(todo), "queried": 0, "resolved": 0, "failed": []}
    session = requests.Session()

    def work(item):
        key, dois = item
        for doi in dois[:3]:
            m = fetch_one(doi, session)
            if m and m["title"]:
                return key, {**m, "doi": doi}
        return key, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, m in pool.map(work, todo.items()):
            stats["queried"] += 1
            if m:
                cache[key] = m
                stats["resolved"] += 1
            else:
                stats["failed"].append(key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return {k: cache[k] for k in candidates if k in cache}, stats
