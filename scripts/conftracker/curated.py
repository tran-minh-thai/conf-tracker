# SPDX-License-Identifier: MIT
"""Hand-maintained data: extra venues (e.g. national conferences no feed covers)
and registration fees, which no automatic source publishes.

Files (YAML, see data/curated/README.md for the format):
  data/curated/venues.yml   extra editions
  data/curated/fees.yml     fees keyed by acronym and year

Every entry must name the page it was checked on and the date it was checked,
because the site shows these values as verified facts.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .ccfddl import KEEP_PAST
from .parsing import parse_deadline, parse_event_dates, parse_place, parse_tz, shift_year, to_utc_iso
from .topics import AREAS

DEADLINE_TYPES = ("abstract", "paper", "rebuttal", "notification")
CURRENCY = re.compile(r"^[A-Z]{3}$")


class CuratedError(ValueError):
    pass


def _load(path: Path):
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(doc, list):
        raise CuratedError(f"{path.name}: top level must be a list")
    return doc


def _checked(value, where):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise CuratedError(f"{where}: 'checked' must be a YYYY-MM-DD date")


def _url(value, where, field="url"):
    if not isinstance(value, str) or not re.match(r"^https?://\S+$", value):
        raise CuratedError(f"{where}: '{field}' must be an http(s) URL")
    return value


def parse_fees(raw, where):
    out = []
    for i, f in enumerate(raw or []):
        w = f"{where} fees[{i}]"
        if not isinstance(f, dict) or not str(f.get("label", "")).strip():
            raise CuratedError(f"{w}: needs a label")
        try:
            amount = float(f["amount"])
        except (KeyError, TypeError, ValueError):
            raise CuratedError(f"{w}: amount must be a number") from None
        if amount < 0:
            raise CuratedError(f"{w}: amount is negative")
        cur = str(f.get("currency", "")).strip().upper()
        if not CURRENCY.match(cur):
            raise CuratedError(f"{w}: currency must be a 3-letter code")
        out.append({"label": str(f["label"]).strip(), "amount": amount, "currency": cur})
    return out


def load_fees(path: Path) -> dict:
    """Map (normalized acronym, year) to a fee record."""
    from .build import norm_acronym  # local import avoids a cycle

    table = {}
    for i, e in enumerate(_load(path)):
        where = f"fees.yml[{i}]"
        if not isinstance(e, dict) or not e.get("acronym") or not e.get("year"):
            raise CuratedError(f"{where}: needs acronym and year")
        key = (norm_acronym(str(e["acronym"])), int(e["year"]))
        if key in table:
            raise CuratedError(f"{where}: duplicate entry for {e['acronym']} {e['year']}")
        table[key] = {
            "items": parse_fees(e.get("fees"), where),
            "url": _url(e.get("fees_url"), where, "fees_url"),
            "checked": _checked(e.get("checked"), where),
            "note": str(e.get("note") or "").strip(),
        }
        if not table[key]["items"]:
            raise CuratedError(f"{where}: fees list is empty")
    return table


def load_venues(path: Path, now: datetime):
    """Return (editions, stats).

    Every entry is validated. Editions whose dates are recent or ahead are published as
    confirmed. Older editions stay in the file as history: when a series has no edition
    with a paper deadline ahead, its latest edition is moved forward one year and
    published as an estimate (the same rule as for ccfddl series).
    """
    records, stats = [], {"entries": 0, "kept": 0, "past": 0, "estimated": 0}
    for i, e in enumerate(_load(path)):
        where = f"venues.yml[{i}] ({e.get('acronym', '?') if isinstance(e, dict) else '?'})"
        if not isinstance(e, dict):
            raise CuratedError(f"{where}: entry must be a mapping")
        stats["entries"] += 1
        for field in ("acronym", "full_name", "year", "url", "deadlines", "checked"):
            if not e.get(field):
                raise CuratedError(f"{where}: missing '{field}'")
        sub = str(e.get("sub", "MX"))
        if sub not in AREAS:
            raise CuratedError(f"{where}: unknown area '{sub}'")
        scope = str(e.get("scope", "international"))
        if scope not in ("international", "national"):
            raise CuratedError(f"{where}: scope must be international or national")
        tz_label = str(e.get("timezone") or "unstated")
        tz, known = parse_tz(None if tz_label == "unstated" else tz_label)
        if tz_label == "unstated":
            known = False
        deadlines = []
        for j, d in enumerate(e["deadlines"]):
            if not isinstance(d, dict) or d.get("type") not in DEADLINE_TYPES:
                raise CuratedError(f"{where} deadlines[{j}]: type must be one of {DEADLINE_TYPES}")
            dt = parse_deadline(str(d.get("date", "")), tz)
            if dt is None:
                raise CuratedError(f"{where} deadlines[{j}]: unreadable date {d.get('date')!r}")
            deadlines.append({"type": d["type"], "dt": dt, "comment": str(d.get("comment") or "").strip()})
        deadlines.sort(key=lambda d: d["dt"])
        if not any(d["type"] == "paper" for d in deadlines):
            raise CuratedError(f"{where}: needs a paper deadline")
        place_raw = str(e.get("place") or "TBD")
        place = parse_place(place_raw)
        start, end = parse_event_dates(str(e.get("date") or ""))
        year = int(e["year"])
        slug = "".join(ch for ch in str(e["acronym"]).lower() if ch.isalnum())
        fees = parse_fees(e.get("fees"), where)
        rank = e.get("rank") or {}
        rec = {
            "id": f"curated_{slug}{year}",
            "acronym": str(e["acronym"]).strip(),
            "full_name": str(e["full_name"]).strip(),
            "year": year,
            "kind": "conference",
            "sub": sub,
            "topic": AREAS[sub],
            "rank": {"ccf": rank.get("ccf"), "core": rank.get("core"), "thcpl": None},
            "dblp": str(e.get("dblp") or "").strip() or None,
            "url": _url(e["url"], where),
            "timezone": "AoE" if tz_label == "unstated" else tz_label,
            "tz_known": known,
            "deadlines": [{"type": d["type"], "iso": to_utc_iso(d["dt"]), "comment": d["comment"]} for d in deadlines],
            "date": str(e.get("date") or "TBD"),
            "event_start": start,
            "event_end": end,
            "place": place_raw,
            "city": place["city"],
            "country": place["country"],
            "mode": place["mode"],
            "status": "confirmed",
            "estimated_from": None,
            "accept_rates": [],
            "source": "curated",
            "scope": scope,
            "publisher": str(e.get("publisher") or "").strip() or None,
            "checked": _checked(e["checked"], where),
            "fees": {"items": fees, "url": _url(e["fees_url"], where, "fees_url"),
                     "checked": _checked(e["checked"], where), "note": ""} if fees else None,
            "keywords": [str(k).strip().lower() for k in (e.get("keywords") or []) if str(k).strip()],
        }
        records.append((slug, rec, deadlines))

    eds = []
    for slug, rec, dls in records:
        if max(d["dt"] for d in dls) >= now - KEEP_PAST:
            eds.append(rec)
            stats["kept"] += 1
        else:
            stats["past"] += 1  # kept as history for the estimate below

    for slug in dict.fromkeys(s for s, _, _ in records):
        series = sorted(((r, d) for s, r, d in records if s == slug), key=lambda x: x[0]["year"])
        if any(d["type"] == "paper" and d["dt"] > now for _, dls in series for d in dls):
            continue
        base, base_dls = series[-1]
        projected = [{**d, "dt": shift_year(d["dt"])} for d in base_dls]
        if not any(d["type"] == "paper" and d["dt"] > now for d in projected):
            continue  # biennial or discontinued: no estimate
        est = dict(base)
        est.update({
            "id": f"curated_{slug}{base['year'] + 1}-est",
            "year": base["year"] + 1,
            "status": "estimated",
            "estimated_from": base["year"],
            "deadlines": [{"type": d["type"], "iso": to_utc_iso(d["dt"]), "comment": d["comment"]} for d in projected],
            "date": "TBD", "event_start": None, "event_end": None, "place": "TBD", "city": "",
            # A national series stays in its country; an international one may move.
            "country": base["country"] if base["scope"] == "national" else "TBD",
            "mode": "tbd", "fees": None,
        })
        eds.append(est)
        stats["estimated"] += 1
    return eds, stats


def apply_fees(editions, fees: dict) -> int:
    """Attach fee records to editions in place; returns how many were attached."""
    from .build import norm_acronym

    n = 0
    for e in editions:
        rec = fees.get((norm_acronym(e["acronym"]), int(e["year"])))
        if rec and not e.get("fees"):
            e["fees"] = rec
            n += 1
    return n
