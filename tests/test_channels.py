# SPDX-License-Identifier: MIT
"""Ranking channels (scripts/conftracker/channels.py, channel_counts.py) and the shared fixture.

tests/fixtures/channel_cases.json freezes a slice of data/venue_channels.json (twelve venues, the
query terms' weights) with the expected fused scores and shared terms, so the Python, browser and
iOS implementations are checked against the same numbers. Regenerate with:
    python tests/test_channels.py --write
"""
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftracker import channel_counts as cc  # noqa: E402
from conftracker import channels, profiles  # noqa: E402
import update_channel_counts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "channel_cases.json"
VENUES = ["icalp", "isit", "soda", "stoc", "colt", "dexa", "edbt", "icdm", "pakdd", "dasfaa", "kdd", "sigmod"]
CASES = [
    {"name": "high-utility sequential pattern mining",
     "text": "Mining high-utility sequential patterns from large transaction databases. We propose a pattern-growth "
             "algorithm with tighter utility upper bounds for pruning, evaluated on real-world datasets.\n"
             "A tighter utility upper bound\nAn efficient pattern-growth mining algorithm"},
    {"name": "graph neural networks", "text": "Graph neural networks for fraud detection in large transaction graphs."},
    {"name": "learning theory", "text": "Regret lower bounds for online learning with expert advice"},
]


def build_fixture():
    src = ROOT / "data" / "venue_channels.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    words = set()
    for c in CASES:
        words.update(profiles.tokens(c["text"]))
    mini = {"schema_version": data["schema_version"], "years": data["years"], "stopwords": data["stopwords"],
            "fusion": data["fusion"], "channels": {}}
    for name, ch in data["channels"].items():
        mini["channels"][name] = {"method": ch["method"], "phrase": ch["phrase"],
                                  "query_weight": {t: w for t, w in ch["query_weight"].items() if t in words},
                                  "venues": {k: {t: w for t, w in ch["venues"][k].items() if t in words}
                                             for k in VENUES if k in ch["venues"]}}
    out = {"note": "Shared by tests/test_channels.py, tests/core.test.js and the iOS ConfCore tests.",
           "source": {"file": "data/venue_channels.json", "generated_at": data["generated_at"],
                      "sha256": hashlib.sha256(src.read_bytes()).hexdigest()},
           "set": mini, "cases": []}
    for c in CASES:
        sc = channels.fused_scores(c["text"], mini)
        ranking = sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))
        out["cases"].append({**c, "ranking": [[k, v] for k, v in ranking],
                             "shared": {k: channels.shared_terms(c["text"], mini, k, 4) for k, _ in ranking[:4]}})
    pub = json.loads((ROOT / "data" / "venue_profiles.json").read_text(encoding="utf-8"))
    spec = profiles.term_specificity(p["terms"] for p in pub["profiles"].values())
    q = profiles.paper_vector([CASES[0]["text"]], pub["idf"], spec)
    old = sorted(((profiles.score(q, p["terms"]), k) for k, p in pub["profiles"].items()), key=lambda x: (-x[0], x[1]))
    new = sorted(channels.fused_scores(CASES[0]["text"], data).items(), key=lambda kv: (-kv[1], kv[0]))
    watch = ("isit", "icdm", "pakdd", "dasfaa", "kdd", "dexa", "edbt")
    out["full_set_case"] = {"title_profiles": {k: [x for _, x in old].index(k) + 1 for k in watch},
                            "channels": {k: [x for x, _ in new].index(k) + 1 for k in watch}}
    return out


FIX = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else None


def _fresh(data):
    """A copy without cached indexes, so every test scores from the JSON values."""
    return json.loads(json.dumps(data))


@pytest.mark.parametrize("case", FIX["cases"] if FIX else [], ids=lambda c: c["name"])
def test_fused_scores_match_fixture(case):
    mini = _fresh(FIX["set"])
    got = sorted(channels.fused_scores(case["text"], mini).items(), key=lambda kv: (-kv[1], kv[0]))
    assert [k for k, _ in got] == [k for k, _ in case["ranking"]]
    for (_, a), (_, b) in zip(got, case["ranking"]):
        assert math.isclose(a, b, abs_tol=1e-12)
    for k, terms in case["shared"].items():
        assert channels.shared_terms(case["text"], mini, k, 4) == terms


def test_high_utility_case_moves_data_mining_venues_up():
    """Reported case (ISIT first). Measured when the fixture was built, on the full published files:
    the channels move ICDM, PAKDD and DASFAA up compared with the title-profile ranking. ISIT still
    ranks first, and algorithm-theory venues stay ahead of the data-mining venues (see
    evaluation/channel-ranking-*.json); this test records that, it does not claim more."""
    full = FIX["full_set_case"]
    for k in ("icdm", "pakdd", "dasfaa"):
        assert full["channels"][k] < full["title_profiles"][k], (k, full)
    assert full["channels"]["isit"] == 1


def test_fusion_weights_and_order_are_the_measured_ones():
    assert channels.ORDER == ["titles", "keywords", "arxiv"]
    assert channels.WEIGHTS == {"titles": 1.0, "keywords": 1.0, "arxiv": 0.25}
    assert FIX["set"]["fusion"]["order"] == channels.ORDER


def test_bm25_weight_by_hand():
    counts = {"a": (10, {"x": {"2024": 4}, "y": {"2024": 2}}), "b": (10, {"x": {"2024": 1}})}
    spec = {"method": "bm25", "k1": 2.0, "b": 1.0, "recency": 0.7, "phrase": 1.0}
    ch = channels.build_channel(counts, spec, n_venues=2, end_year=2024, drop_withheld=False)
    big_n, avg = 3, (6 + 1) / 2
    idf_x = math.log(1 + (big_n - 2 + 0.5) / (2 + 0.5))
    want = idf_x * 4 * 3 / (4 + 2.0 * (6 / avg))
    assert math.isclose(ch["venues"]["a"]["x"], round(want, 6))
    # recency: a paper from 2023 counts 0.7
    ch2 = channels.build_channel({"a": (10, {"x": {"2023": 1}})}, spec, 1, 2024, drop_withheld=False)
    assert ch2["venues"]["a"]["x"] > 0


def test_prune_merge_and_drop_years():
    raw = {"n_by_year": Counter({"2024": 5}), "terms": {"keep": Counter({"2024": 3}), "rare": Counter({"2024": 2})}}
    p = cc.prune(raw)
    assert set(p["terms"]) == {"keep"} and p["n_by_year"] == {"2024": 5}
    many = {"n_by_year": Counter({"2024": 9}), "terms": {f"t{i:03d}": Counter({"2024": 3}) for i in range(cc.MAX_TERMS + 7)}}
    assert len(cc.prune(many)["terms"]) == cc.MAX_TERMS
    new = {"n_by_year": Counter({"2025": 4}), "terms": {"keep": Counter({"2025": 1}), "fresh": Counter({"2025": 2}), "strong": Counter({"2025": 3})}}
    m = cc.merge(p, new)
    assert m["terms"]["keep"] == {"2024": 3, "2025": 1}      # kept term: any count is added
    assert "fresh" not in m["terms"] and "strong" in m["terms"]  # new term needs >= 3 papers
    d = cc.drop_years(m, 2025)
    assert d["n_by_year"] == {"2025": 4} and "keep" not in d["terms"]  # 1 paper left in the window


def test_update_skips_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.config/openalex/api_key either
    counts = tmp_path / "counts.json"
    counts.write_text(json.dumps({"years": [2020, 2021, 2022, 2023, 2024], "venues": {}}))
    before = counts.read_bytes()
    assert update_channel_counts.main(["--dump", str(tmp_path / "none.xml.gz"), "--year", "2025", "--counts", str(counts)]) == 0
    assert "OPENALEX_API_KEY is not set: skipping" in capsys.readouterr().out
    assert counts.read_bytes() == before


def test_update_is_a_no_op_when_the_year_is_present(tmp_path, capsys):
    counts = tmp_path / "counts.json"
    counts.write_text(json.dumps({"years": [2021, 2022, 2023, 2024, 2025], "venues": {}}))
    assert update_channel_counts.main(["--dump", "unused", "--year", "2025", "--counts", str(counts)]) == 0
    assert "already hold 2025" in capsys.readouterr().out


def test_published_counts_follow_the_rules():
    path = ROOT / "data" / "channel_counts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    checked = 0
    for k, v in data["venues"].items():
        for ch in cc.CHANNEL_NAMES:
            terms = v[ch]["terms"]
            assert len(terms) <= cc.MAX_TERMS, k
            for t, ys in terms.items():
                assert sum(ys.values()) >= cc.MIN_PAPERS_PER_TERM, (k, t)
                assert sum(ys.values()) <= sum(v[ch]["n_by_year"].values()), (k, t)
                checked += 1
    assert checked > 10000


if __name__ == "__main__" and "--write" in sys.argv:
    FIXTURE.write_text(json.dumps(build_fixture(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(ROOT).as_posix()}")
