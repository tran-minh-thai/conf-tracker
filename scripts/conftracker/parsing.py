# SPDX-License-Identifier: MIT
"""Parsing helpers for places, event dates, time zones and deadlines.

Every function here is pure (no network, no clock) so it can be unit-tested.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

AOE = timezone(timedelta(hours=-12), "AoE")

# Named zones seen in ccfddl and WikiCFP. Zones with daylight saving time map
# to an IANA zone so the offset is resolved for the actual deadline date.
NAMED_ZONES = {
    "AOE": AOE,
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "Z": timezone.utc,
    "PT": ZoneInfo("America/Los_Angeles"),
    "PST": ZoneInfo("America/Los_Angeles"),
    "PDT": ZoneInfo("America/Los_Angeles"),
    "ET": ZoneInfo("America/New_York"),
    "EST": ZoneInfo("America/New_York"),
    "EDT": ZoneInfo("America/New_York"),
    "CET": ZoneInfo("Europe/Paris"),
    "CEST": ZoneInfo("Europe/Paris"),
    "BST": ZoneInfo("Europe/London"),
}

PLACEHOLDERS = {"", "tbd", "tba", "n/a", "na", "none", "-"}

COUNTRY_ALIASES = {
    "usa": "USA", "u.s.a.": "USA", "u.s.": "USA", "us": "USA",
    "united states": "USA", "united states of america": "USA",
    "uk": "UK", "u.k.": "UK", "united kingdom": "UK", "england": "UK",
    "scotland": "UK", "wales": "UK", "northern ireland": "UK",
    "prc": "China", "p.r. china": "China", "p.r.china": "China", "china": "China",
    "korea": "South Korea", "south korea": "South Korea", "republic of korea": "South Korea",
    "viet nam": "Vietnam", "vietnam": "Vietnam",
    "uae": "UAE", "united arab emirates": "UAE",
    "the netherlands": "Netherlands", "netherlands": "Netherlands",
    "czechia": "Czech Republic", "türkiye": "Turkey", "turkiye": "Turkey",
}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
US_STATE_NAMES = {"hawaii", "california", "texas", "new york", "washington", "florida"}
CITY_STATES = {"singapore", "hong kong", "macau", "macao", "monaco", "luxembourg"}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

ONLINE_WORDS = re.compile(r"\b(online|virtual|remote)\b", re.I)
HYBRID_WORDS = re.compile(r"\bhybrid\b", re.I)


def is_placeholder(value) -> bool:
    return value is None or str(value).strip().lower() in PLACEHOLDERS


def normalize_country(raw: str) -> str:
    c = raw.strip().strip(".").strip()
    if not c:
        return "TBD"
    if c.upper() in US_STATES or c.lower() in US_STATE_NAMES:
        return "USA"
    return COUNTRY_ALIASES.get(c.lower(), c)


def parse_place(place: str) -> dict:
    """Split a free-text venue into city, country and attendance mode.

    mode is one of "in-person", "online", "hybrid", "tbd". A hybrid venue keeps
    its physical city and country ("Bruges, Belgium and Online").
    """
    if is_placeholder(place):
        return {"city": "", "country": "TBD", "mode": "tbd"}

    text = re.sub(r"\s+", " ", str(place)).strip()
    hybrid = bool(HYBRID_WORDS.search(text))
    online = bool(ONLINE_WORDS.search(text))

    # Remove the attendance words to find the physical location, if any.
    physical = HYBRID_WORDS.sub("", text)
    physical = re.sub(r"\b(and|&|/|\+)\s*(online|virtual|remote)\b", "", physical, flags=re.I)
    physical = ONLINE_WORDS.sub("", physical)
    physical = re.sub(r"\b(conference|event|meeting)\b", "", physical, flags=re.I)
    physical = re.sub(r"[()\[\]]", " ", physical)
    physical = re.sub(r"\s*[-–/&+]\s*$", "", physical.strip())
    physical = re.sub(r"\s+", " ", physical).strip(" ,;-/&+")

    if not physical:
        if online or hybrid:
            return {"city": "", "country": "Online", "mode": "online"}
        return {"city": "", "country": "TBD", "mode": "tbd"}

    mode = "hybrid" if (hybrid or online) else "in-person"
    parts = [p.strip() for p in physical.split(",") if p.strip()]
    if len(parts) == 1:
        p0 = parts[0]
        if p0.lower() in CITY_STATES:
            return {"city": p0, "country": p0, "mode": mode}
        return {"city": "", "country": normalize_country(p0), "mode": mode}
    country = normalize_country(parts[-1])
    # "Venue, City, Country": the city sits just before the country, unless that
    # part is a state or province code ("San Diego, CA, USA", "Vancouver, BC, Canada").
    city = parts[-2]
    state_not_city = US_STATE_NAMES - {"washington", "new york"}
    if len(parts) >= 3 and (city.upper() in US_STATES or city.lower() in state_not_city
                            or re.fullmatch(r"[A-Z]{2,3}", city)):
        city = parts[-3]
    return {"city": normalize_city(city), "country": country, "mode": mode}


CITY_ALIASES = {
    "hcmc": "Ho Chi Minh City", "ho chi minh": "Ho Chi Minh City", "saigon": "Ho Chi Minh City",
    "tp. ho chi minh": "Ho Chi Minh City", "ha noi": "Hanoi", "danang": "Da Nang", "da nang city": "Da Nang",
    "hue city": "Hue", "can tho city": "Can Tho", "macau sar": "Macau", "hong kong sar": "Hong Kong",
}


def normalize_city(raw: str) -> str:
    c = re.sub(r"\s+", " ", raw).strip()
    return CITY_ALIASES.get(c.lower(), c)


def _iso(y: int, m: int, d: int):
    try:
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _month(name: str):
    return MONTHS.get(name.lower().rstrip("."))


def parse_event_dates(text):
    """Return (start, end) as YYYY-MM-DD strings, or (None, None)."""
    if is_placeholder(text):
        return None, None
    s = str(text).replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()

    # "Oct 12, 2026 - Oct 15, 2026"
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})\s*(?:-|to)\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})", s)
    if m and _month(m[1]) and _month(m[4]):
        return _iso(int(m[3]), _month(m[1]), int(m[2])), _iso(int(m[6]), _month(m[4]), int(m[5]))
    # "May 29 - June 2, 2027" (a December-January span crosses the year)
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})\s*(?:-|to)\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})", s)
    if m and _month(m[1]) and _month(m[3]):
        y = int(m[5])
        y1 = y - 1 if _month(m[1]) > _month(m[3]) else y
        return _iso(y1, _month(m[1]), int(m[2])), _iso(y, _month(m[3]), int(m[4]))
    # "August 14-18, 2027"
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})\s*-\s*(\d{1,2}),?\s*(\d{4})", s)
    if m and _month(m[1]):
        mo, y = _month(m[1]), int(m[4])
        return _iso(y, mo, int(m[2])), _iso(y, mo, int(m[3]))
    # "14-18 August 2027"
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\.?,?\s*(\d{4})", s)
    if m and _month(m[3]):
        mo, y = _month(m[3]), int(m[4])
        return _iso(y, mo, int(m[1])), _iso(y, mo, int(m[2]))
    # "28 June - 2 July 2027"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+),?\s*(\d{4})", s)
    if m and _month(m[2]) and _month(m[4]):
        y = int(m[5])
        y1 = y - 1 if _month(m[2]) > _month(m[4]) else y
        return _iso(y1, _month(m[2]), int(m[1])), _iso(y, _month(m[4]), int(m[3]))
    # "2027-08-14 - 2027-08-18"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:-|to)\s*(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m[1], m[2]
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m[1], m[1]
    # "August 14, 2027"
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})", s)
    if m and _month(m[1]):
        d = _iso(int(m[3]), _month(m[1]), int(m[2]))
        return d, d
    # "14 August 2027"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s*(\d{4})", s)
    if m and _month(m[2]):
        d = _iso(int(m[3]), _month(m[2]), int(m[1]))
        return d, d
    # "August 2027": month only, kept as the first day so date filters still work.
    m = re.search(r"([A-Za-z]+),?\s*(\d{4})", s)
    if m and _month(m[1]):
        d = _iso(int(m[2]), _month(m[1]), 1)
        return d, d
    return None, None


def parse_tz(tz_str) -> tuple[tzinfo, bool]:
    """Return (tzinfo, known). Unknown zones fall back to AoE with known=False."""
    if tz_str is None or not str(tz_str).strip():
        return AOE, True
    key = str(tz_str).strip().upper()
    if key in NAMED_ZONES:
        return NAMED_ZONES[key], True
    m = re.fullmatch(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", key)
    if m:
        sign = 1 if m[1] == "+" else -1
        delta = timedelta(hours=int(m[2]), minutes=int(m[3] or 0))
        if delta > timedelta(hours=14):
            return AOE, False
        return timezone(sign * delta), True
    return AOE, False


DEADLINE_FORMATS = (
    ("%Y-%m-%d %H:%M:%S", False), ("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True),
    ("%b %d, %Y", True), ("%B %d, %Y", True), ("%d %b %Y", True), ("%d %B %Y", True),
)


def parse_deadline(value, tz: tzinfo):
    """Parse a deadline string in zone tz into an aware datetime, or None.

    A date without a time means the end of that day (23:59:59) in tz.
    """
    if is_placeholder(value):
        return None
    clean = re.sub(r"\(.*?\)", "", str(value)).strip()
    clean = re.sub(r"\s+", " ", clean)
    for fmt, date_only in DEADLINE_FORMATS:
        try:
            dt = datetime.strptime(clean, fmt)
        except ValueError:
            continue
        if date_only:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.replace(tzinfo=tz)
    return None


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_year(dt: datetime, years: int = 1) -> datetime:
    """Same wall-clock date the given number of years later (Feb 29 -> Feb 28)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)
