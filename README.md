# conf-tMtTracker

Calls for papers in computer science, built for researchers deciding where to
submit: deadlines in the venue's own time zone and yours, CCF and CORE ranks,
acceptance-rate history, a personal submission plan, calendar export, and venue
suggestions matched to your research interests or a paper abstract.

Live site: <https://tran-minh-thai.github.io/conf-tracker/>

## Features

- **Open calls by default.** Only venues whose paper deadline is still ahead are
  listed; recently closed calls, estimated deadlines and journal calls are one
  click away.
- **Deadlines you can trust.** Every date is shown in the zone the venue states
  (AoE, UTC offsets, Pacific time with daylight saving) and in your local time.
  Venues with no stated zone are flagged.
- **Estimated next deadlines** for series whose next call is not out yet, taken
  from last year's call and clearly marked.
- **Ranks and acceptance rates** from ccfddl (CCF, CORE), with the history of
  recent acceptance rates and a link to the venue's DBLP page.
- **Where:** your country is inferred from the browser time zone (no permission,
  no network); an optional precise location is matched to the nearest city on
  your device. Filter by *in my country* or *abroad*, by country and city, by
  attendance mode, and by international or national-level conference.
- **Summary per venue:** dates, place and registration fees (fees only where a
  hand-checked entry exists, with its source page and check date).
- **For you:** describe your research interests or paste an abstract, and venues
  are ranked by topical similarity to the titles they published. With your
  permission the app also learns from searches, opened and tracked venues. All of
  it runs in your browser; nothing is sent anywhere and no account is needed.
- **Publications & points:** add your papers by DOI, link or title (looked up on
  Crossref), keep the facts each rule needs (Web of Science index, impact factor,
  Scopus quartile, CORE rank, ISBN...) with the source of every fact, and get the
  state council points and your university's bonus for each paper, with the rule
  that produced it and the facts that could still raise it. Totals per calendar or
  school year, CSV export, backup and restore.
- **Your institution's documents, not ours:** points lists and bonus rules are rule
  files that each user loads for their own field, university and year. The
  repository ships two samples to start from (`data/rules/`), never applied
  automatically. A domestic journal list can be replaced by pasting the table from
  the official document; a Scimago CSV that the user downloads fills Scopus
  quartiles by ISSN.
- **Journal finder:** paste an abstract and main contributions to rank journals by
  topical similarity to what they published, with full titles and ISSNs, and an
  estimate of points and bonus under your rule files when a quartile is known.
- **My plan:** track venues with a status (considering, writing, submitted, under
  review, accepted, rejected), notes and a working title; export to a calendar
  or back up and restore as JSON.
- **Calendar:** a month view of deadlines, `.ics` export with reminders 7 days
  and 1 day ahead, and a subscribable feed of ranked deadlines:
  `https://tran-minh-thai.github.io/conf-tracker/data/deadlines.ics`.
- Shareable filter links, CSV export, English and Vietnamese interface, light and
  dark themes, phone layout.

## Data sources

| source | what | licence |
|---|---|---|
| [ccfddl/ccf-deadlines](https://github.com/ccfddl/ccf-deadlines) | curated deadlines, ranks, acceptance rates, DBLP keys | MIT |
| [WikiCFP](http://www.wikicfp.com) | additional open calls (unranked unless matched to a ccfddl series) | CC BY-SA 3.0 |
| `data/curated/` | hand-checked venues (e.g. conferences in Vietnam) and fees | this repository |
| [DBLP](https://dblp.org) bulk dump | paper titles used to build conference and journal topic profiles | CC0 |
| [Crossref](https://www.crossref.org) | journal full titles and ISSNs (build time); publication metadata by DOI (in the browser, on request) | facts, CC0 |

Deadlines change. Always confirm on the venue's website before submitting.

## How venue matching works

`scripts/build_profiles.py` reads five years of conference paper titles from the
DBLP dump for every ccfddl series and builds a TF-IDF profile (unigrams and
bigrams, top 120 terms). The browser scores your interests, activity or abstract
against these profiles by cosine similarity (`assets/match.js`, the same
tokenizer as the Python side; `tests/fixtures/tokenize_cases.json` keeps them in
step). Venues without DBLP titles fall back to their name and keywords, and the
interface says so.

Each profile build also runs a held-out evaluation: profiles from the five years
before the latest year, queried with that latest year's titles. Results, with the
command and file hashes that produced them, are written to `evaluation/`.

## Rule files

A rule file is JSON that transcribes one official document. Conditions are data
(`{"all": [...]}`, `{"any": [...]}`, `{"not": ...}`, `{"fact": "impact_factor", "gte": 3}`),
never code, so a file from anyone can be loaded safely. Each file names its source
document, lists the places where the document can be read two ways, and may hold a
journal list whose points change with the publication year
(`[{"from": null, "max": 0.5}, {"from": 2019, "max": 0.75}]`). The engine
(`assets/rules.js`) evaluates every rule, applies the highest value, explains which
rule matched, and treats a missing fact as unknown, never as met. The points result
feeds the bonus file as the fact `hdgsnn_max`, because bonus rules may refer to it.

Journal matching evaluation, built the same way as for conferences (2020-2024
profiles, 2025 titles as queries, 1089 journals ranked): recall@10 0.357 against
0.065 for name-only profiles and 0.009 at random; see `evaluation/`.

## Repository layout

```
index.html, assets/        static web app (no build step)
data/conferences.json      venue editions (schema version 2), rebuilt daily
data/deadlines.ics         subscribable feed of ranked deadlines
data/venue_profiles.json   conference topic profiles, rebuilt monthly
data/journal_profiles.json journal topic profiles with titles and ISSNs, rebuilt monthly
data/rules/                sample rule files (state council points, a university bonus table)
data/curated/              hand-checked venues and fees (see its README)
scripts/                   data pipeline (Python)
tests/                     pytest suite; tests/core.test.html runs the browser tests
evaluation/                matcher evaluation results with provenance
```

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q tests
python scripts/fetch_conferences.py          # writes data/conferences.json and data/deadlines.ics
python -m http.server 8000                   # open http://localhost:8000
```

Browser tests: open `http://localhost:8000/tests/core.test.html`.

Rebuilding topic profiles needs the DBLP dump (about 1.1 GB):

```bash
curl -L -o dblp.xml.gz https://dblp.dagstuhl.de/xml/dblp.xml.gz
python scripts/build_profiles.py --dump dblp.xml.gz
python scripts/build_journal_profiles.py --dump dblp.xml.gz
```

The fetch step refuses to write when validation fails, when curated data is
malformed, or when the venue count drops below half of the previous run
(`--force` overrides the last check).

## Automation

- `update-data.yml`: daily; runs the tests, fetches deadlines, commits the data.
- `update-profiles.yml`: monthly; downloads the DBLP dump, rebuilds profiles and
  the evaluation.

## Licence

MIT, see [LICENSE](LICENSE). Data files keep the licence of their source.
