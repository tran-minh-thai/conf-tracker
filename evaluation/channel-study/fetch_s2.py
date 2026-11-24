# SPDX-License-Identifier: MIT
"""Fetch abstracts from the Semantic Scholar batch endpoint for the same per-venue DOI sample."""
import json, sys, time, random, urllib.request, os
S = sys.argv[1]
d = json.load(open(f"{S}/papers.json"))
by = {}
for k, y, t, doi in d["rows"]:
    if y == 2025 and doi: by.setdefault(k, []).append((doi.lower(), t))
want = []
for k in sorted(by):
    items = sorted(by[k]); random.Random(k).shuffle(items)
    want += [doi for doi, _ in items[:80]]
path = f"{S}/s2_abstracts.json"
cache = json.load(open(path)) if os.path.exists(path) else {}
todo = [x for x in want if x not in cache]
print("wanted", len(want), "to fetch", len(todo), flush=True)
for i in range(0, len(todo), 400):
    batch = todo[i:i + 400]
    body = json.dumps({"ids": [f"DOI:{x}" for x in batch]}).encode()
    res = None
    for attempt in range(30):
        try:
            req = urllib.request.Request("https://api.semanticscholar.org/graph/v1/paper/batch?fields=abstract",
                                         data=body, headers={"User-Agent": "conf-tracker-evaluation/1.0", "Content-Type": "application/json"})
            res = json.load(urllib.request.urlopen(req, timeout=120)); break
        except Exception as e:
            time.sleep(min(60, 3 * (attempt + 1)))
    if res is None:
        print("gave up", i, flush=True); continue
    for x, r in zip(batch, res): cache[x] = (r or {}).get("abstract") or ""
    json.dump(cache, open(path, "w"))
    print(i, len(cache), sum(1 for v in cache.values() if v), flush=True)
    time.sleep(3)
print("done", len(cache), sum(1 for v in cache.values() if v))
