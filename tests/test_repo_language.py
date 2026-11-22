# SPDX-License-Identifier: MIT
"""Repository text is English. Vietnamese is allowed only where it is content:
the Vietnamese interface strings and a tokenizer test case."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {
    "assets/i18n.js": "Vietnamese interface translation",
    "tests/fixtures/tokenize_cases.json": "tokenizer case with Vietnamese diacritics",
    "tests/test_repo_language.py": "contains the detection pattern itself",
    "tests/rules.test.js": "test data quoting Vietnamese official documents",
}
SKIP_DIRS = {".git", "data", "evaluation", "__pycache__", ".venv"}
SUFFIXES = {".py", ".js", ".html", ".css", ".md", ".yml", ".yaml", ".json", ".txt", ".sh", ".ps1", ".bat"}
# Letters that only Vietnamese uses among Latin scripts (with their tone marks).
VIETNAMESE = re.compile("[ăâđêôơưĂÂĐÊÔƠƯẠ-ỹ]")


def scanned_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in SUFFIXES and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            yield p


def offenders(files):
    out = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if VIETNAMESE.search(line):
                out.append(f"{rel}:{n}")
    return out


def test_no_vietnamese_outside_allowed_files():
    files = list(scanned_files())
    assert len(files) > 10, f"scanned only {len(files)} files"
    assert offenders(files) == []


def test_detector_catches_vietnamese(tmp_path):
    bad = tmp_path / "x.py"
    bad.write_text("# Đang tải dữ liệu\nprint('ok')\n", encoding="utf-8")
    ok = tmp_path / "y.py"
    ok.write_text("# loading data, em dash — and ≤ are fine\n", encoding="utf-8")
    assert [bool(VIETNAMESE.search(f.read_text(encoding="utf-8"))) for f in (bad, ok)] == [True, False]
