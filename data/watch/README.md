# Conference website watch

`scripts/watch_series.py` runs every Monday (`.github/workflows/watch-series.yml`).
For each series in `series.yml` it fetches the listed pages (and, for `url_templates`,
the addresses for this year and next, such as `https://rivf{year}.org/`), then:

- `history/<series>.jsonl`: one line appended **only when a page changed** (content,
  HTTP status, final address, or reachability), with the page title, a SHA-256 of its
  visible text, and the dates found next to deadline words with the surrounding text.
  The file is never rewritten, so it is the change log of that series' website.
- `status.json`: rewritten every run; for every page, when it was last checked and
  when it last changed.
- `report-latest.json`: the pages that changed in the latest run.

When pages changed, the workflow opens an issue labelled `watch` listing the dates
found. **Extracted dates are never published as deadlines.** A maintainer checks the
page and records real deadlines in `data/curated/venues.yml` (with the page and the
check date). Past editions stay there as history and give next-year estimates.

## `series.yml`

```yaml
- id: rivf                    # unique, used for the history file name
  acronym: RIVF
  full_name: International Conference on Computing and Communication Technologies
  scope: international        # international | national
  urls: [https://example.org/]            # pages checked as they are
  url_templates: ["https://rivf{year}.org/"]   # optional; {year} is required
  note: optional free text
```
