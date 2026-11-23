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
    - {type: paper, date: "2026-12-15", comment: "extended from 2026-12-01", comment_vi: "..."}
                              # type: abstract | paper | rebuttal | notification; comment and
                              # comment_vi (its Vietnamese text) are optional
    - {type: notification, date: "2027-02-01"}
  date: "Mar 12-14, 2027"
  place: "Can Tho, Vietnam"
  publisher: IEEE             # optional
  keywords: [knowledge graph, reasoning]   # optional, helps topic matching
  fees:                       # optional
    - {label: "Regular author", label_vi: "...", amount: 350, currency: USD}   # label_vi optional
  fees_url: https://example.org/kse2026/registration
  checked: 2026-11-22
```

An edition whose dates are past is kept as history. When a series has no open
call, its latest edition moved forward one year is published as an estimate,
without last year's deadline notes; the estimate is replaced as soon as the new
call is entered here.

Text that the page shows (`comment`, fee `label`) is English; add `comment_vi`
and `label_vi` so the Vietnamese page shows Vietnamese. Without them the
Vietnamese page shows the English text marked as written on the venue page.

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
