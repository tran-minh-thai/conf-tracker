# SPDX-License-Identifier: MIT
import os
"""Probe: repository module conftracker.channels (built from the study's counts, end year 2024, withheld filter off)
must give the same fused ranks as the study code (rank_study.Channel + rank_run fuse, T+K+A1, weights 1/1/0.25)."""
import sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")); sys.path.insert(0, ".")
import numpy as np
from conftracker import channels as C
import rank_study as R
from rank_study import VENUES
IDX = {k: i for i, k in enumerate(VENUES)}
ch = R.channel_counts()
names = {"titles": "T", "keywords": "K", "arxiv": "A1"}
study = {"T": dict(method="cosine", r=0.85, p=1.0), "K": dict(method="bm25", k1=2.0, b=1.0, r=0.7, p=1.5), "A1": dict(method="cosine", r=0.85, p=1.0)}
data = {"fusion": {"weights": C.WEIGHTS}, "channels": {}}
for n, c in names.items():
    built = C.build_channel(ch[c], C.CHANNELS[n], len(VENUES), 2024, drop_withheld=False)
    built["phrase"] = C.CHANNELS[n]["phrase"]; data["channels"][n] = built
chan = {c: R.Channel(ch[c], **study[c]) for c in study}
qa = [(k, a) for k, a, t in R.queries_abstract() if k in R.base["profiles"]]
def rank(sc, key): return R.rank_of(sc, key)
dis, n, worst = 0, 0, 0
for k, text in qa:
    a = C.fused_scores(text, data)
    per = {c: chan[c].scores(text) for c in study}
    b = {}
    for c, w in (("T", 1.0), ("K", 1.0), ("A1", 0.25)):
        m = max(per[c].values(), default=0)
        if m > 0:
            for v, x in per[c].items(): b[v] = b.get(v, 0) + w * x / m
    ra, rb = rank(a, k), rank(b, k); n += 1
    if ra != rb: dis += 1; worst = max(worst, abs(ra - rb))
print("queries compared", n, "rank disagreements", dis, "largest rank difference", worst)
sizes = {nm: len(json.dumps({"query_weight": d["query_weight"], "venues": d["venues"]}, separators=(",", ":"))) for nm, d in data["channels"].items()}
print("channel sizes (bytes)", sizes, "total", sum(sizes.values()))
