# SPDX-License-Identifier: MIT
"""Pre-registered ranking study driver. Stage 1 (validation): per-channel scoring settings. Stage 2 (validation):
fusion. Stage 3: one read of the test half for the named variants. Inputs: aggregated counts only (+ test queries)."""
import itertools, json, math, sys
from collections import Counter, defaultdict
import numpy as np
sys.path.insert(0, ".")
import rank_study as R
from rank_study import P, VENUES, AREA
IDX = {k: i for i, k in enumerate(VENUES)}; NV = len(VENUES)
base = R.base
qa = [(k, a, t) for k, a, t in R.queries_abstract() if k in base["profiles"]]
val = [(k, a) for i, (k, a, _) in enumerate(qa) if i % 2 == 0]
test = [(k, a) for i, (k, a, _) in enumerate(qa) if i % 2 == 1]
titles = [(k, t) for k, t, _ in R.queries_title() if k in base["profiles"]]
ch = R.channel_counts()
for c in ch: R.CHAN_VENUES[c] = set(ch[c])
print("channel venues", {c: len(v) for c, v in ch.items()}, flush=True)

# current shipped matcher: title profiles (top 120 cosine) + paper_vector
inv = defaultdict(list)
for k, p in base["profiles"].items():
    for t, w in p["terms"].items(): inv[t].append((IDX[k], w))
spec_cur = P.term_specificity(p["terms"] for p in base["profiles"].values())
def current_matrix(qs):
    M = np.zeros((len(qs), NV))
    for i, (_, text) in enumerate(qs):
        for t, w in P.paper_vector([text], base["idf"], spec_cur).items():
            for j, x in inv.get(t, ()): M[i, j] += w * x
    return M
def matrix(chan, qs):
    M = np.zeros((len(qs), NV))
    for i, (_, text) in enumerate(qs):
        for k, v in chan.scores(text).items(): M[i, IDX[k]] = v
    return M
def ranks(M, qs):
    tr = np.array([IDX[k] for k, _ in qs]); st = M[np.arange(len(qs)), tr][:, None]
    order_idx = np.arange(NV)[None, :]
    r = 1 + (M > st).sum(1) + ((M == st) & (order_idx < tr[:, None])).sum(1)
    r[st[:, 0] <= 0] = NV
    return r
mrr = lambda r: float(np.mean(1.0 / r))
res = {"channel_venues": {c: len(v) for c, v in ch.items()}}

# Stage 1
best = {}
for c in ("T", "K", "A1", "A2", "Ac"):
    trials = {}
    def tr_(name, **kw):
        trials[name] = mrr(ranks(matrix(R.Channel(ch[c], **kw), val), val)); print(c, name, round(trials[name], 4), flush=True); return trials[name]
    for r in (1.0, 0.85, 0.7):
        for p in (1.0, 1.5, 2.5): tr_(f"cosine r={r} p={p}", method="cosine", r=r, p=p)
    bm = {(k1, b): tr_(f"bm25 k1={k1} b={b}", method="bm25", k1=k1, b=b) for k1 in (0.6, 1.2, 2.0) for b in (0.25, 0.5, 0.75, 1.0)}
    k1, b = max(bm, key=bm.get)
    rr = {r: tr_(f"bm25 k1={k1} b={b} r={r}", method="bm25", k1=k1, b=b, r=r) for r in (0.85, 0.7)}; rr[1.0] = bm[(k1, b)]
    r = max(rr, key=rr.get)
    pp = {p: tr_(f"bm25 k1={k1} b={b} r={r} p={p}", method="bm25", k1=k1, b=b, r=r, p=p) for p in (1.5, 2.5)}; pp[1.0] = rr[r]
    p = max(pp, key=pp.get)
    cos_best = max((n for n in trials if n.startswith("cosine")), key=trials.get)
    if trials[cos_best] >= pp[p]:
        rc, pc = [float(x.split("=")[1]) for x in cos_best.split()[1:]]
        best[c] = dict(method="cosine", r=rc, p=pc)
    else:
        best[c] = dict(method="bm25", k1=k1, b=b, r=r, p=p)
    res.setdefault("stage1", {})[c] = {"trials": trials, "chosen": best[c]}
    print("chosen", c, best[c], flush=True)

# matrices for chosen settings
chan = {c: R.Channel(ch[c], **best[c]) for c in best}
Mv = {c: matrix(chan[c], val) for c in chan}
if "--validation-only" not in sys.argv:
    Mt = {c: matrix(chan[c], test) for c in chan}; Mq = {c: matrix(chan[c], titles) for c in chan}
present = {c: np.array([k in ch[c] for k in VENUES]) for c in ch}
def fuse(M, weights, method, impute):
    out = np.zeros_like(M["T"])
    tn = M["T"] / np.maximum(M["T"].max(1, keepdims=True), 1e-12)
    if method == "rrf":
        def rr_(A): return 1.0 / (60 + 1 + np.argsort(np.argsort(-A, axis=1), axis=1))
        tr_r = rr_(M["T"])
    for c, w in weights.items():
        if not w: continue
        if method == "sum":
            X = M[c] / np.maximum(M[c].max(1, keepdims=True), 1e-12)
            if impute and c != "T": X = np.where(present[c][None, :], X, tn)
        else:
            X = rr_(M[c]) * (M[c] > 0)
            if impute and c != "T": X = np.where(present[c][None, :], X, tr_r)
        out += w * X
    return out
# Stage 2
sets = {"T+K": ["K"], "T+A1": ["A1"], "T+K+A1": ["K", "A1"], "T+K+A2": ["K", "A2"], "T+K+Ac": ["K", "Ac"]}
grid = (0, 0.25, 0.5, 1, 2)
chosen = {}
for name, others in sets.items():
    bestv = None
    for method in ("sum", "rrf"):
        for impute in (0, 1):
            for ws in itertools.product(grid, repeat=len(others)):
                if not any(ws): continue
                weights = {"T": 1, **dict(zip(others, ws))}
                v = mrr(ranks(fuse(Mv, weights, method, impute), val))
                if bestv is None or v > bestv[0]: bestv = (v, method, impute, weights)
    chosen[name] = bestv; print("fusion", name, round(bestv[0], 4), bestv[1:], flush=True)
res["stage2"] = {n: {"val_mrr": v[0], "method": v[1], "impute": v[2], "weights": v[3]} for n, v in chosen.items()}
res["stage2"]["T_alone_val_mrr"] = mrr(ranks(Mv["T"], val))

# Stage 3: test, once (skipped with --validation-only)
if "--validation-only" in sys.argv:
    json.dump(res, open(sys.argv[1], "w"), indent=1, default=float); print("validation only: test half not read"); sys.exit(0)
cur_t = ranks(current_matrix(test), test); cur_q = ranks(current_matrix(titles), titles)
def boot(a, b, n=2000):
    d = 1.0 / b - 1.0 / a; rng = np.random.default_rng(7); m = len(d)
    ms = np.sort([d[rng.integers(0, m, m)].mean() for _ in range(n)])
    return round(float(d.mean()), 4), [round(float(ms[int(.025 * n)]), 4), round(float(ms[int(.975 * n)]), 4)]
smp = json.load(open("train_sample.json")); size = {k: min(200, v) for k, v in smp["papers"].items()}
def report(rt, rq, chans):
    out = {"test": {"mrr": round(mrr(rt), 4), "r@5": round(float(np.mean(rt <= 5)), 4), "r@10": round(float(np.mean(rt <= 10)), 4),
                    "delta_ci": boot(cur_t, rt), "better": int((rt < cur_t).sum()), "worse": int((rt > cur_t).sum())},
           "titles": {"mrr": round(mrr(rq), 4), "delta_ci": boot(cur_q, rq)}}
    area = defaultdict(list)
    for i, (k, _) in enumerate(test): area[AREA.get(k)].append(i)
    out["per_area"] = {a: [len(ix), round(mrr(cur_t[ix]), 3), round(mrr(rt[ix]), 3)] for a, ix in sorted(area.items(), key=lambda x: str(x[0]))}
    for c in chans:
        if c == "T": continue
        cov = {k: (ch[c][k][0] / size[k] if k in ch[c] else 0.0) for k in VENUES}
        ix = [i for i, (k, _) in enumerate(test) if cov[k] < 0.2]
        if ix: out[f"under20_{c}"] = [len(ix), len({test[i][0] for i in ix}), round(mrr(cur_t[ix]), 4), round(mrr(rt[ix]), 4), boot(cur_t[ix], rt[ix])]
    return out
res["test"] = {"current": {"test": {"mrr": round(mrr(cur_t), 4), "r@5": round(float(np.mean(cur_t <= 5)), 4), "r@10": round(float(np.mean(cur_t <= 10)), 4)}, "titles": {"mrr": round(mrr(cur_q), 4)}}}
res["test"]["T alone"] = report(ranks(Mt["T"], test), ranks(Mq["T"], titles), ["T"])
for name, (v, method, impute, weights) in chosen.items():
    res["test"][name] = report(ranks(fuse(Mt, weights, method, impute), test), ranks(fuse(Mq, weights, method, impute), titles), list(weights))
    print("test", name, res["test"][name]["test"], "titles", res["test"][name]["titles"], flush=True)
ab = "Mining high-utility sequential patterns from large transaction databases. We propose a pattern-growth algorithm with tighter utility upper bounds for pruning, evaluated on real-world datasets.\nA tighter utility upper bound\nAn efficient pattern-growth mining algorithm"
case_q = [("icdm", ab)]
for name, (v, method, impute, weights) in [("T alone", (0, "sum", 0, {"T": 1}))] + list(chosen.items()):
    M = fuse({c: matrix(chan[c], case_q) for c in chan}, weights, method, impute)[0]
    order = [VENUES[j] for j in np.argsort(-M)]
    res.setdefault("case", {})[name] = {"top8": order[:8], "rank": {k: order.index(k) + 1 for k in ("isit", "icdm", "pakdd", "dasfaa", "kdd", "dexa", "edbt")}}
print(json.dumps(res["test"], indent=0)[:4000]); print(json.dumps(res["case"]))
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
