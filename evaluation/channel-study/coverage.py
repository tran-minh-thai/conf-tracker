# SPDX-License-Identifier: MIT
"""Coverage per venue and source, from the aggregated counts (no text). Denominator: min(200, papers 2020-2024)."""
import json, os, glob, sys
from statistics import median
tr = json.load(open("train.json")); smp = json.load(open("train_sample.json"))
fb = set(json.load(open("record025.json"))["fallback"][2])
low = {k for k in tr["profiles"] if smp["with_doi"].get(k, 0) < 0.5 * smp["papers"][k]}
C = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.expanduser("~/data-local/conf-tracker-eval/counts/*.json"))}
rows = {}
for k in sorted(tr["profiles"]):
    den = min(200, smp["papers"][k]); c = C.get(k)
    if not c: rows[k] = {"den": den, "kw": 0, "arxiv": 0, "openalex_abs": 0, "crossref": 0, "s2": 0, "arxiv_or_oa": 0, "all": 0}; continue
    v = c["variants"]; src_all = v["all"]["sources"]
    rows[k] = {"den": den, "kw": v["kw"]["n"], "arxiv": v["arxiv"]["n"], "openalex_abs": v["arxiv_oa"]["sources"].get("openalex", 0) + v["arxiv"]["n"] * 0,
               "arxiv_or_oa": v["arxiv_oa"]["n"], "crossref": src_all.get("crossref", 0), "s2": src_all.get("semantic_scholar", 0), "all": v["all"]["n"]}
def summary(keys, label):
    keys = [k for k in keys if k in rows]
    out = {"venues": len(keys)}
    for s in ("kw", "arxiv", "arxiv_or_oa", "all"):
        cov = [rows[k][s] / rows[k]["den"] if rows[k]["den"] else 0 for k in keys]
        out[s] = {"median": round(median(cov), 3), "venues >= 20 papers": sum(1 for k in keys if rows[k][s] >= 20), "venues >= 80%": sum(1 for x in cov if x >= 0.8)}
    print(label, json.dumps(out))
    return out
res = {"all_profiled": summary(rows, "all 324 venues"), "86_without_abstracts": summary(fb, "86 venues without abstracts"),
       "27_low_doi": summary(low, "27 low-DOI venues")}
res["per_venue"] = rows
for k in ("dasfaa", "dexa", "adma", "eccv", "crypto", "esa", "pakdd", "icdm", "kdd", "isit", "nips", "icml", "iclr", "vldb"):
    r = rows.get(k); print(k, {s: f"{r[s]}/{r['den']}" for s in ("kw", "arxiv", "arxiv_or_oa", "all")})
json.dump(res, open(sys.argv[1], "w"), indent=1)
