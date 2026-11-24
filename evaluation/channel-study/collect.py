# SPDX-License-Identifier: MIT
"""Per-venue aggregated term counts, no abstract text written anywhere.

For each venue (one at a time, resumable at venue granularity) and each paper of its seeded 2020-2024 sample:
  OpenAlex record by DOI: keywords + topics names, arXiv id (from locations), abstract index;
  arXiv abstract by id (export.arxiv.org API, 3 s between requests);
  comparison only: Crossref abstract (by DOI), Semantic Scholar abstract (existing cache).
Per paper one abstract per variant, first source in a fixed order. Abstracts are tokenized in memory and dropped.
Kept per venue and variant: n papers, per term per year the number of papers containing it, only terms in >= 3
papers of the venue, top 500 by paper count. Also per paper the source used (identifiers only).
Variants: kw = OpenAlex keywords+topics; arxiv = arXiv abstracts; arxiv_oa = arXiv then OpenAlex abstracts;
all = arXiv, OpenAlex, Crossref, Semantic Scholar (comparison only)."""
import json, os, re, sys, time, random, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")); sys.path.insert(0, ".")
from conftracker import profiles as P
from oa_common import get, text, STATE
from harness import clean_abstract
OUT = os.path.expanduser("~/data-local/conf-tracker-eval/counts"); os.makedirs(OUT, exist_ok=True)
ORDER = {"kw": ["openalex_keywords"], "arxiv": ["arxiv"], "arxiv_oa": ["arxiv", "openalex"], "all": ["arxiv", "openalex", "crossref", "semantic_scholar"]}
d = json.load(open("papers.json")); s2 = json.load(open(os.path.expanduser("~/data-local/conf-tracker-eval/s2_abstracts_train.json")))
sample = defaultdict(list); year_of = {}
for k, y, t, doi in d["rows"]:
    if 2020 <= y <= 2024 and doi: sample[k].append(doi.lower()); year_of[doi.lower()] = y
fallback = set(json.load(open("record025.json"))["fallback"][2])
tr_ = json.load(open("train.json")); smp_ = json.load(open("train_sample.json"))
LOW = {k for k in tr_["profiles"] if smp_["with_doi"].get(k, 0) < 0.5 * smp_["papers"][k]}  # filled by collect_low.py
venues = sorted((k for k in sample if k not in LOW), key=lambda k: (k not in fallback, k))
budget_floor = int(sys.argv[1]) if len(sys.argv) > 1 else 40
UA = {"User-Agent": "conf-tracker-evaluation/1.0"}
def crossref(dois):
    out = {}
    for i in range(0, len(dois), 40):
        q = urllib.parse.urlencode({"filter": ",".join(f"doi:{x}" for x in dois[i:i + 40]), "select": "DOI,abstract", "rows": 100})
        try:
            items = json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.crossref.org/works?{q}", headers=UA), timeout=60))["message"]["items"]
            out.update({it["DOI"].lower(): it.get("abstract", "") for it in items if it.get("abstract")})
        except Exception: pass
        time.sleep(0.3)
    return out
def arxiv(ids):
    out = {}
    for i in range(0, len(ids), 100):
        q = urllib.parse.urlencode({"id_list": ",".join(ids[i:i + 100]), "max_results": 100})
        for a in range(4):
            try:
                root = ET.fromstring(urllib.request.urlopen(urllib.request.Request("http://export.arxiv.org/api/query?" + q, headers=UA), timeout=90).read())
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for e in root.findall("a:entry", ns):
                    aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1])
                    summ = e.findtext("a:summary", "", ns)
                    if summ and summ.strip(): out[aid] = summ
                break
            except Exception: time.sleep(5 * (a + 1))
        time.sleep(3.1)
    return out
ARX = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$")
done = {f[:-5] for f in os.listdir(OUT) if f.endswith(".json")}
for k in venues:
    if k in done: continue
    ds = sorted(set(sample[k])); random.Random(k).shuffle(ds); ds = ds[:200]
    if STATE["remaining"] is not None and int(STATE["remaining"]) < budget_floor + 4:
        print("stopping before", k, "OpenAlex requests left", STATE["remaining"], flush=True); break
    rec, failed = {}, 0
    for i in range(0, len(ds), 50):
        r = get("works", {"filter": "doi:" + "|".join(ds[i:i + 50]), "select": "doi,keywords,topics,locations,abstract_inverted_index", "per-page": 50})
        if r is None: failed += 1; continue
        for w in r["results"]:
            if w.get("doi"): rec[w["doi"].lower().replace("https://doi.org/", "")] = w
    if failed:
        print("venue", k, "OpenAlex batches failed", failed, "- not saved, will retry", flush=True)
        if STATE["remaining"] == "0": break
        continue
    arx_id = {}
    for doi, w in rec.items():
        for loc in w.get("locations") or []:
            m = ARX.search(((loc or {}).get("landing_page_url") or "").strip())
            if m: arx_id[doi] = m.group(1); break
    ax = arxiv(sorted(set(arx_id.values())))
    cr = crossref(ds)
    counts = {v: defaultdict(Counter) for v in ORDER}; n = Counter(); source_of = defaultdict(dict)
    for doi in ds:
        w = rec.get(doi, {}); y = str(year_of[doi])
        avail = {"openalex_keywords": " . ".join([x.get("display_name", "") for x in w.get("keywords") or []] + [x.get("display_name", "") for x in w.get("topics") or []]),
                 "arxiv": ax.get(arx_id.get(doi, ""), ""), "openalex": text(w.get("abstract_inverted_index")),
                 "crossref": cr.get(doi, ""), "semantic_scholar": s2.get(doi, "")}
        for v, order in ORDER.items():
            src = next((o for o in order if avail[o] and (o == "openalex_keywords" or len(clean_abstract(avail[o]).split()) >= 40)), None)
            if not src: continue
            body = avail[src] if src == "openalex_keywords" else clean_abstract(avail[src])
            for t in set(P.tokens(body)): counts[v][t][y] += 1
            n[v] += 1; source_of[v][doi] = src
        del avail
    out = {"venue": k, "sample": len(ds), "openalex_records": len(rec), "arxiv_ids": len(arx_id), "variants": {}}
    for v in ORDER:
        tot = {t: sum(c.values()) for t, c in counts[v].items()}
        keep = sorted((t for t, c in tot.items() if c >= 3), key=lambda t: (-tot[t], t))[:500]
        out["variants"][v] = {"n": n[v], "terms": {t: dict(counts[v][t]) for t in keep},
                              "sources": dict(Counter(source_of[v].values())), "source_of": source_of[v]}
    del counts
    json.dump(out, open(os.path.join(OUT, k + ".json"), "w"))
    print(k, "sample", len(ds), "openalex", len(rec), "arxiv", len(ax), {v: out["variants"][v]["n"] for v in ORDER},
          "OpenAlex requests left", STATE["remaining"], flush=True)
print("finished pass; venues saved", len(os.listdir(OUT)), "of", len(venues), flush=True)
