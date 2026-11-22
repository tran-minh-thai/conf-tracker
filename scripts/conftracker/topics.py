# SPDX-License-Identifier: MIT
"""Research areas and a keyword classifier for venues without a curated area.

ccfddl assigns every series to one of ten areas. WikiCFP only says which
search category a call appeared under, and that tag is set by whoever posted
the call: mechanical-engineering meetings show up under "data mining". So a
WikiCFP venue gets its area from the words in its full name instead.
"""
from __future__ import annotations

import re

AREAS = {
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
    "OT": "Outside Computing",
}

# Ordered: the first area whose pattern matches wins, so more specific areas
# come before broad ones (security before networks, data mining before AI).
KEYWORDS = [
    ("SC", r"secur|privacy|crypt|forensic|trust|malware|intrusion|blockchain|cyber|attack"),
    ("DB", r"data mining|database|big data|data science|knowledge discovery|information retrieval|"
           r"data management|recommender|web mining|text mining|semantic web|data engineering|analytics"),
    ("CG", r"graphics|multimedia|image|video|vision|visuali|signal processing|speech|audio|virtual reality"),
    ("HI", r"human[- ]computer|interaction|user experience|ubiquitous|accessib|usab"),
    ("SE", r"software|programming|requirements|model[- ]driven|testing|devops|formal method"),
    ("NW", r"network|wireless|internet of things|\biot\b|communication|mobile|5g|6g|sensor|cloud|edge computing|internet"),
    ("DS", r"architecture|parallel|distributed|high performance|embedded|operating system|computer systems|"
           r"storage|hardware|vlsi|circuit"),
    ("CT", r"theory|algorithm|logic|computational complexity|combinatori|automata"),
    ("AI", r"artificial intelligence|machine learning|deep learning|neural|natural language|\bnlp\b|"
           r"intelligen|fuzzy|robot|soft computing|evolutionary|language model|\bai\b"),
    ("MX", r"comput|informati|digital|cyber|e-learning|bioinformatics|smart"),
]
_COMPILED = [(area, re.compile(pat, re.I)) for area, pat in KEYWORDS]

# Names that clearly sit outside computing even when they mention "computing".
OUTSIDE = re.compile(
    r"mechanical|civil engineering|supply chain|management|economics|education|business|"
    r"medicine|medical|nursing|agricultur|chemistry|physics|materials|energy|electrical engineering|"
    r"social science|humanities|tourism|finance|marketing|law\b|linguistics",
    re.I,
)
STRONG_CS = re.compile(r"comput|software|data|artificial intelligence|machine learning|network|secur", re.I)

JOURNAL = re.compile(r"\bjournal\b|\btransactions on\b", re.I)
CONFERENCE = re.compile(r"\b(conference|symposium|workshop|congress|forum|summit)\b", re.I)


def classify(full_name: str) -> str:
    """Return an area code for a venue name."""
    name = full_name or ""
    if OUTSIDE.search(name) and not STRONG_CS.search(name):
        return "OT"
    for area, pat in _COMPILED:
        if pat.search(name):
            return area
    return "OT" if OUTSIDE.search(name) else "MX"


def venue_kind(full_name: str, acronym: str = "") -> str:
    """'journal' for calls that are journal issues, otherwise 'conference'."""
    name = full_name or ""
    if CONFERENCE.search(name):
        return "conference"
    if JOURNAL.search(name) or re.match(r"^IJ[A-Z]", acronym or ""):
        return "journal"
    return "conference"
