# SPDX-License-Identifier: MIT
"""Shared in-memory aggregation (same rules as collect.py): abstracts never leave memory; only pruned counts are returned."""
import json, os, re, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")); sys.path.insert(0, ".")
from conftracker import profiles as P
from oa_common import text
from harness import clean_abstract
ORDER = {"kw": ["openalex_keywords"], "arxiv": ["arxiv"], "arxiv_oa": ["arxiv", "openalex"], "all": ["arxiv", "openalex", "crossref", "semantic_scholar"]}
UA = {"User-Agent": "conf-tracker-evaluation/1.0"}
ARX = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$")
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
                root = ET.fromstring(urllib.request.urlopen(urllib.request.Request("https://export.arxiv.org/api/query?" + q, headers=UA), timeout=120).read())
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for e in root.findall("a:entry", ns):
                    aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1]); summ = e.findtext("a:summary", "", ns)
                    if summ and summ.strip(): out[aid] = summ
                break
            except Exception: time.sleep(5 * (a + 1))
        time.sleep(3.1)
    return out
def aggregate(k, papers, s2):
    """papers: [{id, year, doi, work}] -> pruned per-variant counts (>= 3 papers, top 500), sources per paper."""
    arx_id = {}
    for p in papers:
        for loc in p["work"].get("locations") or []:
            m = ARX.search(((loc or {}).get("landing_page_url") or "").strip())
            if m: arx_id[p["id"]] = m.group(1); break
    ax = arxiv(sorted(set(arx_id.values()))); cr = crossref(sorted({p["doi"] for p in papers if p["doi"]}))
    counts = {v: defaultdict(Counter) for v in ORDER}; n = Counter(); source_of = defaultdict(dict); n_year = defaultdict(Counter)
    for p in papers:
        w = p["work"]; y = str(p["year"])
        avail = {"openalex_keywords": " . ".join([x.get("display_name", "") for x in w.get("keywords") or []] + [x.get("display_name", "") for x in w.get("topics") or []]),
                 "arxiv": ax.get(arx_id.get(p["id"], ""), ""), "openalex": text(w.get("abstract_inverted_index")),
                 "crossref": cr.get(p["doi"], ""), "semantic_scholar": s2.get(p["doi"], "") if p["doi"] else ""}
        for v, order in ORDER.items():
            src = next((o for o in order if avail[o] and (o == "openalex_keywords" or len(clean_abstract(avail[o]).split()) >= 40)), None)
            if not src: continue
            body = avail[src] if src == "openalex_keywords" else clean_abstract(avail[src])
            for t in set(P.tokens(body)): counts[v][t][y] += 1
            n[v] += 1; source_of[v][p["id"]] = src; n_year[v][y] += 1
        del avail
    out = {"venue": k, "sample": len(papers), "openalex_records": len(papers), "arxiv_ids": len(arx_id), "variants": {}}
    for v in ORDER:
        tot = {t: sum(c.values()) for t, c in counts[v].items()}
        keep = sorted((t for t, c in tot.items() if c >= 3), key=lambda t: (-tot[t], t))[:500]
        out["variants"][v] = {"n": n[v], "terms": {t: dict(counts[v][t]) for t in keep}, "sources": dict(Counter(source_of[v].values())), "source_of": source_of[v], "n_by_year": dict(n_year[v])}
    return out
