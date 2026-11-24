# SPDX-License-Identifier: MIT
"""Counts for the 27 venues with DOIs for under half their papers: OpenAlex works listed by source and year,
kept on exact DBLP title match (venue identity from DBLP), seeded sample of <= 200; then the same in-memory,
counts-only aggregation as collect.py. Semantic Scholar is used only where the paper has a DOI in its cache."""
import json, os, re, sys, random
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")); sys.path.insert(0, ".")
from conftracker import profiles as P
from oa_common import get, text, STATE
from harness import clean_abstract
import collect_helpers as H
OUT = os.path.expanduser("~/data-local/conf-tracker-eval/counts")
d = json.load(open("papers.json")); tr = json.load(open("train.json")); smp = json.load(open("train_sample.json"))
s2 = json.load(open(os.path.expanduser("~/data-local/conf-tracker-eval/s2_abstracts_train.json")))
LOW = sorted(k for k in tr["profiles"] if smp["with_doi"].get(k, 0) < 0.5 * smp["papers"][k])
norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
titles = defaultdict(dict)
for k, y, t, _ in d["rows"]:
    if k in LOW and 2020 <= y <= 2024: titles[(k, y)][norm(t)] = t
SEL = "title,doi,keywords,topics,locations,abstract_inverted_index"
DONE = {k for k in LOW if os.path.exists(os.path.join(OUT, k + ".json")) and json.load(open(os.path.join(OUT, k + ".json"))).get("matched", 0) >= 20}
for k in LOW:
    if k in DONE: continue
    votes = Counter()
    for y in range(2020, 2025):  # every year with titles (biennial venues have none in some years)
        ts = sorted(titles[(k, y)].values())
        for t in random.Random(k + str(y)).sample(ts, min(2, len(ts))):
            r = get("works", {"filter": f"title.search:{re.sub(r'[,:|]', ' ', t)},publication_year:{y}", "select": "title,locations", "per-page": 5})
            for w in (r or {}).get("results", []):
                if norm(w.get("title")) == norm(t):
                    for loc in w.get("locations") or []:
                        src = (loc or {}).get("source") or {}
                        # a repository (arXiv, institutional) is not the venue, and listing it pages through millions of works
                        if src.get("id") and src.get("type") in ("conference", "journal", "book series", "ebook platform"): votes[src["id"]] += 1
    sources = [sid for sid, _ in votes.most_common(2)]
    matched = {}
    for y in range(2020, 2025):
        for sid in sources:
            cursor = "*"
            for _ in range(25):  # at most 5,000 works per source and year
                r = get("works", {"filter": f"locations.source.id:{sid.split('/')[-1]},publication_year:{y}", "select": SEL, "per-page": 200, "cursor": cursor})
                if not r: break
                for w in r["results"]:
                    n = norm(w.get("title"))
                    if n in titles[(k, y)] and (y, n) not in matched: matched[(y, n)] = w
                cursor = r["meta"].get("next_cursor")
                if not cursor or not r["results"]: break
    keys = sorted(matched); random.Random(k).shuffle(keys); keys = keys[:200]
    papers = []
    for (y, n) in keys:
        w = matched[(y, n)]; doi = (w.get("doi") or "").lower().replace("https://doi.org/", "")
        papers.append({"id": doi or f"dblp:{k}:{y}:{n[:60]}", "year": y, "doi": doi, "work": w})
    out = H.aggregate(k, papers, s2)
    out.update({"listing_sources": sources, "dblp_titles": sum(len(titles[(k, y)]) for y in range(2020, 2025)), "matched": len(matched)})
    json.dump(out, open(os.path.join(OUT, k + ".json"), "w"))
    print(k, "dblp titles", out["dblp_titles"], "matched", len(matched), "sample", len(papers), {v: out["variants"][v]["n"] for v in out["variants"]},
          "OpenAlex requests left", STATE["remaining"], flush=True)
print("finished low-DOI pass", len(LOW), flush=True)
