# Channel ranking study (data/venue_channels.json)

Code of the held-out study behind the ranking channels used by "find venues for a paper".
Results: `evaluation/channel-ranking-*.json`. The method is pre-registered: settings are chosen
on the even half of the queries (validation) and reported on the odd half (test).

## Data

- DBLP dump (CC0): conference papers 2020-2025 of the ccfddl series (`extract.py`).
- Queries: 2025 abstracts, at most 30 per venue (4,806 over 197 venues), from Semantic Scholar and
  Crossref (`fetch_s2.py`, `fetch.py`). They are used only to measure, never published; the text
  stays outside the repository.
- Channel counts for 2020-2024, at most 200 papers per venue:
  - keywords: OpenAlex keywords and topics (CC0);
  - arxiv: terms of arXiv abstracts (CC0 1.0, abstract included);
  - comparison only, never published: OpenAlex abstracts, Crossref abstracts (publisher copyright),
    Semantic Scholar abstracts (licence reserves derivative works).
  Abstracts are tokenized in memory; only per-venue counts of terms seen in at least 3 papers
  (top 500) are written (`collect.py`, `collect_helpers.py`, `collect_low.py`).
  Venues whose DBLP records mostly lack DOIs are found by listing their OpenAlex sources and
  matching DBLP titles exactly (`collect_low.py`).

## Steps

1. `extract.py`, `train.py`: papers and held-out title profiles (2020-2024).
2. `collect.py`, `collect_low_rerun.py`: channel counts (OpenAlex, arXiv; comparison sources).
3. `coverage.py`: coverage per venue and source.
4. `rank_run.py` (with `rank_study.py`): stage 1 per-channel settings (cosine or BM25, recency,
   phrase weight), stage 2 fusion (weighted sum or reciprocal rank fusion, weights, missing-channel
   rule), both on validation; stage 3 one read of the test half. `check_driver.py` checks that the
   driver reproduces the current matcher's MRR; `parity_channels.py` checks that the repository
   module (`scripts/conftracker/channels.py`) gives the study's ranks.
5. `make_committed_counts.py`: the published channels' counts into `data/channel_counts.json`;
   `scripts/update_channel_counts.py` then adds 2025 and drops 2020, as the monthly workflow does.

Every run went through `run.py`, which records the command, the hashes of the code and inputs, and
the log. Scripts read their working data from `CHANNEL_STUDY_DATA` (default: current folder).

A first study on the same queries (title profiles mixed with abstract terms) was superseded:
its abstract inputs were deleted under the rule that abstract text is not kept, so it cannot be
re-run; it is not part of this folder.
