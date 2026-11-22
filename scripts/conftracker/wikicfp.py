# SPDX-License-Identifier: MIT
"""Supplementary calls for papers scraped from WikiCFP listing pages.

WikiCFP has no curation, so these venues carry no rank unless they match a
ccfddl series, and their research area is re-derived from the full name.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .parsing import AOE, parse_deadline, parse_event_dates, parse_place, to_utc_iso
from .topics import AREAS, classify, venue_kind

BASE_URL = "http://www.wikicfp.com"
CATEGORIES = [
    "data mining", "artificial intelligence", "machine learning", "security",
    "software engineering", "computer networks", "computer science",
]
HEADERS = {"User-Agent": "conf-tracker/2.0 (+https://github.com/tran-minh-thai/conf-tracker)"}


def parse_listing(html: str):
    """Yield raw rows (event, url, full_name, date, place, deadline) from one page."""
    soup = BeautifulSoup(html, "html.parser")
    contsec = soup.find("div", class_="contsec")
    if not contsec:
        return
    table = None
    for tb in contsec.find_all("table"):
        if tb.find("td", string=re.compile(r"Event", re.I)):
            table = tb
            break
    if table is None:
        return
    rows = table.find_all("tr")
    i = 1
    while i + 1 < len(rows):
        r1, r2 = rows[i].find_all("td"), rows[i + 1].find_all("td")
        i += 2
        if len(r1) < 2 or len(r2) < 3:
            continue
        link = r1[0].find("a")
        if not link:
            continue
        href = link.get("href", "")
        yield {
            "event": link.get_text(strip=True),
            "url": f"{BASE_URL}{href}" if href.startswith("/") else href,
            "full_name": r1[1].get_text(strip=True),
            "date": r2[0].get_text(strip=True),
            "place": r2[1].get_text(strip=True),
            "deadline": r2[2].get_text(strip=True),
        }


def row_to_edition(row: dict, category: str, now: datetime):
    """Convert one listing row into an edition, or None if closed/unparseable."""
    dl = parse_deadline(row["deadline"], AOE)
    if dl is None or dl <= now:
        return None
    m = re.match(r"^(.*?)\s*(\d{4})$", row["event"])
    acronym, year = (m[1].strip(), int(m[2])) if m else (row["event"].strip(), dl.year)
    place = parse_place(row["place"])
    start, end = parse_event_dates(row["date"])
    sub = classify(row["full_name"])
    return {
        "id": "",  # assigned by the merge step from the dedup key
        "acronym": acronym,
        "full_name": row["full_name"],
        "year": year,
        "kind": venue_kind(row["full_name"], acronym),
        "sub": sub,
        "topic": AREAS[sub],
        "rank": {"ccf": None, "core": None, "thcpl": None},
        "dblp": None,
        "url": row["url"],
        "timezone": "AoE",
        "tz_known": False,  # WikiCFP lists a date only; the zone is not stated
        "deadlines": [{"type": "paper", "iso": to_utc_iso(dl), "comment": ""}],
        "date": row["date"] or "TBD",
        "event_start": start,
        "event_end": end,
        "place": row["place"] or "TBD",
        "city": place["city"],
        "country": place["country"],
        "mode": place["mode"],
        "status": "confirmed",
        "estimated_from": None,
        "accept_rates": [],
        "source": "wikicfp",
        "wikicfp_category": category,
    }


def fetch(now: datetime, max_pages: int = 2, session=None, pause: float = 1.0):
    """Return (editions, stats). Network errors are counted, not hidden."""
    http = session or requests.Session()
    out, stats = [], {"pages": 0, "rows": 0, "errors": []}
    for cat in CATEGORIES:
        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}/cfp/call?conference={quote(cat)}&page={page}"
            try:
                resp = http.get(url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                stats["errors"].append(f"{cat} p{page}: {exc}")
                break
            stats["pages"] += 1
            rows = list(parse_listing(resp.text))
            stats["rows"] += len(rows)
            if not rows:
                break
            for row in rows:
                ed = row_to_edition(row, cat, now)
                if ed is not None:
                    out.append(ed)
            time.sleep(pause)
    return out, stats
