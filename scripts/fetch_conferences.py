import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
import requests
import yaml

CCFDDL_ZIP_URL = "https://github.com/ccfddl/ccf-deadlines/archive/refs/heads/main.zip"
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

def parse_deadline(dl_str: str, tz_str: str):
    if not dl_str or str(dl_str).strip().upper() == "TBD":
        return None
    tz = parse_tz(tz_str)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(str(dl_str).strip(), fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue
    return None

def fetch_ccfddl():
    print("Đang tải dữ liệu từ ccfddl/ccf-deadlines...")
    resp = requests.get(CCFDDL_ZIP_URL, timeout=60)
    resp.raise_for_status()

    now_utc = datetime.now(timezone.utc)
    results = []

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
                        tz_str = conf.get("timezone", "AoE")
                        timelines = conf.get("timeline", []) or []

                        # Tìm mốc deadline gần nhất còn hạn
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
                            results.append({
                                "id": conf.get("id", f"{title.lower()}_{conf.get('year')}"),
                                "acronym": title,
                                "full_name": desc,
                                "year": conf.get("year"),
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
                            })

    results.sort(key=lambda x: x["deadline_iso"])
    return results

def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    conferences = fetch_ccfddl()
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total": len(conferences),
        "conferences": conferences,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Hoàn tất! Đã lưu {len(conferences)} hội nghị sắp diễn ra vào {OUTPUT_PATH}.")

if __name__ == "__main__":
    main()