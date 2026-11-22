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

# Các chuyên mục cần lấy trên WikiCFP -> ánh xạ về mã nhóm (sub)
WIKICFP_CATEGORIES = [
    ("data mining", "DB"),
    ("artificial intelligence", "AI"),
    ("machine learning", "AI"),
    ("security", "SC"),
    ("software engineering", "SE"),
    ("computer networks", "NW"),
    ("computer science", "MX"),
]


def make_dedup_key(acronym: str, year) -> str:
    """Tạo khóa chuẩn hóa để khử trùng lặp giữa các nguồn."""
    raw = f"{acronym}{year}".lower()
    return re.sub(r"[^a-z0-9]", "", raw)


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
    clean_str = str(dl_str).strip()
    # Loại bỏ phần ngày cũ trong ngoặc đơn nếu WikiCFP ghi kiểu: "Dec 15, 2026 (Dec 01, 2026)"
    clean_str = re.sub(r"\(.*?\)", "", clean_str).strip()

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
    )
    for fmt in formats:
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
        yml_files = [
            f for f in zf.namelist()
            if "/conference/" in f and f.endswith(".yml")
        ]

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
                            results.append({
                                "id": conf.get("id", f"{title.lower()}_{year}"),
                                "acronym": title,
                                "full_name": desc,
                                "year": year,
                                "sub": sub,
                                "topic": SUB_MAP.get(sub, sub),
                                "rank_ccf": rank.get("ccf", "N/A"),
                                "rank_core": rank.get("core", "N/A"),
                                "deadline_iso": upcoming_dl.astimezone(timezone.utc).isoformat(),
                                "abstract_iso": abstract_dl,
                                "timezone": tz_str,
                                "comment": comment,
                                "date": conf.get("date", "TBD"),
                                "place": conf.get("place", "TBD"),
                                "url": conf.get("link", ""),
                                "source": "ccfddl",
                            })

    print(f"   -> Lấy được {len(results)} hội nghị từ ccfddl.")
    return results, seen_keys


def fetch_wikicfp(seen_keys: set, max_pages: int = 2):
    print("2. Đang bổ sung dữ liệu từ WikiCFP...")
    now_utc = datetime.now(timezone.utc)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CSConfTracker/1.0; +https://github.com)"
    }
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

            # Bảng danh sách hội nghị của WikiCFP có cặp 2 thẻ <tr> cho mỗi hội nghị
            tables = contsec.find_all("table")
            conf_table = None
            for tb in tables:
                if tb.find("td", string=re.compile(r"Event", re.I)):
                    conf_table = tb
                    break
            if not conf_table:
                break

            rows = conf_table.find_all("tr")
            # Bỏ qua hàng tiêu đề đầu tiên, duyệt từng cặp 2 hàng
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

                # Tách tên viết tắt và năm từ chuỗi kiểu "ICDM 2026"
                m = re.match(r"^(.*?)\s*(\d{4})$", raw_event)
                if m:
                    acronym = m.group(1).strip()
                    year = int(m.group(2))
                else:
                    acronym = raw_event
                    year = dl_dt.year

                key = make_dedup_key(acronym, year)
                if key in seen_keys:
                    continue

                seen_keys.add(key)
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
                    "place": place_str or "TBD",
                    "url": conf_url,
                    "source": "wikicfp",
                })

            # Nghỉ 1 giây giữa các trang để tôn trọng máy chủ WikiCFP
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
