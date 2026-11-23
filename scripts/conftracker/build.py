# SPDX-License-Identifier: MIT
"""Merge sources, validate the result and write the published data files."""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from . import ics, parsing
from .topics import AREAS

SCHEMA_VERSION = 2
PREFIX = re.compile(r"^(ieee|acm|springer|eai|ifip|siam|usenix)\s+", re.I)
SUFFIX = re.compile(r"(--?ei|\s*\|.*)$", re.I)
RANKED = ("ccf", "core")


def norm_acronym(acronym: str) -> str:
    a = PREFIX.sub("", acronym.strip())
    a = SUFFIX.sub("", a)
    return re.sub(r"[^a-z0-9]", "", a.lower())


def dedup_key(acronym: str, year) -> str:
    return f"{norm_acronym(acronym)}{year}"


def norm_name(name: str) -> str:
    n = re.sub(r"\b\d+(st|nd|rd|th)\b", " ", (name or "").lower())
    n = re.sub(r"\b(international|conference|symposium|workshop|on|the|of|and|in|ieee|acm|annual)\b", " ", n)
    return re.sub(r"[^a-z]+", " ", n).strip()


def same_venue(a: str, b: str, threshold: float = 0.6) -> bool:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def is_ranked(ed: dict) -> bool:
    return any(ed["rank"].get(k) for k in RANKED)


EXTRA_DEFAULTS = {"scope": "international", "fees": None, "keywords": [], "publisher": None, "checked": None}


def merge_curated(ccf_editions, curated_editions):
    """Add hand-checked editions. A curated edition replaces an estimate of the
    same venue and year; a confirmed ccfddl edition wins but takes the curated fees."""
    by_key = {dedup_key(e["acronym"], e["year"]): e for e in ccf_editions}
    out = list(ccf_editions)
    stats = {"curated_added": 0, "curated_replaced_estimate": 0, "curated_skipped_confirmed": 0}
    for c in curated_editions:
        existing = by_key.get(dedup_key(c["acronym"], c["year"]))
        if existing is not None and existing["status"] == "confirmed":
            if c.get("fees") and not existing.get("fees"):
                existing["fees"] = c["fees"]
            stats["curated_skipped_confirmed"] += 1
            continue
        if existing is not None:
            if not any(c["rank"].values()):
                c["rank"] = existing["rank"]
            if not c.get("dblp"):
                c["dblp"] = existing.get("dblp")
            if not c.get("accept_rates"):
                c["accept_rates"] = existing.get("accept_rates", [])
            out.remove(existing)
            stats["curated_replaced_estimate"] += 1
        out.append(c)
        stats["curated_added"] += 1
    return out, stats


def merge(ccf_editions, wiki_editions):
    """Combine both sources; ccfddl wins, WikiCFP fills gaps.

    A WikiCFP call that matches a ccfddl series (same acronym and a similar
    full name) inherits that series' rank, area and DBLP key, and replaces an
    estimated edition of the same year because it is a published call.
    """
    by_key = {dedup_key(e["acronym"], e["year"]): e for e in ccf_editions}
    series = {}
    for e in ccf_editions:
        series.setdefault(norm_acronym(e["acronym"]), e)
    merged = list(ccf_editions)
    stats = {"wikicfp_dup": 0, "wikicfp_inherited": 0, "wikicfp_replaced_estimate": 0, "wikicfp_added": 0}
    seen, ids = set(), {e["id"] for e in ccf_editions}
    for w in wiki_editions:
        key = dedup_key(w["acronym"], w["year"])
        # The same call is listed under several WikiCFP categories; two
        # different venues can still share an acronym, so the name is part of the key.
        seen_key = (key, norm_name(w["full_name"]))
        if seen_key in seen:
            stats["wikicfp_dup"] += 1
            continue
        seen.add(seen_key)
        wid, n = f"wikicfp_{key}", 2
        while wid in ids:
            wid, n = f"wikicfp_{key}_{n}", n + 1
        w["id"] = wid
        ids.add(wid)
        parent = series.get(norm_acronym(w["acronym"]))
        if parent is not None and not same_venue(parent["full_name"], w["full_name"]):
            parent = None
        existing = by_key.get(key)
        if existing is not None and parent is not None:
            if existing["status"] == "confirmed":
                stats["wikicfp_dup"] += 1
                continue
            merged.remove(existing)
            stats["wikicfp_replaced_estimate"] += 1
        if parent is not None:
            for field in ("rank", "dblp", "sub", "topic", "accept_rates"):
                w[field] = parent[field]
            w["kind"] = "conference"
            stats["wikicfp_inherited"] += 1
        merged.append(w)
        stats["wikicfp_added"] += 1
    merged.sort(key=lambda e: (e["deadlines"][0]["iso"] if e["deadlines"] else "9999", e["acronym"]))
    return merged, stats


REQUIRED = {
    "id": str, "acronym": str, "full_name": str, "year": int, "kind": str, "sub": str,
    "topic": str, "rank": dict, "url": str, "timezone": str, "tz_known": bool,
    "deadlines": list, "place": str, "city": str, "country": str, "mode": str,
    "status": str, "accept_rates": list, "source": str,
}
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate(payload: dict) -> list[str]:
    """Return a list of problems; empty means the payload is publishable."""
    problems = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version is {payload.get('schema_version')!r}, expected {SCHEMA_VERSION}")
    confs = payload.get("conferences")
    if not isinstance(confs, list) or not confs:
        return problems + ["conferences is empty or missing"]
    ids = set()
    for i, c in enumerate(confs):
        where = f"conferences[{i}] ({c.get('id', '?')})"
        for field, typ in REQUIRED.items():
            if not isinstance(c.get(field), typ):
                problems.append(f"{where}: field {field!r} missing or not {typ.__name__}")
        if c.get("id") in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(c.get("id"))
        if c.get("sub") not in AREAS:
            problems.append(f"{where}: unknown area {c.get('sub')!r}")
        if c.get("status") not in ("confirmed", "estimated"):
            problems.append(f"{where}: bad status {c.get('status')!r}")
        if c.get("mode") not in ("in-person", "online", "hybrid", "tbd"):
            problems.append(f"{where}: bad mode {c.get('mode')!r}")
        if not c.get("deadlines"):
            problems.append(f"{where}: no deadlines")
        for d in c.get("deadlines") or []:
            if d.get("type") not in ics.LABELS or not ISO_Z.match(str(d.get("iso", ""))):
                problems.append(f"{where}: bad deadline {d!r}")
        isos = [d.get("iso", "") for d in c.get("deadlines") or []]
        if isos != sorted(isos):
            problems.append(f"{where}: deadlines not sorted")
        for f in ("event_start", "event_end"):
            if c.get(f) is not None and not DAY.match(str(c[f])):
                problems.append(f"{where}: bad {f} {c[f]!r}")
        if c.get("event_start") and c.get("event_end") and c["event_end"] < c["event_start"]:
            problems.append(f"{where}: event_end before event_start")
        if c.get("url") and "<" in c["url"]:
            problems.append(f"{where}: url contains '<'")
        if c.get("scope") not in ("international", "national"):
            problems.append(f"{where}: bad scope {c.get('scope')!r}")
        fees = c.get("fees")
        if fees is not None:
            if not isinstance(fees, dict) or not fees.get("items") or not str(fees.get("url", "")).startswith("http"):
                problems.append(f"{where}: fees need items and a source url")
            else:
                for f in fees["items"]:
                    if not isinstance(f.get("amount"), (int, float)) or not re.fullmatch(r"[A-Z]{3}", str(f.get("currency"))):
                        problems.append(f"{where}: bad fee item {f!r}")
    return problems


def build_payload(editions, now: datetime, source_stats: dict) -> dict:
    for e in editions:
        for field, default in EXTRA_DEFAULTS.items():
            e.setdefault(field, list(default) if isinstance(default, list) else default)
    counts = {
        "total": len(editions),
        "open_confirmed": sum(
            1 for e in editions if e["status"] == "confirmed"
            and any(d["type"] == "paper" and d["iso"] > now.strftime("%Y-%m-%dT%H:%M:%SZ") for d in e["deadlines"])
        ),
        "estimated": sum(1 for e in editions if e["status"] == "estimated"),
        "ranked": sum(1 for e in editions if is_ranked(e)),
        "ccfddl": sum(1 for e in editions if e["source"] == "ccfddl"),
        "wikicfp": sum(1 for e in editions if e["source"] == "wikicfp"),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "total": len(editions),
        "counts": counts,
        "source_stats": source_stats,
        "areas": AREAS,
        # Country name -> ISO code, for showing names in the page language. Names without a code
        # are listed so a new spelling from a source is noticed instead of shown untranslated.
        "country_codes": parsing.COUNTRY_CODES,
        "countries_without_code": sorted({e["country"] for e in editions}
                                         - set(parsing.COUNTRY_CODES) - {"TBD", "Online"}),
        "conferences": editions,
    }


def feed_events(editions, now: datetime):
    """Deadlines for the subscribable feed: ranked, confirmed, future."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for e in editions:
        if e["status"] != "confirmed" or e["kind"] != "conference" or not is_ranked(e):
            continue
        for ev in ics.deadline_events(e):
            if ev["when"].strftime("%Y-%m-%dT%H:%M:%SZ") > stamp:
                yield ev


class ShrinkGuard(RuntimeError):
    pass


def check_shrink(previous_path: Path, new_total: int, min_ratio: float = 0.5):
    """Refuse to overwrite good data with a run that lost most venues."""
    if not previous_path.exists():
        return
    try:
        prev = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    prev_total = int(prev.get("total") or len(prev.get("conferences") or []))
    if prev_total and new_total < min_ratio * prev_total:
        raise ShrinkGuard(
            f"new total {new_total} is below {min_ratio:.0%} of the previous {prev_total} in {previous_path}; "
            "rerun with --force if the drop is real"
        )


def write_outputs(payload: dict, out_dir: Path, now: datetime) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "conferences.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    events = sorted(feed_events(payload["conferences"], now), key=lambda e: e["when"])
    ics_path = out_dir / "deadlines.ics"
    with open(ics_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(ics.calendar(events, "conf-tMtTracker: ranked conference deadlines", now))
    return {"json": json_path.as_posix(), "ics": ics_path.as_posix(), "feed_events": len(events)}
