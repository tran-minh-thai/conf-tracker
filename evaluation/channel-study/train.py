# SPDX-License-Identifier: MIT
"""Build held-out profiles (2020-2024 titles) exactly as build_profiles.py does, cache to train.json."""
import json, sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from conftracker import profiles as P
S = sys.argv[2]
d = json.load(open(f"{S}/papers.json"))
train = P.group_titles((k, y, t) for k, y, t, _ in d["rows"] if 2020 <= y <= 2024)
prof, idf = P.build_profiles(train)
used = {t for p in prof.values() for t in p["terms"]}
idf = {t: round(v, 3) for t, v in idf.items() if t in used}
json.dump({"profiles": prof, "idf": idf, "area": d["area"]}, open(f"{S}/train.json", "w"))
print(len(prof), len(idf))
