# SPDX-License-Identifier: MIT
"""One-off: study count files (2020-2024) -> data/channel_counts.json with the two published channels only.
DOI venues: n per year from each DOI's DBLP year. Low-DOI venues: the rerun output (n per year recorded)."""
import json, os, sys, glob
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from conftracker import channel_counts as cc
out_path = sys.argv[1]
d = json.load(open("papers.json")); year_of = {doi.lower(): y for k, y, t, doi in d["rows"] if doi}
tr = json.load(open("train.json")); smp = json.load(open("train_sample.json"))
low = {k for k in tr["profiles"] if smp["with_doi"].get(k, 0) < 0.5 * smp["papers"][k]}
venues, missing_year = {}, 0
for f in sorted(glob.glob(os.path.expanduser("~/data-local/conf-tracker-eval/counts/*.json"))):
    c = json.load(open(f)); k = c["venue"]
    if k in low: continue
    v = {"mode": "doi"}
    for ch, var in (("keywords", "kw"), ("arxiv", "arxiv")):
        x = c["variants"][var]; n = Counter()
        for doi in x["source_of"]:
            y = year_of.get(doi)
            if y is None: missing_year += 1; continue
            n[str(y)] += 1
        v[ch] = cc.prune({"n_by_year": n, "terms": {t: Counter(ys) for t, ys in x["terms"].items()}})
    venues[k] = v
for f in sorted(glob.glob(os.path.expanduser("~/data-local/conf-tracker-eval/counts_low_rerun/*.json"))):
    c = json.load(open(f)); k = c["venue"]; v = {"mode": "listing", "listing_sources": c.get("listing_sources", [])}
    for ch, var in (("keywords", "kw"), ("arxiv", "arxiv")):
        x = c["variants"][var]
        v[ch] = cc.prune({"n_by_year": Counter(x["n_by_year"]), "terms": {t: Counter(ys) for t, ys in x["terms"].items()}})
    venues[k] = v
data = {"schema_version": 1, "years": [2020, 2021, 2022, 2023, 2024],
        "rules": {"sample": "up to 200 papers per venue over the five years (seeded); later years add up to 40 per venue",
                  "min_papers_per_term": cc.MIN_PAPERS_PER_TERM, "max_terms": cc.MAX_TERMS,
                  "keywords": "names of OpenAlex keywords and topics of each paper", "arxiv": "terms of the paper's arXiv abstract (>= 40 words); text not stored"},
        "sources": {"keywords": "OpenAlex (CC0)", "arxiv": "arXiv API (CC0 1.0 metadata, abstract included)"},
        "venues": venues}
json.dump(data, open(out_path, "w"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
print("venues", len(venues), "doi", sum(1 for v in venues.values() if v["mode"] == "doi"), "listing", sum(1 for v in venues.values() if v["mode"] == "listing"),
      "papers without a DBLP year (DOI venues)", missing_year, "bytes", os.path.getsize(out_path))
