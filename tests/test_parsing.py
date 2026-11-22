# SPDX-License-Identifier: MIT
from datetime import datetime, timedelta, timezone

import pytest

from conftracker.parsing import (
    AOE, parse_deadline, parse_event_dates, parse_place, parse_tz, shift_year, to_utc_iso,
)


@pytest.mark.parametrize("raw, city, country, mode", [
    ("San Diego, CA, USA", "San Diego", "USA", "in-person"),
    ("Vancouver, BC, Canada", "Vancouver", "Canada", "in-person"),
    ("Singapore", "Singapore", "Singapore", "in-person"),
    ("Online", "", "Online", "online"),
    ("Virtual Conference", "", "Online", "online"),
    ("TBD", "", "TBD", "tbd"),
    ("", "", "TBD", "tbd"),
    (None, "", "TBD", "tbd"),
    # Hybrid venues keep the physical location (the old parser returned "Online").
    ("Bruges, Belgium and Online", "Bruges", "Belgium", "hybrid"),
    ("Toronto, Canada (Hybrid)", "Toronto", "Canada", "hybrid"),
    ("Laguna Hills, CA, USA - Hybrid", "Laguna Hills", "USA", "hybrid"),
    ("Guiyang, China / Online", "Guiyang", "China", "hybrid"),
    ("Waikoloa, Hawaii, USA (Hybrid)", "Waikoloa", "USA", "hybrid"),
    ("Hanoi, Viet Nam", "Hanoi", "Vietnam", "in-person"),
    ("Honolulu, Hawaii", "Honolulu", "USA", "in-person"),
    # Institution first: the city is the part before the country.
    ("VinUniversity, Hanoi, Vietnam", "Hanoi", "Vietnam", "in-person"),
    ("Washington DC Convention Center, Washington, USA", "Washington", "USA", "in-person"),
    ("Danang, Vietnam / Online", "Da Nang", "Vietnam", "hybrid"),
    ("Saigon, Vietnam", "Ho Chi Minh City", "Vietnam", "in-person"),
])
def test_parse_place(raw, city, country, mode):
    assert parse_place(raw) == {"city": city, "country": country, "mode": mode}


@pytest.mark.parametrize("raw, start, end", [
    ("Oct 12, 2026 - Oct 15, 2026", "2026-10-12", "2026-10-15"),
    ("May 29 - June 2, 2027", "2027-05-29", "2027-06-02"),
    ("Dec 30 - Jan 2, 2027", "2026-12-30", "2027-01-02"),
    ("August 14-18, 2027", "2027-08-14", "2027-08-18"),
    ("14-18 August 2027", "2027-08-14", "2027-08-18"),
    ("28 June - 2 July 2027", "2027-06-28", "2027-07-02"),
    ("2027-08-14 to 2027-08-18", "2027-08-14", "2027-08-18"),
    ("August 14, 2027", "2027-08-14", "2027-08-14"),
    ("August 2027", "2027-08-01", "2027-08-01"),
    ("April 21 – 23, 2027", "2027-04-21", "2027-04-23"),
    ("TBD", None, None),
    ("Feb 30, 2027", None, None),
])
def test_parse_event_dates(raw, start, end):
    assert parse_event_dates(raw) == (start, end)


def test_parse_tz_offsets_and_names():
    assert parse_tz("AoE") == (AOE, True)
    assert parse_tz(None) == (AOE, True)
    assert parse_tz("UTC+8")[0].utcoffset(None) == timedelta(hours=8)
    assert parse_tz("UTC-5:30")[0].utcoffset(None) == timedelta(hours=-5, minutes=-30)
    # The old parser mapped plain "UTC" to AoE: a 12-hour error.
    assert parse_tz("UTC")[0].utcoffset(None) == timedelta(0)
    assert parse_tz("UTC+0")[0].utcoffset(None) == timedelta(0)


def test_unknown_zone_is_flagged():
    tz, known = parse_tz("Mars/Olympus")
    assert tz is AOE and known is False
    assert parse_tz("UTC+20")[1] is False


def test_pacific_time_follows_daylight_saving():
    tz, known = parse_tz("PT")
    assert known
    winter = parse_deadline("2026-12-01 17:00:00", tz)
    summer = parse_deadline("2026-07-01 17:00:00", tz)
    assert to_utc_iso(winter) == "2026-12-02T01:00:00Z"  # PST, UTC-8
    assert to_utc_iso(summer) == "2026-07-02T00:00:00Z"  # PDT, UTC-7


def test_deadline_formats():
    assert to_utc_iso(parse_deadline("2027-01-15", AOE)) == "2027-01-16T11:59:59Z"
    assert to_utc_iso(parse_deadline("2027-01-15 23:59", AOE)) == "2027-01-16T11:59:00Z"
    assert to_utc_iso(parse_deadline("Jan 15, 2027", AOE)) == "2027-01-16T11:59:59Z"
    assert to_utc_iso(parse_deadline("Jan 15, 2027 (Jan 1, 2027)", AOE)) == "2027-01-16T11:59:59Z"
    assert to_utc_iso(parse_deadline("15 January 2027", timezone.utc)) == "2027-01-15T23:59:59Z"
    for bad in ("TBD", "", None, "soon", "2027-13-01"):
        assert parse_deadline(bad, AOE) is None


def test_shift_year_handles_leap_day():
    assert shift_year(datetime(2028, 2, 29, tzinfo=AOE)).date().isoformat() == "2029-02-28"
    assert shift_year(datetime(2027, 3, 1, tzinfo=AOE)).date().isoformat() == "2028-03-01"
