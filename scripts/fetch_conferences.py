import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
import yaml
from bs4 import BeautifulSoup

CCFDDL_ZIP_URL = "https://github.com/ccfddl/ccf-deadlines/archive/refs/heads/main.zip"
WIKICFP_BASE_URL = "http://www.wikicfp.com"
OUTPUT_PATH = "data/conferences.json"

SUB_MAP = {
    "AI": "Artificial Intelligence",
    "DB": "Data Mining & Databases",
    "SE": "Software Engineering",
    "SC": "Security & Privacy",
    "NW": "Computer Networks",
    "DS": "Computer Architecture & Systems",
    "CG": "Computer Graphics & Multimedia",
    "CT": "Theory of Computation",
    "HI": "Human-Computer Interaction",
    "MX": "Interdisciplinary / Emerging",
}

WIKICFP_CATEGORIES = [
    ("data mining", "DB"),
    ("artificial intelligence", "AI"),
    ("machine learning", "AI"),
    ("security", "SC"),
    ("software engineering", "SE"),
    ("computer networks", "NW"),
    ("computer science", "MX"),
]

COUNTRY_ALIASES = {
    "usa": "USA",
    "u.s.a.": "USA",
    "u.s.": "USA",
    "us": "USA",
    "united states": "USA",
    "united states of america": "USA",
    "uk": "UK",
    "u.k.": "UK",
    "united kingdom": "UK",
    "england": "UK",
    "scotland": "UK",
    "wales": "UK",
    "prc": "China",
    "p.r. china": "China",
    "p.r.china": "China",
    "china": "China",
    "korea": "South Korea",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "viet nam": "Vietnam",
    "vietnam": "Vietnam",
    "uae": "UAE",
    "united arab emirates": "UAE",
    "the netherlands": "Netherlands",
    "netherlands": "Netherlands",
}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

CITY_STATES = {"singapore", "hong kong", "macau", "macao"}

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def make_dedup_key(acronym: str, year) -> str:
    raw = f"{acronym}{year}".lower()
    return re.sub(r"[^a-z0-9]", "", raw)


def normalize_country(raw: str) -> str:
    c = raw.strip().strip(".")
    if not c:
        return "TBD"
    if c.upper() in US_STATES:
        return "USA"
    return COUNTRY_ALIASES.get(c.lower(), c)


def parse_place(place_str: str):
    """Tách chuỗi địa điểm thành (city, country) đã chuẩn hóa."""
    if not place_str or place_str.strip().lower() in ("tbd", "n/a", "tba", ""):
        return "", "TBD"

    clean = re.sub(r"\s+", " ", place_str).strip()
    if any(k in clean.lower() for k in ("online", "virtual")):
        return "Online", "Online"

    parts = [p.strip() for p in clean.split(",") if p.strip()]
    if len(parts) == 1:
        p0 = parts[0]
        if p0.lower() in CITY_STATES:
            return p0, p0
        return "", normalize_country(p0)

    if len(parts) == 2:
        city, second = parts[0], parts[1]
        return city, normalize_country(second)

    # 3 phần trở lên, ví dụ: "San Diego, CA, USA" hoặc "Vancouver, BC, Canada"
    return parts[0], normalize_country(parts[-1])


def safe_iso_date(y: int, m: int, d: int):
    try:
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_event_dates(date_str: str, fallback_year=None):
    """Phân tích chuỗi ngày tổ chức thành (event_start, event_end) dạng YYYY-MM-DD."""
    if not date_str or str(date_str).strip().lower() in ("tbd", "n/a", "tba", ""):
        return None, None

    s = str(date_str).replace("–", "-").replace("—", "-").strip()
    s = re.sub(r"\s+", " ", s)

    # Dạng 1: "Oct 12, 2026 - Oct 15, 2026" (phổ biến trên WikiCFP)
    m = re.search(
        r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})\s*-\s*([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})",
        s,
    )
    if m:
        m1, d1, y1, m2, d2, y2 = m.groups()
        mo1, mo2 = MONTH_MAP.get(m1.lower()), MONTH_MAP.get(m2.lower())
        if mo1 and mo2:
            return safe_iso_date(int(y1), mo1, int(d1)), safe_iso_date(int(y2), mo2, int(d2))

    # Dạng 2: "May 29 - June 2, 2027"
    m = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})",
        s,
    )
    if m:
        m1, d1, m2, d2, y = m.groups()
        mo1, mo2 = MONTH_MAP.get(m1.lower()), MONTH_MAP.get(m2.lower())
        if mo1 and mo2:
            y1 = int(y) - 1 if mo1 > mo2 else int(y)
            return safe_iso_date(y1, mo1, int(d1)), safe_iso_date(int(y), mo2, int(d2))

    # Dạng 3: "August 14-18, 2027" hoặc "Aug 14 - 18, 2027"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),?\s*(\d{4})", s)
    if m:
        mon, d1, d2, y = m.groups()
        mo = MONTH_MAP.get(mon.lower())
        if mo:
            return safe_iso_date(int(y), mo, int(d1)), safe_iso_date(int(y), mo, int(d2))

    # Dạng 4: "14-18 August 2027"
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+),?\s*(\d{4})", s)
    if m:
        d1, d2, mon, y = m.groups()
        mo = MONTH_MAP.get(mon.lower())
        if mo:
            return safe_iso_date(int(y), mo, int(d1)), safe_iso_date(int(y), mo, int(d2))

    # Dạng 5: "2027-08-14 - 2027-08-18" hoặc "2027-08-14 to 2027-08-18"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:-|to)\s*(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1), m.group(2)

    # Dạng 6: Ngày đơn "August 14, 2027"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", s)
    if m:
        mon, d1, y = m.groups()
        mo = MONTH_MAP.get(mon.lower())
        if mo:
            dt = safe_iso_date(int(y), mo, int(d1))
            return dt, dt

    # Dạng 7: Chỉ có tháng và năm "August 2027"
    m = re.search(r"([A-Za-z]+),?\s*(\d{4})", s)
    if m:
        mon, y = m.groups()
        mo = MONTH_MAP.get(mon.lower())
        if mo:
            dt = safe_iso_date(int(y), mo, 1)
            return dt, dt

    return None, None


def parse_tz(tz_str: str) -> timezone:
    if not tz_str or tz_str.strip().upper() == "AOE":
        return timezone(timedelta(hours=-12))
    match = re.match(r"UTC([+-])(\d{1,2})(?::?(\d{2}))?", tz_str.strip().upper())
    if match:
        sign = 1 if match.group(1) == "+" else -1
        hours = int(match.group(2))
        minutes = int(match.group(3) or 0)
        return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    return timezone(timedelta(hours=-12))


def parse_deadline(dl_str: str, tz_str: str = "AoE"):
    if not dl_str or str(dl_str).strip().upper() in ("TBD", "N/A", ""):
        return None
    tz = parse_tz(tz_str)
    clean_str = re.sub(r"\(.*?\)", "", str(dl_str).strip()).strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(clean_str, fmt)
            if fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def fetch_ccfddl():
    print("1. Đang tải dữ liệu từ ccfddl/ccf-deadlines...")
    resp = requests.get(CCFDDL_ZIP_URL, timeout=60)
    resp.raise_for_status()

    now_utc = datetime.now(timezone.utc)
    results = []
    seen_keys = set()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        yml_files = [f for f in zf.namelist() if "/conference/" in f and f.endswith(".yml")]

        for filepath in yml_files:
            with zf.open(filepath) as f:
                try:
                    items = yaml.safe_load(f)
                except yaml.YAMLError:
                    continue
                if not isinstance(items, list):
                    continue

                for item in items:
                    title = item.get("title", "")
                    desc = item.get("description", "")
                    sub = item.get("sub", "MX")
                    rank = item.get("rank", {}) or {}

                    for conf in item.get("confs", []):
                        year = conf.get("year")
                        tz_str = conf.get("timezone", "AoE")
                        timelines = conf.get("timeline", []) or []

                        upcoming_dl = None
                        abstract_dl = None
                        comment = ""

                        for tl in timelines:
                            dt = parse_deadline(tl.get("deadline"), tz_str)
                            if dt and dt > now_utc:
                                if upcoming_dl is None or dt < upcoming_dl:
                                    upcoming_dl = dt
                                    abs_dt = parse_deadline(tl.get("abstract_deadline"), tz_str)
                                    abstract_dl = abs_dt.isoformat() if abs_dt else None
                                    comment = tl.get("comment", "")

                        if upcoming_dl:
                            key = make_dedup_key(title, year)
                            seen_keys.add(key)
                            place_raw = conf.get("place", "TBD")
                            date_raw = conf.get("date", "TBD")
                            city, country = parse_place(place_raw)
                            ev_start, ev_end = parse_event_dates(date_raw, year)

                            results.append({
                                "id": conf.get("id", f"{title.lower()}_{year}"),
                                "acronym": title,
                                "full_name": desc,
                                "year": int(year) if year else upcoming_dl.year,
                                "sub": sub,
                                "topic": SUB_MAP.get(sub, sub),
                                "rank_ccf": rank.get("ccf", "N/A"),
                                "rank_core": rank.get("core", "N/A"),
                                "deadline_iso": upcoming_dl.astimezone(timezone.utc).isoformat(),
                                "abstract_iso": abstract_dl,
                                "timezone": tz_str,
                                "comment": comment,
                                "date": date_raw,
                                "event_start": ev_start,
                                "event_end": ev_end,
                                "place": place_raw,
                                "city": city,
                                "country": country,
                                "url": conf.get("link", ""),
                                "source": "ccfddl",
                            })

    print(f"   -> Lấy được {len(results)} hội nghị từ ccfddl.")
    return results, seen_keys


def fetch_wikicfp(seen_keys: set, max_pages: int = 2):
    print("2. Đang bổ sung dữ liệu từ WikiCFP...")
    now_utc = datetime.now(timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CSConfTracker/1.0; +https://github.com)"}
    added = []

    for cat_name, sub_code in WIKICFP_CATEGORIES:
        for page in range(1, max_pages + 1):
            url = f"{WIKICFP_BASE_URL}/cfp/call?conference={quote(cat_name)}&page={page}"
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"   [Cảnh báo] Không tải được WikiCFP ({cat_name}, trang {page}): {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            contsec = soup.find("div", class_="contsec")
            if not contsec:
                break

            conf_table = None
            for tb in contsec.find_all("table"):
                if tb.find("td", string=re.compile(r"Event", re.I)):
                    conf_table = tb
                    break
            if not conf_table:
                break

            rows = conf_table.find_all("tr")
            i = 1
            while i + 1 < len(rows):
                r1_tds = rows[i].find_all("td")
                r2_tds = rows[i + 1].find_all("td")
                i += 2

                if len(r1_tds) < 2 or len(r2_tds) < 3:
                    continue

                link_tag = r1_tds[0].find("a")
                if not link_tag:
                    continue

                raw_event = link_tag.get_text(strip=True)
                href = link_tag.get("href", "")
                conf_url = f"{WIKICFP_BASE_URL}{href}" if href.startswith("/") else href
                full_name = r1_tds[1].get_text(strip=True)

                date_str = r2_tds[0].get_text(strip=True)
                place_str = r2_tds[1].get_text(strip=True)
                dl_str = r2_tds[2].get_text(strip=True)

                dl_dt = parse_deadline(dl_str, "AoE")
                if not dl_dt or dl_dt <= now_utc:
                    continue

                m = re.match(r"^(.*?)\s*(\d{4})$", raw_event)
                if m:
                    acronym, year = m.group(1).strip(), int(m.group(2))
                else:
                    acronym, year = raw_event, dl_dt.year

                key = make_dedup_key(acronym, year)
                if key in seen_keys:
                    continue

                seen_keys.add(key)
                city, country = parse_place(place_str)
                ev_start, ev_end = parse_event_dates(date_str, year)

                added.append({
                    "id": f"wikicfp_{key}",
                    "acronym": acronym,
                    "full_name": full_name,
                    "year": year,
                    "sub": sub_code,
                    "topic": SUB_MAP.get(sub_code, sub_code),
                    "rank_ccf": "N/A",
                    "rank_core": "N/A",
                    "deadline_iso": dl_dt.astimezone(timezone.utc).isoformat(),
                    "abstract_iso": None,
                    "timezone": "AoE",
                    "comment": "Nguồn: WikiCFP",
                    "date": date_str or "TBD",
                    "event_start": ev_start,
                    "event_end": ev_end,
                    "place": place_str or "TBD",
                    "city": city,
                    "country": country,
                    "url": conf_url,
                    "source": "wikicfp",
                })

            time.sleep(1)

    print(f"   -> Bổ sung thêm {len(added)} hội nghị mới từ WikiCFP.")
    return added


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    ccf_confs, seen_keys = fetch_ccfddl()
    wiki_confs = fetch_wikicfp(seen_keys, max_pages=2)

    all_confs = ccf_confs + wiki_confs
    all_confs.sort(key=lambda x: x["deadline_iso"])

    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total": len(all_confs),
        "conferences": all_confs,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Hoàn tất! Tổng cộng {len(all_confs)} hội nghị đã lưu vào {OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
