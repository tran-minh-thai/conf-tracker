# SPDX-License-Identifier: MIT
"""Read the ccfddl/ccf-deadlines repository (MIT licensed) into venue editions.

Besides the editions with an upcoming deadline, this module derives two
things a researcher needs when choosing where to submit:

* an *estimated* next edition for series whose next call is not published
  yet, by moving the latest known deadlines forward one year;
* the acceptance-rate history of each series.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from pathlib import PurePosixPath

import yaml

from .parsing import (
    is_placeholder, parse_deadline, parse_event_dates, parse_place, parse_tz,
    shift_year, to_utc_iso,
)
from .topics import AREAS

CCFDDL_ZIP_URL = "https://github.com/ccfddl/ccf-deadlines/archive/refs/heads/main.zip"

DEADLINE_KEYS = (
    ("abstract_deadline", "abstract"),
    ("deadline", "paper"),
    ("rebuttal_deadline", "rebuttal"),
    ("decision_deadline", "notification"),
)

# Keep editions whose last date passed less than this long ago, so the
# "recently closed" view and pending notifications stay visible.
KEEP_PAST = timedelta(days=60)
MAX_ACCEPT_RATES = 6


def clean_rank(value):
    if value is None:
        return None
    v = str(value).strip()
    return None if v.upper() in ("", "N", "N/A", "NA", "NONE", "-") else v


def read_zip(blob: bytes):
    """Return (conference_docs, accept_rate_docs) as lists of parsed YAML lists."""
    confs, rates = [], []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            parts = PurePosixPath(name).parts
            if not name.endswith(".yml") or len(parts) < 3:
                continue
            target = confs if parts[1] == "conference" else rates if parts[1] == "accept_rates" else None
            if target is None:
                continue
            try:
                doc = yaml.safe_load(zf.read(name))
            except yaml.YAMLError as exc:
                print(f"  [warn] skipping unreadable YAML {name}: {exc}")
                continue
            if isinstance(doc, list):
                target.append(doc)
    return confs, rates


def accept_rate_index(rate_docs) -> dict:
    """Map lower-case series title to its recent acceptance rates (newest last)."""
    index = {}
    for doc in rate_docs:
        for item in doc:
            title = str(item.get("title", "")).strip().lower()
            rows = []
            for r in item.get("accept_rates") or []:
                try:
                    rate = float(r["rate"])
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append({
                    "year": int(r.get("year")) if r.get("year") else None,
                    "rate": round(rate, 4),
                    "accepted": r.get("accepted"),
                    "submitted": r.get("submitted"),
                })
            rows.sort(key=lambda x: x["year"] or 0)
            if title and rows:
                index[title] = rows[-MAX_ACCEPT_RATES:]
    return index


def _deadlines(conf: dict, tz):
    """All parsed deadlines of one edition, sorted by time, plus a TBD flag."""
    out, has_tbd = [], False
    for tl in conf.get("timeline") or []:
        comment = str(tl.get("comment") or "").strip()
        for key, kind in DEADLINE_KEYS:
            if key not in tl:
                continue
            dt = parse_deadline(tl.get(key), tz)
            if dt is None:
                if kind == "paper" and is_placeholder(tl.get(key)):
                    has_tbd = True
                continue
            out.append({"type": kind, "dt": dt, "comment": comment})
    out.sort(key=lambda d: d["dt"])
    return out, has_tbd


def _serialize(deadlines):
    return [{"type": d["type"], "iso": to_utc_iso(d["dt"]), "comment": d["comment"]} for d in deadlines]


def _edition_record(item, conf, deadlines, rates, status, estimated_from=None):
    rank = item.get("rank") or {}
    sub = item.get("sub", "MX")
    place_raw = conf.get("place") or "TBD"
    date_raw = conf.get("date") or "TBD"
    place = parse_place(place_raw)
    start, end = parse_event_dates(date_raw)
    tz_str = conf.get("timezone") or "AoE"
    _, tz_known = parse_tz(tz_str)
    year = int(conf.get("year"))
    return {
        "id": str(conf.get("id") or f"{item.get('title', '').lower()}{year % 100:02d}"),
        "acronym": str(item.get("title", "")).strip(),
        "full_name": str(item.get("description", "")).strip(),
        "year": year,
        "kind": "conference",
        "sub": sub,
        "topic": AREAS.get(sub, sub),
        "rank": {
            "ccf": clean_rank(rank.get("ccf")),
            "core": clean_rank(rank.get("core")),
            "thcpl": clean_rank(rank.get("thcpl")),
        },
        "dblp": str(item.get("dblp") or "").strip() or None,
        "url": str(conf.get("link") or "").strip(),
        "timezone": tz_str,
        "tz_known": tz_known,
        "deadlines": _serialize(deadlines),
        "date": date_raw,
        "event_start": start,
        "event_end": end,
        "place": place_raw,
        "city": place["city"],
        "country": place["country"],
        "mode": place["mode"],
        "status": status,
        "estimated_from": estimated_from,
        "accept_rates": rates,
        "source": "ccfddl",
    }


def build_editions(conf_docs, rate_docs, now: datetime):
    """Return (editions, stats). now must be timezone-aware."""
    rates_by_title = accept_rate_index(rate_docs)
    editions = []
    stats = {"series": 0, "confirmed": 0, "estimated": 0, "unknown_tz": set()}

    for doc in conf_docs:
        for item in doc:
            if not isinstance(item, dict) or not item.get("confs"):
                continue
            stats["series"] += 1
            title = str(item.get("title", "")).strip()
            rates = rates_by_title.get(title.lower(), [])
            parsed = []
            for conf in item["confs"]:
                if not conf.get("year"):
                    continue
                tz_str = conf.get("timezone") or "AoE"
                tz, known = parse_tz(tz_str)
                if not known:
                    stats["unknown_tz"].add(tz_str)
                dls, has_tbd = _deadlines(conf, tz)
                parsed.append((conf, dls, has_tbd))
            parsed.sort(key=lambda p: int(p[0]["year"]))

            has_future_paper = False
            for conf, dls, _ in parsed:
                last = max((d["dt"] for d in dls), default=None)
                if any(d["type"] == "paper" and d["dt"] > now for d in dls):
                    has_future_paper = True
                if last is not None and last >= now - KEEP_PAST:
                    editions.append(_edition_record(item, conf, dls, rates, "confirmed"))
                    stats["confirmed"] += 1

            if has_future_paper:
                continue
            est = _estimate(item, parsed, rates, now)
            if est is not None:
                editions.append(est)
                stats["estimated"] += 1

    stats["unknown_tz"] = sorted(stats["unknown_tz"])
    return editions, stats


def _estimate(item, parsed, rates, now):
    """Project the latest edition with real deadlines forward by one year.

    Returns None when the projected paper deadline would already be past
    (biennial or discontinued series), so no estimate is shown for those.
    """
    with_dates = [p for p in parsed if any(d["type"] == "paper" for d in p[1])]
    if not with_dates:
        return None
    base_conf, base_dls, _ = with_dates[-1]
    base_year = int(base_conf["year"])
    projected = [{"type": d["type"], "dt": shift_year(d["dt"]), "comment": d["comment"]} for d in base_dls]
    if not any(d["type"] == "paper" and d["dt"] > now for d in projected):
        return None
    projected = [d for d in projected if d["dt"] > now] or projected

    # Prefer the announced next edition (with TBD deadlines) for link and venue.
    target_year = base_year + 1
    next_conf = next((c for c, _, _ in parsed if int(c["year"]) == target_year), None)
    conf = dict(next_conf) if next_conf else {
        "year": target_year,
        "link": base_conf.get("link", ""),
        "timezone": base_conf.get("timezone", "AoE"),
        "date": "TBD",
        "place": "TBD",
    }
    slug = "".join(ch for ch in str(item.get("title", "")).lower() if ch.isalnum())
    conf["id"] = f"{slug}{target_year % 100:02d}-est"
    return _edition_record(item, conf, projected, rates, "estimated", estimated_from=base_year)
