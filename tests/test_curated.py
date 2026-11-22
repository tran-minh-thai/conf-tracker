# SPDX-License-Identifier: MIT
from datetime import datetime, timezone

import pytest
import yaml

from conftracker import build, curated

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

VENUE = {
    "acronym": "KSEX", "full_name": "Knowledge and Systems Engineering Example", "year": 2026,
    "scope": "international", "sub": "AI", "url": "https://ksex.example/cfp", "timezone": "unstated",
    "deadlines": [{"type": "paper", "date": "2026-12-15"}, {"type": "notification", "date": "2027-02-01"}],
    "date": "Mar 12-14, 2027", "place": "Can Tho, Vietnam", "checked": "2026-11-22",
    "fees": [{"label": "Regular", "amount": 350, "currency": "usd"}], "fees_url": "https://ksex.example/reg",
    "keywords": ["Knowledge Graph", "reasoning"],
}


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_curated_venue_is_loaded(tmp_path):
    eds, stats = curated.load_venues(write(tmp_path, "venues.yml", [VENUE]), NOW)
    assert stats == {"entries": 1, "kept": 1, "past": 0}
    e = eds[0]
    assert e["id"] == "curated_ksex2026" and e["source"] == "curated"
    assert e["tz_known"] is False and e["timezone"] == "AoE"  # unstated zone: AoE, flagged
    assert e["deadlines"][0] == {"type": "paper", "iso": "2026-12-16T11:59:59Z", "comment": ""}
    assert (e["city"], e["country"]) == ("Can Tho", "Vietnam")
    assert e["fees"]["items"] == [{"label": "Regular", "amount": 350.0, "currency": "USD"}]
    assert e["keywords"] == ["knowledge graph", "reasoning"]


def test_missing_file_is_empty(tmp_path):
    assert curated.load_venues(tmp_path / "none.yml", NOW) == ([], {"entries": 0, "kept": 0, "past": 0})
    assert curated.load_fees(tmp_path / "none.yml") == {}


def test_old_entries_are_dropped_and_counted(tmp_path):
    old = {**VENUE, "deadlines": [{"type": "paper", "date": "2025-01-10"}]}
    eds, stats = curated.load_venues(write(tmp_path, "venues.yml", [old]), NOW)
    assert eds == [] and stats["past"] == 1


BAD_VENUES = [
    ("no url", {"url": None}),
    ("bad url", {"url": "ftp://x"}),
    ("bad area", {"sub": "ZZ"}),
    ("bad scope", {"scope": "regional"}),
    ("bad deadline type", {"deadlines": [{"type": "camera", "date": "2026-12-01"}]}),
    ("unreadable date", {"deadlines": [{"type": "paper", "date": "mid December"}]}),
    ("no paper deadline", {"deadlines": [{"type": "abstract", "date": "2026-12-01"}]}),
    ("no checked date", {"checked": None}),
    ("negative fee", {"fees": [{"label": "x", "amount": -1, "currency": "USD"}]}),
    ("bad currency", {"fees": [{"label": "x", "amount": 1, "currency": "dollars"}]}),
    ("fees without source", {"fees_url": None}),
]


@pytest.mark.parametrize("name, patch", BAD_VENUES, ids=[b[0] for b in BAD_VENUES])
def test_bad_curated_venue_is_rejected(tmp_path, name, patch):
    with pytest.raises(curated.CuratedError):
        curated.load_venues(write(tmp_path, "venues.yml", [{**VENUE, **patch}]), NOW)


def test_fees_file_and_duplicates(tmp_path):
    rec = {"acronym": "IEEE KDDX", "year": 2027, "fees": [{"label": "Student", "amount": 200, "currency": "EUR"}],
           "fees_url": "https://x.example/reg", "checked": "2026-11-20"}
    table = curated.load_fees(write(tmp_path, "fees.yml", [rec]))
    assert ("kddx", 2027) in table
    with pytest.raises(curated.CuratedError):
        curated.load_fees(write(tmp_path, "fees2.yml", [rec, rec]))
    eds = [{"acronym": "KDDX", "year": 2027}, {"acronym": "OTHER", "year": 2027}]
    assert curated.apply_fees(eds, table) == 1 and eds[0]["fees"]["items"][0]["currency"] == "EUR"


def base_edition(acronym, year, status):
    return {"id": f"{acronym.lower()}{year}", "acronym": acronym, "year": year, "status": status,
            "rank": {"ccf": "B", "core": None, "thcpl": None}, "dblp": "x", "accept_rates": [{"year": 2025}],
            "deadlines": [{"type": "paper", "iso": "2027-01-01T00:00:00Z", "comment": ""}]}


def test_merge_curated_replaces_estimate_and_keeps_confirmed(tmp_path):
    cur, _ = curated.load_venues(write(tmp_path, "venues.yml", [VENUE]), NOW)
    est = base_edition("KSEX", 2026, "estimated")
    out, stats = build.merge_curated([est], cur)
    assert stats["curated_replaced_estimate"] == 1 and len(out) == 1
    assert out[0]["source"] == "curated" and out[0]["rank"]["ccf"] == "B"  # rank inherited
    conf = base_edition("KSEX", 2026, "confirmed")
    out, stats = build.merge_curated([conf], cur)
    assert stats["curated_skipped_confirmed"] == 1 and out == [conf]
    assert conf["fees"]["items"][0]["amount"] == 350.0  # fees carried over
