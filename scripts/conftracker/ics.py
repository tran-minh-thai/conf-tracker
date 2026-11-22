# SPDX-License-Identifier: MIT
"""Minimal RFC 5545 calendar writer for deadline events."""
from __future__ import annotations

from datetime import datetime, timezone

LABELS = {
    "abstract": "Abstract deadline",
    "paper": "Paper deadline",
    "rebuttal": "Rebuttal deadline",
    "notification": "Notification",
}
ALARM_DAYS = (7, 1)


def escape_text(value: str) -> str:
    return (str(value).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Fold a content line to at most 75 octets per physical line."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current, limit = [], b"", 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > limit:
            parts.append(current.decode("utf-8"))
            current, limit = b"", 74  # continuation lines start with a space
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def deadline_events(edition: dict):
    """Yield one event dict per deadline of an edition."""
    for i, d in enumerate(edition.get("deadlines", [])):
        when = datetime.strptime(d["iso"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        label = LABELS.get(d["type"], d["type"])
        summary = f"{edition['acronym']} {edition['year']}: {label}"
        if edition.get("status") == "estimated":
            summary += " (estimated)"
        lines = [edition.get("full_name", "")]
        if d.get("comment"):
            lines.append(d["comment"])
        lines.append(f"Time zone stated by the venue: {edition.get('timezone', 'AoE')}")
        if edition.get("url"):
            lines.append(edition["url"])
        yield {
            "uid": f"{edition['id']}-{d['type']}-{i}@conf-tracker",
            "when": when,
            "summary": summary,
            "description": "\n".join(x for x in lines if x),
            "url": edition.get("url", ""),
            "location": edition.get("place", ""),
        }


def calendar(events, name: str, now: datetime) -> str:
    out = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//conf-tracker//deadlines//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{escape_text(name)}",
        "X-PUBLISHED-TTL:PT12H",
    ]
    stamp = _stamp(now)
    for ev in events:
        t = _stamp(ev["when"])
        out += [
            "BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp}",
            f"DTSTART:{t}", f"DTEND:{t}",
            f"SUMMARY:{escape_text(ev['summary'])}",
            f"DESCRIPTION:{escape_text(ev['description'])}",
        ]
        if ev.get("location"):
            out.append(f"LOCATION:{escape_text(ev['location'])}")
        if ev.get("url"):
            out.append(f"URL:{ev['url']}")
        for days in ALARM_DAYS:
            out += [
                "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape_text(ev['summary'])}",
                f"TRIGGER:-P{days}D", "END:VALARM",
            ]
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in out) + "\r\n"
