# SPDX-License-Identifier: MIT
"""Probe: the driver's current-matcher matrix and numpy ranks must reproduce the known odd-half MRR 0.2913,
and numpy ranks must equal rank_study.rank_of on a sample (tie rule included)."""
import sys, numpy as np
sys.path.insert(0, ".")
src = open("rank_run.py").read()
head = src[:src.index("ch = R.channel_counts()")] + src[src.index("# current shipped matcher"):src.index("res = {")]
exec(head)
r = ranks(current_matrix(test), test)
print("current, odd half: queries", len(test), "MRR", round(mrr(r), 4), "(expected 0.2913)")
M = current_matrix(test[:200]); rn = ranks(M, test[:200])
ref = [R.rank_of({VENUES[j]: M[i, j] for j in range(NV) if M[i, j] > 0}, k) for i, (k, _) in enumerate(test[:200])]
print("numpy vs reference ranks, 200 queries: disagreements", int(sum(a != b for a, b in zip(rn, ref))))
M2 = M.copy(); M2[:, :] = 1.0
print("all-tied matrix: rank of venue index 0 =", int(ranks(M2[:1], [(VENUES[0], "")])[0]), "and of last venue =", int(ranks(M2[:1], [(VENUES[-1], "")])[0]))
