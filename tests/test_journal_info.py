# SPDX-License-Identifier: MIT
import pytest

from conftracker import journal_info as ji

CSV = (
    "﻿Journal title,Journal ISSN (print version),Journal EISSN (online version),APC,APC amount\n"
    "Open With Fee,,2169-3536,Yes,2160 USD\n"
    "Diamond Journal,1234-5679,,No,\n"
    "Two Currencies,1111-2222,3333-444x,Yes,1000000 IDR; 100 USD\n"
)


def test_doaj_csv_reads_both_issns_and_charges():
    d = ji.read_doaj(CSV)
    assert d["2169-3536"]["apc_amounts"] == [{"amount": 2160, "currency": "USD"}]
    assert d["1234-5679"]["apc"] is False and d["1234-5679"]["apc_amounts"] == []
    assert d["3333-444X"] is d["1111-2222"]  # online ISSN normalised to upper-case X
    assert d["1111-2222"]["apc_amounts"][1] == {"amount": 100, "currency": "USD"}
    with pytest.raises(ValueError):
        ji.read_doaj("Title,ISSN\nx,1\n")


@pytest.mark.parametrize("in_doaj, is_oa, works, hybrid, want", [
    (True, False, 0, 0, "open"),            # DOAJ alone is enough
    (False, True, 5, 0, "open"),            # OpenAlex alone is enough
    (False, False, 1488, 120, "hybrid"),    # Information Sciences, 2024 counts
    (False, False, 20, 5, "hybrid"),        # both thresholds exactly met
    (False, False, 20, 4, "subscription"),  # one hybrid article short
    (False, False, 19, 19, "unknown"),      # too few articles to tell
    (False, None, None, None, "unknown"),   # not in OpenAlex
])
def test_classification_boundaries(in_doaj, is_oa, works, hybrid, want):
    assert ji.classify(in_doaj, is_oa, works, hybrid) == want


def test_record_prefers_journal_statement_and_marks_diamond():
    d = ji.read_doaj(CSV)
    src = {"id": "https://openalex.org/S123", "is_oa": True, "apc_usd": 2075,
           "summary_stats": {"2yr_mean_citedness": 4.3456, "h_index": 250}}
    r = ji.journal_record(["2169-3536"], d, src, 30000, 0)
    assert (r["access"], r["apc_source"], r["apc"][0]["amount"], r["openalex"]) == ("open", "doaj", 2160, "S123")
    assert (r["citedness_2y"], r["h_index"]) == (4.35, 250)
    dia = ji.journal_record(["1234-5679"], d, None, None, None)
    assert dia["access"] == "open" and dia["diamond"] and dia["apc"] == []
    sub = ji.journal_record(["0020-0255"], d, {"id": "S9", "is_oa": False, "apc_usd": 3200, "summary_stats": {}}, 1488, 120)
    assert (sub["access"], sub["apc_source"], sub["citedness_2y"]) == ("hybrid", "openalex", None)


def test_record_lists_every_issn_and_the_country():
    # The finder knows only the print ISSN; OpenAlex adds the online one and the publisher's country.
    src = {"id": "S900972176", "is_oa": False, "summary_stats": {}, "issn": ["0952-1976", "1873-6769"], "country_code": "GB"}
    r = ji.journal_record(["0952-1976"], {}, src, 3168, 336)
    assert (r["issn"], r["country"]) == (["0952-1976", "1873-6769"], "GB")
    # Not found in OpenAlex: the finder's own ISSNs, no country (unknown, not "domestic").
    r = ji.journal_record(["0952-1976", "bad"], {}, None, None, None)
    assert (r["issn"], r["country"]) == (["0952-1976"], None)


def write_yaml(tmp_path, text):
    p = tmp_path / "journal_access.yml"
    p.write_text(text, encoding="utf-8")
    return p


GOOD = """- journal: pvldb
  access: open
  diamond: true
  url: https://vldb.org/pvldb/general-information/open-access-statement
  checked: 2026-11-23
"""


def test_override_replaces_access_and_keeps_figures(tmp_path):
    o = ji.load_overrides(write_yaml(tmp_path, GOOD), {"pvldb"})
    rec = ji.journal_record(["2150-8097"], {}, {"id": "S1", "is_oa": False, "apc_usd": None,
                                                "summary_stats": {"2yr_mean_citedness": 9.67, "h_index": 227}}, 442, 0)
    assert rec["access"] == "subscription"
    r = ji.apply_override(rec, o["pvldb"])
    assert (r["access"], r["diamond"], r["citedness_2y"], r["override"]["checked"]) == ("open", True, 9.67, "2026-11-23")


@pytest.mark.parametrize("patch, why", [
    (("pvldb", "nosuch"), "unknown journal"),
    (("access: open", "access: free"), "access must"),
    (("diamond: true", "diamond: yes please"), "diamond"),
    (("https://vldb", "http://vldb"), "https url"),
    (("checked: 2026-11-23", "checked: soon"), "checked date"),
    (("access: open", "access: hybrid"), "only an open journal"),
])
def test_bad_overrides_are_rejected(tmp_path, patch, why):
    with pytest.raises(ValueError, match=why):
        ji.load_overrides(write_yaml(tmp_path, GOOD.replace(*patch)), {"pvldb"})
    with pytest.raises(ValueError, match="duplicate"):
        ji.load_overrides(write_yaml(tmp_path, GOOD + GOOD), {"pvldb"})


def test_repository_overrides_are_valid():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    keys = set(json.loads((root / "data" / "journal_profiles.json").read_text(encoding="utf-8"))["profiles"])
    assert len(ji.load_overrides(root / "data" / "curated" / "journal_access.yml", keys)) >= 4
