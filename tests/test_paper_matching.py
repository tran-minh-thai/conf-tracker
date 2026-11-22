# SPDX-License-Identifier: MIT
"""Paper-to-venue query (abstract + contributions), shared with assets/match.js and the iOS ConfCore.

tests/fixtures/paper_match_cases.json freezes the inputs (twelve venue profiles, idf and specificity
of the query terms, taken from the published data/venue_profiles.json named in the fixture) so the
expected scores do not move when the profiles are rebuilt. Regenerate with:
    python tests/test_paper_matching.py --write
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftracker import profiles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "paper_match_cases.json"
VENUES = ["icalp", "isit", "soda", "coco", "stoc", "colt", "dexa", "edbt", "cidr", "icdm", "pakdd", "kdd"]
CASES = [
    {"name": "high-utility sequential pattern mining",
     "fields": ["Mining high-utility sequential patterns from large transaction databases. We propose a pattern-growth "
                "algorithm with tighter utility upper bounds for pruning, evaluated on real-world datasets.",
                "A tighter utility upper bound\nAn efficient pattern-growth mining algorithm"]},
    {"name": "abstract only", "fields": ["Graph neural networks for fraud detection in transaction databases.", ""]},
    {"name": "contributions only", "fields": ["", "Lower bounds for online learning with expert advice"]},
]


def old_query(fields, idf):
    """The query before the change: one normalised vector per field, summed with weight 1."""
    out = {}
    for f in fields:
        if f.strip():
            for t, w in profiles.query_vector(f, idf).items():
                out[t] = out.get(t, 0.0) + w
    norm = math.sqrt(sum(w * w for w in out.values())) or 1.0
    return {t: w / norm for t, w in out.items()}


def ranking(q, prof):
    scored = [(profiles.score(q, p["terms"]), k) for k, p in prof.items()]
    return [[k, s] for s, k in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0]


def build():
    src = ROOT / "data" / "venue_profiles.json"
    pub = json.loads(src.read_text(encoding="utf-8"))
    spec_full = profiles.term_specificity(p["terms"] for p in pub["profiles"].values())
    terms = sorted({t for c in CASES for f in c["fields"] for t in profiles.tokens(f) if t in pub["idf"]})
    data = {
        "note": "Shared by tests/test_paper_matching.py, tests/core.test.js and the iOS ConfCore tests.",
        "source": {"file": "data/venue_profiles.json", "generated_at": pub["generated_at"],
                   "sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "profiles_total": len(pub["profiles"])},
        "stopwords": pub["stopwords"],
        "idf": {t: pub["idf"][t] for t in terms},
        "specificity": {t: spec_full.get(t, 1.0) for t in terms},
        "profiles": {k: pub["profiles"][k] for k in VENUES},
        "specificity_unit": {"vectors": [["a", "b"], ["a"], ["a", "c"]],
                             "expected": profiles.term_specificity({t: 1 for t in v} for v in [["a", "b"], ["a"], ["a", "c"]])},
        "cases": [],
    }
    for c in CASES:
        q = profiles.paper_vector(c["fields"], data["idf"], data["specificity"])
        data["cases"].append({**c, "query": dict(sorted(q.items())),
                              "ranking": ranking(q, data["profiles"]),
                              "ranking_before_change": [k for k, _ in ranking(old_query(c["fields"], data["idf"]), data["profiles"])]})
    return data


FIX = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else None


def test_specificity_formula():
    exp = FIX["specificity_unit"]["expected"]
    got = profiles.term_specificity({t: 1 for t in v} for v in FIX["specificity_unit"]["vectors"])
    assert got.keys() == exp.keys()
    top = math.log(4) + 1
    assert math.isclose(got["a"], (math.log(4 / 4) + 1) / top) and math.isclose(got["b"], (math.log(4 / 2) + 1) / top)
    for t in exp:
        assert math.isclose(got[t], exp[t], rel_tol=0, abs_tol=1e-12)


@pytest.mark.parametrize("case", FIX["cases"] if FIX else [], ids=lambda c: c["name"])
def test_paper_query_matches_fixture(case):
    q = profiles.paper_vector(case["fields"], FIX["idf"], FIX["specificity"])
    assert q.keys() == case["query"].keys()
    for t, w in case["query"].items():
        assert math.isclose(q[t], w, abs_tol=1e-12)
    got = ranking(q, FIX["profiles"])
    assert [k for k, _ in got] == [k for k, _ in case["ranking"]]
    for (_, a), (_, b) in zip(got, case["ranking"]):
        assert math.isclose(a, b, abs_tol=1e-12)


def test_high_utility_case_moves_data_mining_venues_above_theory():
    """Reported case: ISIT ranked first. Measured effect of the change on the frozen profiles:
    the database venues EDBT and DEXA move above three theory venues they trailed before.
    ICALP and ISIT stay first and second: title profiles of data-mining venues hold no
    'utility' term (2 of 731 ICDM titles), which a query-side change cannot add."""
    case = next(c for c in FIX["cases"] if c["name"].startswith("high-utility"))
    new = [k for k, _ in case["ranking"]]
    old = case["ranking_before_change"]
    for db in ("edbt", "dexa"):
        for theory in ("soda", "coco", "stoc"):
            assert new.index(db) < new.index(theory), (db, theory, new)
    assert any(old.index(db) > old.index("soda") for db in ("edbt", "dexa")), old


def test_fixture_inputs_are_consistent():
    assert FIX["source"]["profiles_total"] > 300
    assert set(FIX["profiles"]) == set(VENUES)
    for t, s in FIX["specificity"].items():
        assert 0 < s <= 1 and FIX["idf"][t] > 0


if __name__ == "__main__" and "--write" in sys.argv:
    FIXTURE.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(ROOT).as_posix()}")
