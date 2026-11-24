# SPDX-License-Identifier: MIT
"""Fetch Crossref abstracts for a deterministic sample of 2025 DOIs per venue (batched filter queries)."""
import json, sys, time, random, urllib.request, urllib.parse, os
S = sys.argv[1]
d = json.load(open(f"{S}/papers.json"))
by = {}
for k, y, t, doi in d["rows"]:
    if y == 2025 and doi: by.setdefault(k, []).append((doi.lower(), t))
cache_path = f"{S}/abstracts.json"
cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
want = []
for k in sorted(by):
    items = sorted(by[k])
    random.Random(k).shuffle(items)
    want += [doi for doi, _ in items[:80]]
todo = [x for x in want if x not in cache]
print("venues", len(by), "dois wanted", len(want), "to fetch", len(todo), flush=True)
UA = "conf-tracker-evaluation/1.0"
for i in range(0, len(todo), 40):
    batch = todo[i:i + 40]
    q = urllib.parse.urlencode({"filter": ",".join(f"doi:{x}" for x in batch), "select": "DOI,abstract", "rows": 100})
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"https://api.crossref.org/works?{q}", headers={"User-Agent": UA})
            msg = json.load(urllib.request.urlopen(req, timeout=60))["message"]
            break
        except Exception as e:
            print("retry", i, e, flush=True); time.sleep(5 * (attempt + 1)); msg = None
    if msg is None: continue
    got = {it["DOI"].lower(): it.get("abstract", "") for it in msg["items"]}
    for x in batch: cache[x] = got.get(x, "")
    if (i // 40) % 25 == 0:
        json.dump(cache, open(cache_path, "w")); print(i, sum(1 for v in cache.values() if v), flush=True)
    time.sleep(0.3)
json.dump(cache, open(cache_path, "w"))
print("done", len(cache), "with abstract", sum(1 for v in cache.values() if v))
