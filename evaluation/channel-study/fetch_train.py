# SPDX-License-Identifier: MIT
"""Semantic Scholar abstracts for a seeded sample of up to 200 DOIs per venue from 2020-2024."""
import json, sys, time, random, urllib.request, os
from collections import Counter
S, out = sys.argv[1], sys.argv[2]
d = json.load(open(f"{S}/papers.json"))
by, total, with_doi = {}, Counter(), Counter()
for k, y, t, doi in d["rows"]:
    if 2020 <= y <= 2024:
        total[k] += 1
        if doi: with_doi[k] += 1; by.setdefault(k, []).append(doi.lower())
want = []
for k in sorted(by):
    items = sorted(set(by[k])); random.Random(k).shuffle(items); want += items[:200]
json.dump({"sample": want, "papers": total, "with_doi": with_doi}, open(f"{S}/train_sample.json", "w"))
cache = json.load(open(out)) if os.path.exists(out) else {}
todo = [x for x in want if x not in cache]
print("venues", len(by), "sample", len(want), "to fetch", len(todo), flush=True)
for i in range(0, len(todo), 400):
    batch = todo[i:i + 400]; body = json.dumps({"ids": [f"DOI:{x}" for x in batch]}).encode(); res = None
    for attempt in range(40):
        try:
            req = urllib.request.Request("https://api.semanticscholar.org/graph/v1/paper/batch?fields=abstract", data=body,
                                         headers={"User-Agent": "conf-tracker-evaluation/1.0", "Content-Type": "application/json"})
            res = json.load(urllib.request.urlopen(req, timeout=120)); break
        except Exception:
            time.sleep(min(60, 3 * (attempt + 1)))
    if res is None: print("gave up", i, flush=True); continue
    for x, r in zip(batch, res): cache[x] = (r or {}).get("abstract") or ""
    json.dump(cache, open(out, "w"))
    print(i + len(batch), len(cache), sum(1 for v in cache.values() if v), flush=True)
    time.sleep(3)
print("done", len(cache), sum(1 for v in cache.values() if v), flush=True)
