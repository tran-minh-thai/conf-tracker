# SPDX-License-Identifier: MIT
"""Ranking study (pre-registered in ranking-study-preregistration.md). Reads only aggregated counts."""
import json, math, os, random, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")); sys.path.insert(0, ".")
from conftracker import profiles as P
from harness import queries_abstract, queries_title, load_train
CNT = os.path.expanduser("~/data-local/conf-tracker-eval/counts")
base = load_train(); VENUES = sorted(base["profiles"]); AREA = base["area"]
d = json.load(open("papers.json"))

def channel_counts():
    """{channel: {venue: (n_papers, {term: {year: papers}})}}; T from all DBLP titles 2020-2024."""
    ch = {"T": {}}
    tc = defaultdict(lambda: defaultdict(Counter)); tn = Counter()
    for k, y, t, _ in d["rows"]:
        if 2020 <= y <= 2024 and k in base["profiles"]:
            tn[k] += 1
            for term in set(P.tokens(t)): tc[k][term][str(y)] += 1
    ch["T"] = {k: (tn[k], {t: dict(c) for t, c in tc[k].items() if sum(c.values()) >= 2}) for k in VENUES}
    for name, v in (("K", "kw"), ("A1", "arxiv"), ("A2", "arxiv_oa"), ("Ac", "all")):
        ch[name] = {}
        for k in VENUES:
            f = os.path.join(CNT, k + ".json")
            if os.path.exists(f):
                x = json.load(open(f))["variants"][v]
                if x["n"] >= 20: ch[name][k] = (x["n"], x["terms"])
    return ch

class Channel:
    def __init__(self, counts, method, k1=1.2, b=0.75, r=1.0, p=1.0, top_k=120):
        self.method, self.p = method, p
        tf = {k: {t: sum(c * r ** (2024 - int(y)) for y, c in ys.items()) for t, ys in terms.items()} for k, (n, terms) in counts.items()}
        N = len(VENUES) + 1; df = Counter(t for k in tf for t in tf[k])
        self.inv = defaultdict(list)
        if method == "cosine":
            idf = {t: math.log((N + 1) / (x + 1)) + 1 for t, x in df.items()}
            for k, terms in tf.items():
                n = counts[k][0]
                w = sorted(((t, c / n * idf[t]) for t, c in terms.items()), key=lambda x: (-x[1], x[0]))[:top_k]
                norm = math.sqrt(sum(x * x for _, x in w)) or 1
                for t, x in w: self.inv[t].append((k, x / norm))
            self.vocab_idf = idf
        else:
            idf = {t: math.log(1 + (N - x + 0.5) / (x + 0.5)) for t, x in df.items()}
            ln = {k: sum(terms.values()) for k, terms in tf.items()}; avg = sum(ln.values()) / max(1, len(ln))
            for k, terms in tf.items():
                norm = k1 * (1 - b + b * ln[k] / avg)
                for t, c in terms.items(): self.inv[t].append((k, idf[t] * c * (k1 + 1) / (c + norm)))
            self.vocab_idf = idf
        self.spec = P.term_specificity({t: 1 for t in terms} for terms in tf.values())
        self.venues = set(tf)
    def scores(self, text):
        c = Counter(t for t in P.tokens(text) if t in self.inv)
        q = {t: (1 + math.log(x)) * self.spec.get(t, 1.0) ** 0.5 * (self.p if "_" in t else 1.0) for t, x in c.items()}
        if self.method == "cosine":
            q = {t: w * self.vocab_idf[t] for t, w in q.items()}
        sc = defaultdict(float)
        for t, w in q.items():
            for k, x in self.inv[t]: sc[k] += w * x
        return sc

def rank_of(sc, key):
    s = sc.get(key, 0.0)
    if s <= 0: return len(VENUES)
    return 1 + sum(1 for k, v in sc.items() if v > s or (v == s and k < key))

def fuse(per, weights, method, impute):
    out = defaultdict(float)
    t_norm = None
    if "T" in per:
        mt = max(per["T"].values(), default=0) or 1; t_norm = {k: v / mt for k, v in per["T"].items()}
    for c, sc in per.items():
        w = weights.get(c, 0)
        if not w: continue
        if method == "sum":
            m = max(sc.values(), default=0) or 1
            for k, v in sc.items(): out[k] += w * v / m
            if impute and c != "T" and t_norm:
                for k in VENUES:
                    if k not in CHAN_VENUES[c]: out[k] += w * t_norm.get(k, 0)
        else:
            order = sorted(sc, key=lambda k: -sc[k]); rank = {k: i + 1 for i, k in enumerate(order)}
            for k in rank: out[k] += w / (60 + rank[k])
            if impute and c != "T" and "T" in per:
                ot = sorted(per["T"], key=lambda k: -per["T"][k])
                for i, k in enumerate(ot):
                    if k not in CHAN_VENUES[c]: out[k] += w / (60 + i + 1)
    return out
CHAN_VENUES = {}
def metrics(ranks):
    m = len(ranks) or 1
    return {"queries": len(ranks), "mrr": round(sum(1 / r for r in ranks) / m, 4), "r@5": round(sum(r <= 5 for r in ranks) / m, 4), "r@10": round(sum(r <= 10 for r in ranks) / m, 4)}
def boot(a, b, n=2000):
    dd = [1 / y - 1 / x for x, y in zip(a, b)]; m = len(dd); rnd = random.Random(7)
    ms = sorted(sum(dd[rnd.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return round(sum(dd) / m, 4), [round(ms[int(.025 * n)], 4), round(ms[int(.975 * n)], 4)]
