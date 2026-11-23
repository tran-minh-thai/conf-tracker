# SPDX-License-Identifier: MIT
"""Access model (open, hybrid, subscription) and citation figures for the journals in the finder.

Two public sources, both CC0 for this data:
- DOAJ journal CSV (journal-level metadata, CC0 waiver): listed journals are fully open access,
  with their article charges as the journal states them.
- OpenAlex sources and works (CC0): whether a journal is fully open, how many of its articles in
  one year were "hybrid" (open articles in a subscription journal), list APC in USD, and the
  journal's two-year mean citedness and h-index.

Rules, fixed before the first run (2026-11-23) and not tuned on the results:
- open: listed in DOAJ, or OpenAlex says the journal is fully open access.
- hybrid: not open, at least MIN_WORKS articles in the year, and at least MIN_HYBRID of them hybrid.
- subscription: not open, at least MIN_WORKS articles in the year, fewer than MIN_HYBRID hybrid.
- unknown: no OpenAlex record, or fewer than MIN_WORKS articles in the year (too few to tell).
- "diamond" marks an open journal that DOAJ lists without article charges.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

import yaml

MIN_WORKS = 20
MIN_HYBRID = 5
RULES = {"min_works": MIN_WORKS, "min_hybrid": MIN_HYBRID,
         "open": "in DOAJ or OpenAlex is_oa",
         "hybrid": f"not open, >= {MIN_WORKS} articles in the year, >= {MIN_HYBRID} hybrid",
         "subscription": f"not open, >= {MIN_WORKS} articles in the year, < {MIN_HYBRID} hybrid",
         "unknown": f"no OpenAlex record or < {MIN_WORKS} articles in the year"}

ISSN_RE = re.compile(r"^(\d{4})-?(\d{3}[\dX])$")


def norm_issn(raw: str) -> str:
    m = ISSN_RE.match((raw or "").strip().upper())
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def parse_apc(raw: str) -> list[dict]:
    """'1000000 IDR; 100 USD' -> [{'amount': 1000000, 'currency': 'IDR'}, {'amount': 100, 'currency': 'USD'}]."""
    out = []
    for part in (raw or "").split(";"):
        m = re.fullmatch(r"\s*([\d.,]+)\s*([A-Za-z]{3})\s*", part)
        if m:
            amount = float(m.group(1).replace(",", ""))
            out.append({"amount": int(amount) if amount.is_integer() else amount, "currency": m.group(2).upper()})
    return out


def read_doaj(text: str) -> dict[str, dict]:
    """DOAJ journal CSV -> {issn: {"apc": bool, "apc_amounts": [...], "title": str}} for print and online ISSNs."""
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    need = {"Journal ISSN (print version)", "Journal EISSN (online version)", "APC", "APC amount"}
    if not need <= set(rows.fieldnames or []):
        raise ValueError(f"DOAJ CSV lacks columns: {sorted(need - set(rows.fieldnames or []))}")
    out = {}
    for r in rows:
        rec = {"apc": r["APC"].strip().lower() == "yes", "apc_amounts": parse_apc(r["APC amount"]),
               "title": r.get("Journal title", "").strip()}
        for col in ("Journal ISSN (print version)", "Journal EISSN (online version)"):
            issn = norm_issn(r[col])
            if issn:
                out[issn] = rec
    return out


def classify(in_doaj: bool, oa_is_oa: bool | None, works: int | None, hybrid: int | None) -> str:
    if in_doaj or oa_is_oa:
        return "open"
    if oa_is_oa is None or works is None or works < MIN_WORKS:
        return "unknown"
    return "hybrid" if (hybrid or 0) >= MIN_HYBRID else "subscription"


def journal_record(issns: list[str], doaj: dict, source: dict | None, works: int | None, hybrid: int | None) -> dict:
    """One journal's entry. `source` is the OpenAlex source object (or None when not found)."""
    d = next((doaj[i] for i in issns if i in doaj), None)
    is_oa = None if source is None else bool(source.get("is_oa"))
    access = classify(d is not None, is_oa, works, hybrid)
    stats = (source or {}).get("summary_stats") or {}
    rec = {
        "access": access,
        "in_doaj": d is not None,
        "diamond": bool(d is not None and not d["apc"]),
        # The journal's own statement (DOAJ) first, else the OpenAlex list price in USD.
        "apc": d["apc_amounts"] if d and d["apc_amounts"] else
               ([{"amount": source["apc_usd"], "currency": "USD"}] if source and source.get("apc_usd") else []),
        "apc_source": "doaj" if d and d["apc_amounts"] else ("openalex" if source and source.get("apc_usd") else None),
        "works_year": works,
        "hybrid_year": hybrid,
        "citedness_2y": round(stats["2yr_mean_citedness"], 2) if isinstance(stats.get("2yr_mean_citedness"), (int, float)) else None,
        "h_index": stats.get("h_index"),
        "openalex": (source or {}).get("id", "").rsplit("/", 1)[-1] or None,
        # Every ISSN known for the journal (the finder's own plus OpenAlex's), so a publication can be
        # matched whichever ISSN Crossref gives; and the publisher's country (OpenAlex), which tells a
        # foreign journal from a domestic one.
        "issn": sorted({n for n in (norm_issn(i) for i in [*issns, *((source or {}).get("issn") or [])]) if n}),
        "country": (source or {}).get("country_code") or None,
    }
    if access == "open" and rec["diamond"]:
        rec["apc"], rec["apc_source"] = [], "doaj"
    return rec


ACCESS = {"open", "hybrid", "subscription"}


def load_overrides(path: Path, keys: set[str]) -> dict[str, dict]:
    """Hand-checked entries (data/curated/journal_access.yml), validated; a bad entry stops the build."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out = {}
    for i, e in enumerate(data):
        w = f"{path.name}[{i}]"
        k = e.get("journal")
        if k not in keys:
            raise ValueError(f"{w}: unknown journal key {k!r}")
        if k in out:
            raise ValueError(f"{w}: duplicate journal {k}")
        if e.get("access") not in ACCESS:
            raise ValueError(f"{w}: access must be one of {sorted(ACCESS)}")
        if not isinstance(e.get("diamond"), bool) or (e["diamond"] and e["access"] != "open"):
            raise ValueError(f"{w}: diamond must be true or false, and only an open journal can be diamond")
        if not str(e.get("url", "")).startswith("https://"):
            raise ValueError(f"{w}: needs the https url of the page that states it")
        if not isinstance(e.get("checked"), date):
            raise ValueError(f"{w}: needs a checked date (YYYY-MM-DD)")
        out[k] = e
    return out


def apply_override(rec: dict, e: dict) -> dict:
    """The hand-checked statement replaces the access model; figures from the sources stay."""
    r = dict(rec, access=e["access"], diamond=e["diamond"], override={"url": e["url"], "checked": e["checked"].isoformat()})
    if e["diamond"]:
        r["apc"], r["apc_source"] = [], "curated"
    return r
