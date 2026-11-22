# SPDX-License-Identifier: MIT
"""Topic profiles of venues built from the titles they published (DBLP dump).

A profile is a sparse TF-IDF vector over title terms (unigrams and bigrams).
The browser scores a researcher's interests or a paper abstract against these
vectors with the same tokenizer (assets/match.js), so both sides must agree:
tests/fixtures/tokenize_cases.json is checked by the Python and the JS tests.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import math
import re
import unicodedata
from collections import Counter, defaultdict

TOKENIZER_VERSION = 2  # 2: "-ses" plurals other than "-sses" lose only the "s"

STOPWORDS = sorted(set("""
a about above across after again against all almost along also although among an and another any are as at
based be because been before being between both but by can could do does done due during each either
else etc every for from further had has have having here how however if in into is it its itself just
less many may more most much must near new no nor not novel of off often on once only or other our out
over own paper per propose proposed rather same several should since so some such than that the their them
then there these they this those through thus to too toward towards under until up upon us use used using
very via was we well were what when where whether which while who whose why will with within without would
yet towards approach approaches method methods study analysis results show towards efficient effective
problem problems system systems framework model models data based new towards case improving improved
""".split()))
STOP = set(STOPWORDS)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _fold(text: str) -> str:
    # U+0111 (d with stroke) has no NFKD decomposition, so it is mapped by hand (mirrored in match.js).
    text = unicodedata.normalize("NFKD", (text or "").replace("\u0111", "d").replace("\u0110", "D"))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def stem(tok: str) -> str:
    """A deliberately small plural stemmer, mirrored in assets/match.js."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    # "processes" -> "process", "boxes" -> "box"; but "databases" -> "database" (the
    # generic -s rule below), so singular and plural forms meet.
    if len(tok) > 4 and re.search(r"(ss|x|ch|sh)es$", tok):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


def tokens(text: str) -> list[str]:
    """Unigrams and adjacent bigrams ("graph_neural") after stopword removal."""
    words = [w for w in _NON_ALNUM.split(_fold(text)) if w]
    kept = []
    for w in words:
        if len(w) < 2 or w.isdigit() or w in STOP:
            kept.append(None)  # a stopword breaks bigrams
            continue
        kept.append(stem(w))
    out = [w for w in kept if w]
    out += [f"{a}_{b}" for a, b in zip(kept, kept[1:]) if a and b]
    return out


# ---- DBLP dump -----------------------------------------------------------------

REC_START = re.compile(r'<inproceedings\b[^>]*\bkey="conf/([^/"]+)/')
TITLE = re.compile(r"<title>(.*?)</title>")
YEAR = re.compile(r"<year>(\d{4})</year>")
TAG = re.compile(r"<[^>]+>")


def iter_dump(path, keys: set, years: range):
    """Yield (dblp_key, year, title) for conference papers of the wanted keys.

    dblp.xml is line oriented: one field per line, records closed by
    </inproceedings>. Entities are HTML entity names, so html.unescape works.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    key = title = year = None
    with opener(path, "rt", encoding="iso-8859-1", errors="replace") as fh:
        for line in fh:
            if key is None:
                if line.startswith("<inproceedings"):
                    m = REC_START.match(line)
                    if m and m[1] in keys:
                        key, title, year = m[1], None, None
                continue
            if title is None and "<title>" in line:
                m = TITLE.search(line)
                if m:
                    title = html.unescape(TAG.sub("", m[1])).strip()
            elif year is None and "<year>" in line:
                m = YEAR.search(line)
                if m:
                    year = int(m[1])
            if "</inproceedings>" in line:
                if title and year in years:
                    yield key, year, title
                key = None


ART_START = re.compile(r'<article\b[^>]*\bkey="journals/([^/"]+)/')
JOURNAL = re.compile(r"<journal>(.*?)</journal>")
DOI_EE = re.compile(r"<ee[^>]*>https?://(?:dx\.)?doi\.org/(10\.[^<\s]+)</ee>")
# Preprint servers and informal series are not peer-reviewed journals.
NOT_JOURNALS = {"corr", "ercim", "dagstuhl-reports", "dagstuhl-manifestos", "sigmod-record-nonref"}


def iter_journal_dump(path, years: range, with_doi: bool = False):
    """Yield (journal_key, year, title, journal_name[, doi]) for journal articles."""
    opener = gzip.open if str(path).endswith(".gz") else open
    key = title = year = name = doi = None
    with opener(path, "rt", encoding="iso-8859-1", errors="replace") as fh:
        for line in fh:
            if key is None:
                if line.startswith("<article"):
                    m = ART_START.match(line)
                    if m and m[1] not in NOT_JOURNALS:
                        key, title, year, name, doi = m[1], None, None, None, None
                continue
            if title is None and "<title>" in line:
                m = TITLE.search(line)
                if m:
                    title = html.unescape(TAG.sub("", m[1])).strip()
            elif year is None and "<year>" in line:
                m = YEAR.search(line)
                if m:
                    year = int(m[1])
            elif name is None and "<journal>" in line:
                m = JOURNAL.search(line)
                if m:
                    name = html.unescape(m[1]).strip()
            elif doi is None and "<ee" in line:
                m = DOI_EE.search(line)
                if m:
                    doi = html.unescape(m[1]).strip()
            if "</article>" in line:
                if title and year in years:
                    yield (key, year, title, name or key, doi) if with_doi else (key, year, title, name or key)
                key = None


# ---- TF-IDF profiles -----------------------------------------------------------

# Terms withheld from the published vocabularies at the maintainers' request (they
# collide with the repository's publishing filter). Stored as SHA-256 digests of the
# single words so the source holds no copy of them. Measured effect on the held-out
# evaluation: none for conferences, under 0.0001 recall for journals.
WITHHELD_SHA256 = frozenset({
    "a39a7ffad4a3013f29da97b84f264337f234c1cf9b3c40c7c30c677a8a18609a",
    "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131",
    "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d",
    "eea82f53ecaed277e542e8a867863be69c50efc4b94dad1f50a33944ca0c2f1f",
})


def withheld(term: str, digests=WITHHELD_SHA256) -> bool:
    """True when any word of a (possibly bigram) term is withheld."""
    return any(hashlib.sha256(part.encode()).hexdigest() in digests for part in term.split("_"))


def build_profiles(titles_by_key: dict, top_k: int = 120, min_titles: int = 30):
    """Return (profiles, idf). profiles: key -> {terms: {term: weight}, n_titles}.

    tf(term, venue) = share of the venue's titles containing the term;
    idf(term) = ln((N + 1) / (df + 1)) + 1 with df counted over venues.
    Weights are L2-normalised after keeping the top_k terms.
    """
    doc_freq_in_venue = {}
    for key, titles in titles_by_key.items():
        if len(titles) < min_titles:
            continue
        c = Counter()
        for t in titles:
            c.update(set(tokens(t)))
        doc_freq_in_venue[key] = (c, len(titles))
    n = len(doc_freq_in_venue)
    df = Counter()
    for c, _ in doc_freq_in_venue.values():
        df.update(c.keys())
    idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
    profiles = {}
    for key, (c, n_titles) in doc_freq_in_venue.items():
        weights = {t: (cnt / n_titles) * idf[t] for t, cnt in c.items() if cnt >= 2 and not withheld(t)}
        top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
        norm = math.sqrt(sum(w * w for _, w in top)) or 1.0
        profiles[key] = {"terms": {t: round(w / norm, 5) for t, w in top}, "n_titles": n_titles}
    return profiles, idf


def query_vector(text: str, idf: dict) -> dict:
    """Sublinear tf times idf, L2-normalised; terms unknown to the profiles are dropped."""
    c = Counter(t for t in tokens(text) if t in idf)
    vec = {t: (1 + math.log(k)) * idf[t] for t, k in c.items()}
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {t: w / norm for t, w in vec.items()}


def score(qvec: dict, profile_terms: dict) -> float:
    return sum(w * profile_terms.get(t, 0.0) for t, w in qvec.items())


def rank(text: str, profiles: dict, idf: dict):
    q = query_vector(text, idf)
    return sorted(((score(q, p["terms"]), k) for k, p in profiles.items()), key=lambda x: (-x[0], x[1]))


def evaluate(train: dict, test: dict, names: dict, per_venue: int = 30, ks=(1, 5, 10)):
    """Held-out evaluation: profiles from earlier years, queries are later titles.

    Reports recall@k and MRR for the title profiles and for a baseline that
    profiles each venue by its full name only (what a name-based matcher sees).
    """
    profiles, idf = build_profiles(train)
    name_profiles, name_idf = build_profiles({k: [names.get(k, k)] * 30 for k in profiles}, min_titles=1)
    queries = []
    for key in sorted(profiles):
        titles = sorted(test.get(key, []))
        if len(titles) < 10:
            continue
        step = max(1, len(titles) // per_venue)
        queries += [(key, t) for t in titles[::step][:per_venue]]

    def run(prof, idf_):
        hits = {k: 0 for k in ks}
        rr = 0.0
        for key, title in queries:
            order = [k for _, k in rank(title, prof, idf_)]
            pos = order.index(key) + 1 if key in order else len(order) + 1
            rr += 1 / pos
            for k in ks:
                hits[k] += pos <= k
        m = len(queries) or 1
        return {**{f"recall@{k}": round(hits[k] / m, 4) for k in ks}, "mrr": round(rr / m, 4)}

    venues = len({k for k, _ in queries})
    return {
        "venues_ranked": len(profiles),
        "venues_queried": venues,
        "queries": len(queries),
        "title_profiles": run(profiles, idf),
        "name_only_baseline": run(name_profiles, name_idf),
        "random_baseline": {f"recall@{k}": round(k / max(1, len(profiles)), 4) for k in ks},
    }


def group_titles(records):
    out = defaultdict(list)
    for key, _year, title in records:
        out[key].append(title)
    return out
