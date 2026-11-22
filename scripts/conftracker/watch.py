# SPDX-License-Identifier: MIT
"""Periodic watch of conference websites that no feed covers (national series).

Each run fetches the pages of every watched series, extracts the visible text,
hashes it, and pulls out dates that sit next to deadline words, with the text
around them as evidence. A record is appended to the series' history file only
when something changed (content, status, final address), so the history is a
log of changes. Extracted dates are never published as deadlines: a person
confirms them into data/curated/venues.yml.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "conf-tracker/2.0 (+https://github.com/tran-minh-thai/conf-tracker)"}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Labels for the words found before a date. Vietnamese is matched without accents
# (the text is folded), so "han nop" also covers the accented spelling.
LABELS = [
    # "Abstract registration" is the abstract deadline, not event registration; when two
    # keywords end at the same place the earlier label in this list wins.
    ("abstract", r"abstract registration|abstract submission|abstract|dang ky tom tat|tom tat"),
    ("paper", r"submission|deadline|due|han nop|han gui|nop bai|gui bai|toan van|full paper|paper"),
    ("notification", r"notification|acceptance|thong bao|ket qua|chap nhan"),
    ("proceedings", r"ky yeu|proceedings"),
    ("camera_ready", r"camera|final version|ban hoan chinh|ban cuoi"),
    ("registration", r"registration|dang ky"),
    ("event", r"conference date|conference will be held|to chuc|dien ra|hoi nghi|hoi thao|event"),
]
_LABELS = [(k, re.compile(p)) for k, p in LABELS]

_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    # 15/12/2026, 15-12-2026, 15.12.2026 (day first, as in Vietnamese and most CFPs)
    ("dmy", re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")),
    # 2026-12-15
    ("ymd", re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")),
    # December 15, 2026 / Dec. 15 2026
    ("mdy", re.compile(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.I)),
    # 15 December 2026
    ("dmy_name", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(20\d{{2}})\b", re.I)),
    # ngay 15 thang 12 nam 2026 (folded Vietnamese)
    ("vi", re.compile(r"ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})\s+nam\s+(20\d{2})")),
]


def fold(text: str) -> str:
    """Lower-case, strip accents, map d-stroke, so Vietnamese keywords match plain ASCII."""
    t = text.lower().replace("\u0111", "d")
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def decode_html(content: bytes, header_encoding: str | None) -> str:
    """Decode a page using its declared charset; servers often omit it from the headers."""
    soup = BeautifulSoup(content, "html.parser")  # reads <meta charset> and byte-order marks
    if soup.original_encoding:
        return content.decode(soup.original_encoding, errors="replace")
    return content.decode(header_encoding or "utf-8", errors="replace")


def visible_text(html: str) -> tuple[str, str]:
    """(title, visible text with whitespace collapsed)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return title, text


def _to_date(kind: str, m: re.Match) -> date | None:
    try:
        if kind in ("dmy", "vi"):
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
        elif kind == "ymd":
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
        elif kind == "mdy":
            mo, d, y = MONTHS[m[1].lower().rstrip(".")], int(m[2]), int(m[3])
        else:
            d, mo, y = int(m[1]), MONTHS[m[2].lower().rstrip(".")], int(m[3])
        return date(y, mo, d)
    except (ValueError, KeyError):
        return None


def extract_dates(text: str, window: int = 70, limit: int = 25) -> list[dict]:
    """Dates with the label of the nearest preceding keyword and the text around them.

    Positions refer to the folded text, which keeps the length of the original
    for Latin scripts (accents are removed, not letters), so evidence is cut from
    the original text at the same offsets.
    """
    folded = fold(text)
    if len(folded) != len(text):
        folded_for_pos, original = folded, folded  # fall back to folded evidence
    else:
        folded_for_pos, original = folded, text
    seen, out = set(), []
    for kind, pat in DATE_PATTERNS:
        for m in pat.finditer(folded_for_pos):
            d = _to_date(kind, m)
            if d is None:
                continue
            before = folded_for_pos[max(0, m.start() - window):m.start()]
            label = "other"
            best = -1
            for name, lp in _LABELS:
                for hit in lp.finditer(before):
                    if hit.end() > best:
                        best, label = hit.end(), name
            key = (d.isoformat(), label)
            if key in seen:
                continue
            seen.add(key)
            s, e = max(0, m.start() - window), min(len(original), m.end() + 30)
            out.append({"pos": m.start(), "date": d.isoformat(), "label": label,
                        "evidence": original[s:e].strip()})
    out.sort(key=lambda c: c["pos"])
    return [{k: v for k, v in c.items() if k != "pos"} for c in out[:limit]]


def expand_urls(series: dict, today: date) -> list[str]:
    """Static addresses plus year templates for this year and the next ("rivf{year}.org")."""
    urls = list(series.get("urls") or [])
    for tpl in series.get("url_templates") or []:
        for y in (today.year, today.year + 1):
            urls.append(tpl.replace("{year}", str(y)))
    return list(dict.fromkeys(urls))


def check_url(url: str, session, timeout: int = 25) -> dict:
    """Fetch one page and summarise it. Errors are recorded, not raised."""
    try:
        r = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    except Exception as exc:  # network, TLS, DNS: all are facts worth recording
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    rec = {"url": url, "status": r.status_code, "final_url": r.url}
    if r.status_code != 200:
        return rec
    html = decode_html(r.content, r.encoding if "charset" in r.headers.get("content-type", "").lower() else None)
    title, text = visible_text(html)
    rec.update({
        "title": title[:200],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chars": len(text),
        "dates": extract_dates(text),
    })
    return rec


def signature(rec: dict) -> tuple:
    """What counts as a change: status, final address, content."""
    return rec.get("status"), rec.get("final_url"), rec.get("sha256"), bool(rec.get("error"))


def load_series(path: Path) -> list[dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(doc, list):
        raise ValueError(f"{path}: top level must be a list")
    ids = set()
    for i, s in enumerate(doc):
        if not isinstance(s, dict) or not s.get("id") or not s.get("acronym"):
            raise ValueError(f"{path}[{i}]: needs id and acronym")
        if s["id"] in ids:
            raise ValueError(f"{path}[{i}]: duplicate id {s['id']}")
        ids.add(s["id"])
        if not (s.get("urls") or s.get("url_templates")):
            raise ValueError(f"{path}[{i}] ({s['id']}): needs urls or url_templates")
        for t in s.get("url_templates") or []:
            if "{year}" not in t:
                raise ValueError(f"{path}[{i}] ({s['id']}): template without {{year}}: {t}")
    return doc


def run(series_list: list[dict], out_dir: Path, session, now: datetime) -> dict:
    """Check every page, append changes to history, rewrite status.json; return the report."""
    hist_dir = out_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    stamp = now.isoformat()
    report = {"checked_at": stamp, "pages": 0, "changed": [], "errors": 0}
    for s in series_list:
        sid = s["id"]
        st = status.setdefault(sid, {"acronym": s["acronym"], "pages": {}})
        st["acronym"] = s["acronym"]
        for url in expand_urls(s, now.date()):
            rec = check_url(url, session)
            report["pages"] += 1
            report["errors"] += 1 if rec.get("status") != 200 else 0
            prev = st["pages"].get(url, {})
            changed = tuple(prev.get("signature") or ()) != signature(rec)
            page = {"last_checked": stamp, "status": rec.get("status"), "title": rec.get("title", ""),
                    "signature": list(signature(rec)),
                    "last_changed": stamp if changed else prev.get("last_changed", stamp)}
            st["pages"][url] = page
            if changed:
                entry = {"checked_at": stamp, "series": sid, "first_seen": not prev, **rec}
                with open(hist_dir / f"{sid}.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if rec.get("status") == 200:
                    report["changed"].append({"series": sid, "acronym": s["acronym"], "url": url,
                                              "title": rec.get("title", ""), "first_seen": not prev,
                                              "dates": [d for d in rec.get("dates", []) if d["label"] != "other"][:12]})
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def issue_markdown(report: dict, repo_url: str = "") -> str:
    """A review issue listing changed pages and the dates found on them."""
    lines = [f"Watch run {report['checked_at']}: {len(report['changed'])} page(s) changed "
             f"out of {report['pages']} checked ({report['errors']} not reachable).", "",
             "Dates below are extracted automatically and are **not published**. Confirm the ones that are "
             "real deadlines into `data/curated/venues.yml` (with the page and the check date).", ""]
    for c in report["changed"]:
        lines.append(f"### {c['acronym']}: {c['title'] or c['url']}")
        lines.append(f"{c['url']}{' (new page)' if c['first_seen'] else ''}")
        if not c["dates"]:
            lines.append("- no dated deadline words found")
        for d in c["dates"]:
            ev = d["evidence"].replace("|", "/")
            lines.append(f"- **{d['date']}** ({d['label']}): \u2026{ev}\u2026")
        lines.append("")
    return "\n".join(lines)
