# SPDX-License-Identifier: MIT
"""Abstracts for venues with few DOIs: Semantic Scholar bulk search by venue/year, kept only on exact DBLP title match."""
import json, re, sys, time, random, urllib.request, urllib.parse, os
from collections import Counter, defaultdict
out = sys.argv[1]
d = json.load(open("papers.json")); s = json.load(open("train_sample.json")); tr = json.load(open("train.json"))
low = sorted(k for k in tr["profiles"] if s["with_doi"].get(k, 0) < 0.5 * s["papers"][k])
norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
titles = defaultdict(dict)
for k, y, t, _ in d["rows"]:
    if k in low and 2020 <= y <= 2024: titles[(k, y)][norm(t)] = t
UA = {"User-Agent": "conf-tracker-evaluation/1.0"}
def get(url):
    for a in range(40):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read(), strict=False)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(min(60, 3 * (a + 1)))
        except Exception: time.sleep(min(60, 3 * (a + 1)))
    return None
cache = json.load(open(out)) if os.path.exists(out) else {"venue_names": {}, "abstracts": {}}
for k in low:
    if k not in cache["venue_names"]:
        votes = Counter()
        ts = sorted(titles[(k, 2023)].values() or titles[(k, 2022)].values())
        for t in random.Random(k).sample(ts, min(4, len(ts))):
            r = get("https://api.semanticscholar.org/graph/v1/paper/search/match?" + urllib.parse.urlencode({"query": t, "fields": "title,venue"}))
            for p in (r or {}).get("data", []):
                if norm(p.get("title")) == norm(t) and p.get("venue"): votes[p["venue"]] += 1
            time.sleep(1.5)
        cache["venue_names"][k] = votes.most_common(1)[0][0] if votes else ""
        json.dump(cache, open(out, "w")); print(k, "venue name", repr(cache["venue_names"][k]), dict(votes), flush=True)
    name = cache["venue_names"][k]
    if not name: continue
    for y in range(2020, 2025):
        tag = f"{k}:{y}"
        if tag in cache["abstracts"]: continue
        r = get("https://api.semanticscholar.org/graph/v1/paper/search/bulk?" + urllib.parse.urlencode({"venue": name, "year": str(y), "fields": "title,abstract"}))
        got = {}
        for p in (r or {}).get("data", []):
            n = norm(p.get("title"))
            if n in titles[(k, y)] and p.get("abstract"): got[n] = p["abstract"]
        cache["abstracts"][tag] = got
        json.dump(cache, open(out, "w")); print(k, y, "dblp titles", len(titles[(k, y)]), "matched with abstract", len(got), flush=True)
        time.sleep(3)
print("done", sum(len(v) for v in cache["abstracts"].values()), flush=True)
