# SPDX-License-Identifier: MIT
"""Read conference papers 2020-2025 (key, year, title, doi) for ccfddl series; also venue->area map."""
import gzip, html, json, re, sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from conftracker import ccfddl
dump, zipf, out = sys.argv[2], sys.argv[3], sys.argv[4]
confs, _ = ccfddl.read_zip(open(zipf, "rb").read())
area = {}
for doc in confs:
    for it in doc:
        k = str(it.get("dblp") or "").strip()
        if k: area[k] = it.get("sub")
REC = re.compile(r'<inproceedings\b[^>]*\bkey="conf/([^/"]+)/')
TITLE = re.compile(r"<title>(.*?)</title>"); YEAR = re.compile(r"<year>(\d{4})</year>")
DOI = re.compile(r"<ee[^>]*>https?://(?:dx\.)?doi\.org/(10\.[^<\s]+)</ee>"); TAG = re.compile(r"<[^>]+>")
rows = []
key = None
with gzip.open(dump, "rt", encoding="iso-8859-1", errors="replace") as fh:
    for line in fh:
        if key is None:
            if line.startswith("<inproceedings"):
                m = REC.match(line)
                if m and m[1] in area: key, title, year, doi = m[1], None, None, None
            continue
        if title is None and "<title>" in line:
            m = TITLE.search(line)
            if m: title = html.unescape(TAG.sub("", m[1])).strip()
        elif year is None and "<year>" in line:
            m = YEAR.search(line); year = int(m[1]) if m else None
        elif doi is None and "<ee" in line:
            m = DOI.search(line); doi = html.unescape(m[1]).strip() if m else None
        if "</inproceedings>" in line:
            if title and year and 2020 <= year <= 2025: rows.append([key, year, title, doi])
            key = None
json.dump({"area": area, "rows": rows}, open(out, "w"))
print(len(rows), sum(1 for r in rows if r[1] == 2025), sum(1 for r in rows if r[1] == 2025 and r[3]))
