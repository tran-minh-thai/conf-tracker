# SPDX-License-Identifier: MIT
"""Aggregated term counts behind data/venue_channels.json (data/channel_counts.json).

Per venue and channel (keywords: OpenAlex keywords and topics; arxiv: arXiv abstracts), the number
of sampled papers per year and, per kept term, the number of those papers containing it per year.
Abstract text is tokenized in memory and dropped: nothing but these counts is written. A term is kept
only if at least MIN_PAPERS_PER_TERM papers of the venue contain it, and at most MAX_TERMS terms are
kept per venue, so no single abstract can be rebuilt from the file.

Sources and terms (read 2026-11-23): OpenAlex records are CC0; the arXiv API terms put descriptive
metadata, including the abstract, under CC0 1.0.
"""
from __future__ import annotations

import gzip
import html
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from .profiles import tokens, withheld

MIN_PAPERS_PER_TERM = 3
MAX_TERMS = 500
SAMPLE_PER_YEAR = 40
USER_AGENT = "conf-tracker (+https://github.com/tran-minh-thai/conf-tracker)"
CHANNEL_NAMES = ("keywords", "arxiv")
_TAG = re.compile(r"<[^>]+>")
_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$")
_NORM = re.compile(r"[^a-z0-9]+")


def norm_title(t: str) -> str:
    return _NORM.sub(" ", (t or "").lower()).strip()


def clean_abstract(text: str) -> str:
    text = html.unescape(_TAG.sub(" ", text or ""))
    text = re.sub(r"^\s*(abstract|summary)\b[:.]?\s*", "", text.strip(), flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


# ---- DBLP --------------------------------------------------------------------

_REC = re.compile(r'<inproceedings\b[^>]*\bkey="conf/([^/"]+)/')
_TITLE = re.compile(r"<title>(.*?)</title>")
_YEAR = re.compile(r"<year>(\d{4})</year>")
_DOI = re.compile(r"<ee[^>]*>https?://(?:dx\.)?doi\.org/(10\.[^<\s]+)</ee>")


def read_dump(path, keys: set, years: range):
    """Yield (key, year, title, doi or None) for conference papers of the wanted series."""
    key = None
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="iso-8859-1", errors="replace") as fh:
        for line in fh:
            if key is None:
                if line.startswith("<inproceedings"):
                    m = _REC.match(line)
                    if m and m[1] in keys:
                        key, title, year, doi = m[1], None, None, None
                continue
            if title is None and "<title>" in line:
                m = _TITLE.search(line)
                if m:
                    title = html.unescape(_TAG.sub("", m[1])).strip()
            elif year is None and "<year>" in line:
                m = _YEAR.search(line)
                year = int(m[1]) if m else None
            elif doi is None and "<ee" in line:
                m = _DOI.search(line)
                doi = html.unescape(m[1]).strip().lower() if m else None
            if "</inproceedings>" in line:
                if title and year in years:
                    yield key, year, title, doi
                key = None


# ---- OpenAlex and arXiv -------------------------------------------------------

class OpenAlex:
    """OpenAlex client. The key comes from OPENALEX_API_KEY or ~/.config/openalex/api_key and is never printed."""

    def __init__(self):
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        path = os.path.expanduser("~/.config/openalex/api_key")
        if not key and os.path.exists(path):
            key = open(path).read().strip()
        self._key = key
        self.remaining = None

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def get(self, path: str, params: dict):
        url = "https://api.openalex.org/" + path + "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": USER_AGENT}
        if self._key:
            headers["Authorization"] = "Bearer " + self._key
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as r:
                    self.remaining = r.headers.get("X-RateLimit-Remaining")
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403, 404):
                    raise RuntimeError(f"OpenAlex answered HTTP {e.code} for /{path}") from None
                time.sleep(3 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"OpenAlex did not answer /{path} after 6 attempts")


def openalex_text(inverted: dict) -> str:
    pos = [(i, w) for w, ii in (inverted or {}).items() for i in ii]
    return " ".join(w for _, w in sorted(pos))


def arxiv_abstracts(ids: list) -> dict:
    """arXiv id -> abstract, by the export API (100 ids a request, 3 s apart as arXiv asks). Kept in memory."""
    out = {}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for i in range(0, len(ids), 100):
        q = urllib.parse.urlencode({"id_list": ",".join(ids[i:i + 100]), "max_results": 100})
        for attempt in range(4):
            try:
                req = urllib.request.Request("https://export.arxiv.org/api/query?" + q, headers={"User-Agent": USER_AGENT})
                root = ET.fromstring(urllib.request.urlopen(req, timeout=120).read())
                for e in root.findall("a:entry", ns):
                    aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1])
                    summary = e.findtext("a:summary", "", ns)
                    if summary and summary.strip():
                        out[aid] = summary
                break
            except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError):
                time.sleep(5 * (attempt + 1))
        time.sleep(3.1)
    return out


# ---- aggregation ----------------------------------------------------------------

def aggregate(works: list) -> dict:
    """works: [(year, OpenAlex work)] -> {channel: {"n_by_year": {y: n}, "terms": {t: {y: c}}}} before pruning.

    keywords: names of the work's OpenAlex keywords and topics; arxiv: its arXiv abstract (>= 40 words).
    """
    arx = {}
    for i, (_y, w) in enumerate(works):
        for loc in w.get("locations") or []:
            m = _ARXIV.search(((loc or {}).get("landing_page_url") or "").strip())
            if m:
                arx[i] = m.group(1)
                break
    abstracts = arxiv_abstracts(sorted(set(arx.values())))
    out = {c: {"n_by_year": Counter(), "terms": defaultdict(Counter)} for c in CHANNEL_NAMES}
    for i, (y, w) in enumerate(works):
        y = str(y)
        kw = " . ".join([x.get("display_name", "") for x in w.get("keywords") or []]
                        + [x.get("display_name", "") for x in w.get("topics") or []])
        if kw.strip():
            out["keywords"]["n_by_year"][y] += 1
            for t in set(tokens(kw)):
                out["keywords"]["terms"][t][y] += 1
        text = clean_abstract(abstracts.get(arx.get(i, ""), ""))
        if len(text.split()) >= 40:
            out["arxiv"]["n_by_year"][y] += 1
            for t in set(tokens(text)):
                out["arxiv"]["terms"][t][y] += 1
        del text
    return out


def prune(channel: dict) -> dict:
    """Keep terms in >= MIN_PAPERS_PER_TERM papers, top MAX_TERMS by papers (ties by term)."""
    # withheld terms (see profiles.WITHHELD_SHA256) never enter the published counts or channels
    tot = {t: sum(ys.values()) for t, ys in channel["terms"].items() if not withheld(t)}
    keep = sorted((t for t, c in tot.items() if c >= MIN_PAPERS_PER_TERM), key=lambda t: (-tot[t], t))[:MAX_TERMS]
    return {"n_by_year": {y: n for y, n in sorted(channel["n_by_year"].items()) if n},
            "terms": {t: {y: c for y, c in sorted(channel["terms"][t].items()) if c} for t in keep}}


def merge(old: dict, new: dict) -> dict:
    """Add a new year's counts to a venue channel; a term not yet kept enters only with >= 3 papers in the new year."""
    terms = {t: dict(ys) for t, ys in old.get("terms", {}).items()}
    for t, ys in new["terms"].items():
        if t in terms or sum(ys.values()) >= MIN_PAPERS_PER_TERM:
            for y, c in ys.items():
                terms.setdefault(t, {})[y] = terms.get(t, {}).get(y, 0) + c
    n = dict(old.get("n_by_year", {}))
    for y, c in new["n_by_year"].items():
        n[y] = n.get(y, 0) + c
    return prune({"n_by_year": Counter(n), "terms": {t: Counter(ys) for t, ys in terms.items()}})


def drop_years(channel: dict, keep_from: int) -> dict:
    n = Counter({y: c for y, c in channel["n_by_year"].items() if int(y) >= keep_from})
    terms = {t: Counter({y: c for y, c in ys.items() if int(y) >= keep_from}) for t, ys in channel["terms"].items()}
    return prune({"n_by_year": n, "terms": terms})


def to_counts(channel: dict):
    """Committed channel -> (n_papers, {term: {year: papers}}) as conftracker.channels.build_channel expects."""
    return sum(channel["n_by_year"].values()), channel["terms"]


def sample(items: list, seed: str, n: int) -> list:
    items = sorted(items)
    random.Random(seed).shuffle(items)
    return items[:n]


def works_by_doi(oa: OpenAlex, dois: list) -> dict:
    sel = "doi,keywords,topics,locations"
    out = {}
    for i in range(0, len(dois), 50):
        r = oa.get("works", {"filter": "doi:" + "|".join(dois[i:i + 50]), "select": sel, "per-page": 50})
        for w in r["results"]:
            if w.get("doi"):
                out[w["doi"].lower().replace("https://doi.org/", "")] = w
    return out


def works_by_source(oa: OpenAlex, source_ids: list, year: int, titles: dict) -> dict:
    """Works of the venue's OpenAlex sources in a year whose normalised title equals a DBLP title of the venue."""
    sel = "title,doi,keywords,topics,locations"
    found = {}
    for sid in source_ids:
        cursor = "*"
        for _ in range(25):
            r = oa.get("works", {"filter": f"locations.source.id:{sid.split('/')[-1]},publication_year:{year}",
                                 "select": sel, "per-page": 200, "cursor": cursor})
            for w in r["results"]:
                n = norm_title(w.get("title"))
                if n in titles and n not in found:
                    found[n] = w
            cursor = r["meta"].get("next_cursor")
            if not cursor or not r["results"]:
                break
    return found
