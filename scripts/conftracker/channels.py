# SPDX-License-Identifier: MIT
"""Venue ranking channels for "find venues for a paper" (data/venue_channels.json).

Three channels, each a set of per-venue term weights built from aggregated counts only:
  titles   - DBLP paper titles (CC0), cosine weights (share x idf, top 120, L2), recency 0.85;
  keywords - OpenAlex keywords and topics of the venue's papers (CC0), BM25 (k1 2.0, b 1.0), recency 0.7;
  arxiv    - terms of the arXiv abstracts of the venue's papers (CC0), cosine weights, recency 0.85.
A paper's text is scored in each channel, each channel's scores are divided by that query's best
score, and the results are summed with weights 1, 1 and 0.25. The settings were chosen on a
validation half of held-out 2025 abstracts and checked once on the other half
(evaluation/channel-ranking-*.json). Mirrored in assets/match.js and the iOS ConfCore package;
tests/fixtures/channel_cases.json keeps the three in step.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .profiles import term_specificity, tokens, withheld

CHANNELS = {
    "titles": {"method": "cosine", "recency": 0.85, "phrase": 1.0, "top_k": 120},
    "keywords": {"method": "bm25", "k1": 2.0, "b": 1.0, "recency": 0.7, "phrase": 1.5},
    "arxiv": {"method": "cosine", "recency": 0.85, "phrase": 1.0, "top_k": 120},
}
WEIGHTS = {"titles": 1.0, "keywords": 1.0, "arxiv": 0.25}
ORDER = ["titles", "keywords", "arxiv"]  # summing order, the same in every client
MIN_PAPERS = 20  # a venue needs this many papers in a non-title channel to get a vector in it
ROUND = 6


def build_channel(counts: dict, spec: dict, n_venues: int, end_year: int, drop_withheld: bool = True) -> dict:
    """counts: {venue: (n_papers, {term: {year: papers}})} -> {"query_weight": {term: w}, "venues": {venue: {term: w}}}.

    n_venues is the number of venues ranked (title-profiled venues), used in idf for every channel.
    """
    r = spec["recency"]
    tf = {}
    for k, (_n, terms) in counts.items():
        tf[k] = {t: sum(c * r ** (end_year - int(y)) for y, c in sorted(ys.items()))
                 for t, ys in terms.items() if not (drop_withheld and withheld(t))}
    big_n = n_venues + 1
    df = Counter(t for k in tf for t in tf[k])
    spec_t = term_specificity({t: 1 for t in terms} for terms in tf.values())
    venues = {}
    if spec["method"] == "cosine":
        idf = {t: math.log((big_n + 1) / (x + 1)) + 1 for t, x in df.items()}
        for k, terms in tf.items():
            n = counts[k][0]
            w = sorted(((t, c / n * idf[t]) for t, c in terms.items()), key=lambda x: (-x[1], x[0]))[:spec["top_k"]]
            norm = math.sqrt(sum(x * x for _, x in w)) or 1.0
            venues[k] = {t: round(x / norm, ROUND) for t, x in w}
        used = {t for v in venues.values() for t in v}
        query_weight = {t: round(spec_t[t] ** 0.5 * idf[t], ROUND) for t in sorted(used)}
    else:
        idf = {t: math.log(1 + (big_n - x + 0.5) / (x + 0.5)) for t, x in df.items()}
        length = {k: sum(terms.values()) for k, terms in tf.items()}
        avg = sum(length.values()) / max(1, len(length))
        k1, b = spec["k1"], spec["b"]
        for k, terms in tf.items():
            norm = k1 * (1 - b + b * length[k] / avg)
            venues[k] = {t: round(idf[t] * c * (k1 + 1) / (c + norm), ROUND) for t, c in sorted(terms.items())}
        used = {t for v in venues.values() for t in v}
        query_weight = {t: round(spec_t[t] ** 0.5, ROUND) for t in sorted(used)}
    return {"query_weight": query_weight, "venues": dict(sorted(venues.items()))}


def _query(text: str, channel: dict, phrase: float) -> dict:
    qw = channel["query_weight"]
    c = Counter(t for t in tokens(text) if t in qw)
    return {t: (1 + math.log(x)) * qw[t] * (phrase if "_" in t else 1.0) for t, x in c.items()}


_INDEX: dict = {}  # id(venues) -> (venues, inverted index); nothing is stored in the channel data itself


def _inverted(channel: dict) -> dict:
    venues = channel["venues"]
    hit = _INDEX.get(id(venues))
    if hit is not None and hit[0] is venues:
        return hit[1]
    inv = defaultdict(list)
    for k, terms in venues.items():
        for t, w in terms.items():
            inv[t].append((k, w))
    _INDEX[id(venues)] = (venues, inv)
    return inv


def channel_scores(text: str, channel: dict, phrase: float) -> dict:
    q = _query(text, channel, phrase)
    inv = _inverted(channel)
    sc = defaultdict(float)
    for t, w in q.items():
        for k, x in inv.get(t, ()):
            sc[k] += w * x
    return dict(sc)


def fused_scores(text: str, data: dict) -> dict:
    """Weighted sum of per-channel scores, each divided by the query's best score in that channel."""
    out = defaultdict(float)
    for name in data["fusion"]["order"]:
        weight = data["fusion"]["weights"].get(name, 0.0)
        ch = data["channels"][name]
        sc = channel_scores(text, ch, ch["phrase"])
        top = max(sc.values(), default=0.0)
        if top <= 0 or weight == 0:
            continue
        for k, v in sc.items():
            out[k] += weight * v / top
    return dict(out)


def shared_terms(text: str, data: dict, venue: str, n: int = 5) -> list:
    """Terms that contribute most to the venue's fused score, for the explanation shown with each result."""
    contrib = defaultdict(float)
    for name in data["fusion"]["order"]:
        weight = data["fusion"]["weights"].get(name, 0.0)
        ch = data["channels"][name]
        q = _query(text, ch, ch["phrase"])
        sc = channel_scores(text, ch, ch["phrase"])
        top = max(sc.values(), default=0.0)
        terms = ch["venues"].get(venue)
        if top <= 0 or not terms:
            continue
        for t, w in q.items():
            if t in terms:
                contrib[t] += weight * w * terms[t] / top
    ranked = sorted(contrib.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [t.replace("_", " ") for t, _ in ranked]
