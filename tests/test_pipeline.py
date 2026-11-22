# SPDX-License-Identifier: MIT
"""End-to-end checks of ccfddl parsing, merging, validation and the ICS feed,
on a small synthetic archive whose expected output is worked out by hand."""
import copy
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
import yaml

from conftracker import build, ccfddl, ics, topics, wikicfp

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

SERIES = [
    {   # open now, with abstract + paper + notification
        "title": "KDDX", "description": "Knowledge Discovery Example", "sub": "DB",
        "rank": {"ccf": "A", "core": "A*", "thcpl": "A"}, "dblp": "kddx",
        "confs": [{
            "year": 2027, "id": "kddx27", "link": "https://kddx.example/2027",
            "timezone": "AoE", "date": "August 14-18, 2027", "place": "Toronto, Canada (Hybrid)",
            "timeline": [{"abstract_deadline": "2027-02-01 23:59:59", "deadline": "2027-02-08 23:59:59",
                          "decision_deadline": "2027-05-01", "comment": "research track"}],
        }],
    },
    {   # closed in July 2026, next edition not announced -> estimate for 2027 deadlines
        "title": "ESTC", "description": "Estimated Conference", "sub": "AI",
        "rank": {"ccf": "B", "core": "N"}, "dblp": "estc",
        "confs": [
            {"year": 2026, "id": "estc26", "link": "https://estc.example", "timezone": "UTC",
             "date": "Oct 1-3, 2026", "place": "Lyon, France",
             "timeline": [{"deadline": "2026-03-10 23:59:59"}]},
            {"year": 2027, "id": "estc27", "link": "https://estc.example/27", "timezone": "UTC",
             "date": "TBD", "place": "Kyoto, Japan", "timeline": [{"deadline": "TBD"}]},
        ],
    },
    {   # last edition long ago -> projection lands in the past -> no estimate, nothing kept
        "title": "OLDC", "description": "Discontinued Conference", "sub": "SE",
        "rank": {"ccf": "C"}, "dblp": "oldc",
        "confs": [{"year": 2019, "id": "oldc19", "link": "", "timezone": "AoE", "date": "TBD",
                   "place": "TBD", "timeline": [{"deadline": "2019-01-01"}]}],
    },
    {   # paper closed 10 days ago: kept as confirmed (recently closed), estimate for next year too
        "title": "RCLS", "description": "Recently Closed Symposium", "sub": "SC",
        "rank": {"ccf": "N", "core": "B"}, "dblp": "rcls",
        "confs": [{"year": 2027, "id": "rcls27", "link": "https://rcls.example", "timezone": "Mars/Olympus",
                   "date": "May 2027", "place": "Online",
                   "timeline": [{"deadline": "2026-11-12 23:59:59"}]}],
    },
]
RATES = [{"title": "KDDX", "accept_rates": [
    {"year": 2025, "rate": 0.2, "accepted": 200, "submitted": 1000},
    {"year": 2026, "rate": 0.15, "accepted": 150, "submitted": 1000},
]}]


def make_zip(series=SERIES, rates=RATES) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ccf-deadlines-main/conference/DB/x.yml", yaml.safe_dump(series))
        zf.writestr("ccf-deadlines-main/accept_rates/DB/x.yml", yaml.safe_dump(rates))
        zf.writestr("ccf-deadlines-main/README.md", "ignored")
    return buf.getvalue()


def editions():
    confs, rates = ccfddl.read_zip(make_zip())
    return ccfddl.build_editions(confs, rates, NOW)


def by_id(eds):
    return {e["id"]: e for e in eds}


def test_editions_selected_as_expected():
    eds, stats = editions()
    assert sorted(by_id(eds)) == ["estc27-est", "kddx27", "rcls27", "rcls28-est"]
    assert stats["confirmed"] == 2 and stats["estimated"] == 2 and stats["series"] == 4
    assert stats["unknown_tz"] == ["Mars/Olympus"]


def test_confirmed_edition_fields():
    e = by_id(editions()[0])["kddx27"]
    assert [d["type"] for d in e["deadlines"]] == ["abstract", "paper", "notification"]
    assert e["deadlines"][1]["iso"] == "2027-02-09T11:59:59Z"
    assert e["deadlines"][1]["comment"] == "research track"
    assert e["rank"] == {"ccf": "A", "core": "A*", "thcpl": "A"}
    assert (e["city"], e["country"], e["mode"]) == ("Toronto", "Canada", "hybrid")
    assert (e["event_start"], e["event_end"]) == ("2027-08-14", "2027-08-18")
    assert [r["year"] for r in e["accept_rates"]] == [2025, 2026]
    assert e["status"] == "confirmed" and e["tz_known"] is True


def test_estimate_uses_announced_edition_and_shifts_one_year():
    e = by_id(editions()[0])["estc27-est"]
    assert e["status"] == "estimated" and e["estimated_from"] == 2026
    assert e["deadlines"] == [{"type": "paper", "iso": "2027-03-10T23:59:59Z", "comment": ""}]
    assert e["year"] == 2027 and e["country"] == "Japan"  # venue from the announced 2027 entry
    assert e["rank"]["core"] is None  # "N" means not ranked


def test_unknown_timezone_is_flagged_on_edition():
    e = by_id(editions()[0])["rcls27"]
    assert e["tz_known"] is False and e["mode"] == "online"


def test_merge_wikicfp_dedup_inherit_and_replace():
    eds, _ = editions()
    w_dup = {**wiki_row("KDDX 2027", "Knowledge Discovery Example"), }
    w_est = wiki_row("IEEE ESTC 2027", "International Conference on Estimated Conference")
    w_other = wiki_row("ESTC 2027", "Earth Science and Technology Congress")
    w_new = wiki_row("NEWC 2027", "International Conference on Machine Learning Things")
    rows = [w_dup, w_est, w_other, w_new, copy.deepcopy(w_new)]
    merged, stats = build.merge(eds, [r for r in rows if r is not None])
    ids = by_id(merged)
    assert stats == {"wikicfp_dup": 2, "wikicfp_inherited": 1, "wikicfp_replaced_estimate": 1, "wikicfp_added": 3}
    assert "estc27-est" not in ids  # the published call replaced the estimate
    inherited = ids["wikicfp_estc2027"]
    assert inherited["rank"]["ccf"] == "B" and inherited["sub"] == "AI"
    # Same acronym but a different venue must not inherit a rank.
    others = [e for e in merged if e["full_name"].startswith("Earth Science")]
    assert len(others) == 1 and others[0]["rank"]["ccf"] is None


def wiki_row(event, name, deadline="Jan 20, 2027"):
    row = {"event": event, "url": "http://www.wikicfp.com/x", "full_name": name,
           "date": "Jun 1, 2027 - Jun 3, 2027", "place": "Hanoi, Vietnam", "deadline": deadline}
    return wikicfp.row_to_edition(row, "machine learning", NOW)


def test_wikicfp_closed_or_unparseable_rows_are_dropped():
    assert wiki_row("A 2026", "x", deadline="Nov 1, 2026") is None
    assert wiki_row("A 2026", "x", deadline="Where") is None


def test_wikicfp_area_comes_from_the_name_not_the_search_category():
    e = wiki_row("MECN 2026", "7th International Conference on Mechanical Engineering")
    assert e["sub"] == "OT" and e["wikicfp_category"] == "machine learning"
    j = wiki_row("SIPIJ 2027", "Signal & Image Processing : An International Journal")
    assert j["kind"] == "journal"


def payload():
    eds, _ = editions()
    return build.build_payload(eds, NOW, {})


def test_valid_payload_has_no_problems():
    assert build.validate(payload()) == []


FAULTS = [
    ("missing field", lambda c: c.pop("url")),
    ("bad area", lambda c: c.update(sub="ZZ")),
    ("bad status", lambda c: c.update(status="maybe")),
    ("bad mode", lambda c: c.update(mode="space")),
    ("unsorted deadlines", lambda c: c["deadlines"].reverse()),
    ("bad iso", lambda c: c["deadlines"][0].update(iso="2027-02-01")),
    ("end before start", lambda c: c.update(event_start="2027-09-01")),
    ("no deadlines", lambda c: c.update(deadlines=[])),
    ("html in url", lambda c: c.update(url="javascript:<script>")),
]


@pytest.mark.parametrize("name, fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_validator_catches_each_injected_fault(name, fault):
    p = payload()
    target = next(c for c in p["conferences"] if c["id"] == "kddx27")
    fault(target)
    problems = build.validate(p)
    assert problems, f"validator missed: {name}"
    assert all("kddx27" in pr for pr in problems)


def test_validator_catches_duplicate_ids_and_empty():
    p = payload()
    p["conferences"].append(copy.deepcopy(p["conferences"][0]))
    assert any("duplicate id" in x for x in build.validate(p))
    assert build.validate({**payload(), "conferences": []})


def test_shrink_guard(tmp_path):
    prev = tmp_path / "conferences.json"
    prev.write_text(json.dumps({"total": 100}))
    build.check_shrink(prev, 60)
    with pytest.raises(build.ShrinkGuard):
        build.check_shrink(prev, 40)
    build.check_shrink(tmp_path / "missing.json", 1)


def test_feed_contains_only_ranked_confirmed_future_deadlines(tmp_path):
    p = payload()
    out = build.write_outputs(p, tmp_path, NOW)
    text = (tmp_path / "deadlines.ics").read_bytes().decode("utf-8")
    # kddx27: 3 future deadlines; rcls27 closed; estimates excluded.
    assert out["feed_events"] == 3
    assert text.count("BEGIN:VEVENT") == 3
    assert "KDDX 2027: Paper deadline" in text and "ESTC" not in text
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert "BEGIN:VALARM" in text and "TRIGGER:-P7D" in text


def test_ics_escape_and_fold():
    assert ics.escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long = "DESCRIPTION:" + "é" * 80
    folded = ics.fold(long)
    assert all(len(x.encode()) <= 75 for x in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == long
    # Single-byte text reaches the limit exactly, so an off-by-one shows up here.
    ascii_long = "DESCRIPTION:" + "x" * 300
    folded = ics.fold(ascii_long)
    assert max(len(x.encode()) for x in folded.split("\r\n")) == 75
    assert folded.replace("\r\n ", "") == ascii_long


def test_classifier_examples():
    assert topics.classify("International Conference on Data Mining and Applications") == "DB"
    assert topics.classify("Conference on Attacks and Defenses for Internet-of-Things") == "SC"
    assert topics.classify("13th International Conference on Artificial Intelligence") == "AI"
    assert topics.classify("Managing Value and Supply Chains") == "OT"
    assert topics.classify("Something Unrelated") == "MX"
