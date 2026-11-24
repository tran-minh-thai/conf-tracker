# SPDX-License-Identifier: MIT
import json, os, math, re, sys, html
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from conftracker import profiles as P
S = os.environ.get("CHANNEL_STUDY_DATA", ".")  # folder holding papers.json, train.json, abstract caches

def load_train(name="train.json"):
    return json.load(open(f"{S}/{name}"))

TAG = re.compile(r"<[^>]+>")
def clean_abstract(a):
    a = html.unescape(TAG.sub(" ", a or ""))
    a = re.sub(r"^\s*(abstract|summary)\b[:.]?\s*", "", a.strip(), flags=re.I)
    return re.sub(r"\s+", " ", a).strip()

def queries_abstract(min_per_venue=5, per_venue=30):
    d = json.load(open(f"{S}/papers.json")); ab = json.load(open(f"{S}/abstracts.json"))
    try:
        s2 = json.load(open(f"{S}/s2_abstracts.json"))
    except FileNotFoundError:
        s2 = {}
    ab = {k: (s2.get(k) or ab.get(k) or "") for k in set(ab) | set(s2)}
    by = defaultdict(list)
    for k, y, t, doi in d["rows"]:
        if y == 2025 and doi and ab.get(doi.lower()):
            a = clean_abstract(ab[doi.lower()])
            if len(a.split()) >= 40: by[k].append((doi.lower(), a, t))
    out = []
    for k in sorted(by):
        items = sorted(by[k])[:per_venue]
        if len(items) >= min_per_venue: out += [(k, a, t) for _, a, t in items]
    return out

def queries_title(per_venue=30):
    d = json.load(open(f"{S}/papers.json"))
    by = defaultdict(list)
    for k, y, t, _ in d["rows"]:
        if y == 2025: by[k].append(t)
    out = []
    for k in sorted(by):
        titles = sorted(by[k])
        if len(titles) < 10: continue
        step = max(1, len(titles) // per_venue)
        out += [(k, t, t) for t in titles[::step][:per_venue]]
    return out

class Scorer:
    """Baseline = app behaviour: cosine of query tf-idf vector with the venue's top-k profile."""
    def __init__(self, tr, spread=None, alpha=0.0, prior=0.0, prior_k=3):
        self.prof = {k: v["terms"] for k, v in tr["profiles"].items()}
        self.idf = tr["idf"]; self.area = tr["area"]; self.spread = spread; self.alpha = alpha
        self.prior = prior; self.prior_k = prior_k
        self.inv = defaultdict(list)
        for k, terms in self.prof.items():
            for t, w in terms.items(): self.inv[t].append((k, w))
        n = len(self.prof); areas = {self.area.get(k) for k in self.prof}
        self.factor = {}
        for t, posting in self.inv.items():
            if spread == "profiles":     # profile-level idf
                self.factor[t] = (math.log((n + 1) / (len(posting) + 1)) + 1) / (math.log(n + 1) + 1)
            elif spread == "areas":      # how many areas carry the term
                na = len({self.area.get(k) for k, _ in posting})
                self.factor[t] = 1.0 / na
            elif spread == "area_entropy":
                mass = defaultdict(float)
                for k, w in posting: mass[self.area.get(k)] += w
                s = sum(mass.values()); h = -sum(m / s * math.log(m / s) for m in mass.values() if m > 0)
                self.factor[t] = 1 - h / math.log(len(areas))
            else:
                self.factor[t] = 1.0
    def qvec(self, text):
        q = P.query_vector(text, self.idf)
        if self.alpha:
            q = {t: w * (self.factor.get(t, 1.0) ** self.alpha) for t, w in q.items()}
        return q
    def scores(self, text):
        q = self.qvec(text); sc = defaultdict(float)
        for t, w in q.items():
            for k, v in self.inv.get(t, ()): sc[k] += w * v
        if self.prior:
            by_area = defaultdict(list)
            for k, s in sc.items(): by_area[self.area.get(k)].append(s)
            agg = {a: sum(sorted(v, reverse=True)[:self.prior_k]) / self.prior_k for a, v in by_area.items()}
            sc = {k: s + self.prior * agg[self.area.get(k)] for k, s in sc.items()}
        return sc
    def rank_of(self, text, key):
        sc = self.scores(text)
        if sc.get(key, 0) <= 0: return len(self.prof)  # unmatched: last (ties broken pessimistically)
        s = sc[key]
        return 1 + sum(1 for k, v in sc.items() if v > s or (v == s and k < key))

def evaluate(scorer, qs, ks=(1, 5, 10), parity=None):
    rows = [(k, q) for i, (k, q, _) in enumerate(qs) if parity is None or i % 2 == parity]
    ranks = [scorer.rank_of(q, k) for k, q in rows]
    m = len(ranks) or 1
    per_v = defaultdict(list)
    for (k, _), r in zip(rows, ranks): per_v[k].append(1 / r)
    res = {"queries": len(ranks), "venues": len(per_v), "mrr": round(sum(1 / r for r in ranks) / m, 4),
           "macro_mrr": round(sum(sum(v) / len(v) for v in per_v.values()) / max(1, len(per_v)), 4)}
    for k in ks: res[f"hit@{k}"] = round(sum(r <= k for r in ranks) / m, 4)
    return res, ranks
