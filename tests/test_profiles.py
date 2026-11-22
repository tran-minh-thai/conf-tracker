# SPDX-License-Identifier: MIT
import gzip
import json
from pathlib import Path

import pytest

from conftracker import profiles

CASES = json.loads((Path(__file__).parent / "fixtures" / "tokenize_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:30] or "empty" for c in CASES])
def test_tokenizer_matches_shared_fixture(case):
    assert profiles.tokens(case["text"]) == case["tokens"]


DUMP = """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
<inproceedings mdate="2025-01-01" key="conf/kdd/A25">
<author>X</author>
<title>Graph Neural Networks for Fraud Detection.</title>
<year>2025</year>
</inproceedings>
<inproceedings mdate="2025-01-01" key="conf/kdd/B23">
<title>Mining <i>Frequent</i> Patterns in M&uuml;nchen.</title>
<year>2023</year>
</inproceedings>
<inproceedings mdate="2025-01-01" key="conf/other/C24">
<title>Ignored venue.</title>
<year>2024</year>
</inproceedings>
<article mdate="2025-01-01" key="journals/kdd/D24">
<title>Journal article is ignored.</title>
<year>2024</year>
</article>
<inproceedings mdate="2025-01-01" key="conf/kdd/E10">
<title>Too old.</title>
<year>2010</year>
</inproceedings>
</dblp>
"""


def test_iter_dump_filters_keys_years_and_cleans_titles(tmp_path):
    p = tmp_path / "dblp.xml.gz"
    with gzip.open(p, "wt", encoding="iso-8859-1") as fh:
        fh.write(DUMP)
    got = list(profiles.iter_dump(p, {"kdd"}, range(2020, 2026)))
    assert got == [("kdd", 2025, "Graph Neural Networks for Fraud Detection."),
                   ("kdd", 2023, "Mining Frequent Patterns in München.")]


def synthetic():
    graph = [f"graph neural network for node classification {i}" for i in range(40)]
    pattern = [f"high utility sequential pattern mining {i}" for i in range(40)]
    crypto = [f"lattice based encryption and secure protocol {i}" for i in range(40)]
    return {"gnn": graph, "spm": pattern, "sec": crypto}


def test_profiles_are_normalised_and_rank_the_right_venue():
    prof, idf = profiles.build_profiles(synthetic())
    for p in prof.values():
        assert abs(sum(w * w for w in p["terms"].values()) - 1) < 1e-3
    assert profiles.rank("Mining sequential patterns with utility", prof, idf)[0][1] == "spm"
    assert profiles.rank("A secure encryption protocol", prof, idf)[0][1] == "sec"
    assert profiles.rank("Message passing in graph neural networks", prof, idf)[0][1] == "gnn"
    # No known term: every score is zero, so no venue is preferred.
    assert all(s == 0 for s, _ in profiles.rank("zzz qqq", prof, idf))


def test_venues_with_too_few_titles_get_no_profile():
    data = synthetic()
    data["tiny"] = ["one title only"]
    prof, _ = profiles.build_profiles(data)
    assert "tiny" not in prof and len(prof) == 3


def test_evaluate_reports_denominators_and_beats_name_baseline():
    train = synthetic()
    test = {k: [t.replace(" 1", " x") for t in v[:12]] for k, v in train.items()}
    names = {"gnn": "Neural Conference", "spm": "Pattern Conference", "sec": "Security Conference"}
    r = profiles.evaluate(train, test, names, per_venue=5)
    assert r["venues_queried"] == 3 and r["queries"] == 15
    assert r["title_profiles"]["recall@1"] == 1.0
    assert r["title_profiles"]["mrr"] >= r["name_only_baseline"]["mrr"]


def test_published_profiles_use_the_current_stopwords_and_tokenizer():
    path = Path(__file__).resolve().parent.parent / "data" / "venue_profiles.json"
    if not path.exists():
        pytest.skip("data/venue_profiles.json not built yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stopwords"] == profiles.STOPWORDS
    assert data["tokenizer_version"] == profiles.TOKENIZER_VERSION
    assert data["profiles"], "no profiles"


def test_withheld_terms_never_reach_profiles():
    import hashlib
    digests = frozenset({hashlib.sha256(b"walrus").hexdigest()})
    assert profiles.withheld("walrus", digests) and profiles.withheld("big_walrus", digests)
    assert not profiles.withheld("graph_mining", digests)
    # The published profiles contain no withheld term.
    path = Path(__file__).resolve().parent.parent / "data" / "venue_profiles.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert not [t for t in data["idf"] if profiles.withheld(t)]
