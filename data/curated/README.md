# Hand-checked data

No feed covers national conferences or registration fees, so they are kept here
by hand. The daily update reads both files and rejects the run if an entry is
malformed (`scripts/conftracker/curated.py` lists every check).

Every entry must say **where** it was checked (`url`, `fees_url`) and **when**
(`checked`). Copy dates exactly as the official page prints them; never estimate.

## `venues.yml`: extra conferences

```yaml
- acronym: KSE
  full_name: "International Conference on Knowledge and Systems Engineering"
  year: 2026
  scope: international        # international | national (national-level conference)
  sub: AI                     # AI DB SE SC NW DS CG CT HI MX OT
  url: https://example.org/kse2026/cfp
  timezone: unstated          # as printed, e.g. AoE, UTC+7; "unstated" shows a warning
  deadlines:
    - {type: paper, date: "2026-12-15"}            # abstract | paper | rebuttal | notification
    - {type: notification, date: "2027-02-01"}
  date: "Mar 12-14, 2027"
  place: "Can Tho, Vietnam"
  publisher: IEEE             # optional
  keywords: [knowledge graph, reasoning]   # optional, helps topic matching
  fees:                       # optional
    - {label: "Regular author", amount: 350, currency: USD}
  fees_url: https://example.org/kse2026/registration
  checked: 2026-11-22
```

An entry whose deadlines are all more than 60 days old is skipped and reported
by the update, so stale entries get noticed.

## `fees.yml`: fees for venues from the automatic sources

```yaml
- acronym: PAKDD
  year: 2027
  fees:
    - {label: "Regular, early", amount: 800, currency: NZD}
  fees_url: https://example.org/pakdd2027/registration
  checked: 2026-11-22
  note: ""                    # optional
```

`acronym` is matched without prefixes such as IEEE or ACM.
