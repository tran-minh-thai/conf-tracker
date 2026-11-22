# SPDX-License-Identifier: MIT
import json
from datetime import date, datetime, timezone

import pytest

from conftracker import watch

VI_PAGE = """<html><head><meta charset="utf-8"><title>Hội nghị Quốc gia FAIR 2027</title>
<script>var x = "Hạn nộp 01/01/2099";</script></head><body>
<h2>Các mốc thời gian</h2>
<p>Hạn nộp toàn văn: 15/06/2027</p>
<p>Thông báo kết quả: ngày 20 tháng 7 năm 2027</p>
<p>Hội nghị diễn ra từ 2027-10-01</p>
<p>Hạn đăng ký: 01/09/2027</p>
<noscript>Hạn nộp 02/02/2098</noscript>
</body></html>"""

EN_PAGE = """<html><head><title>XYZ 2027</title></head><body>
<ul><li>Abstract registration: Jan 5, 2027</li><li>Paper submission deadline: 12 January 2027</li>
<li>Notification of acceptance: March 1st, 2027</li><li>Invalid: 31/02/2027</li></ul></body></html>"""


def test_text_extraction_drops_scripts_and_keeps_title():
    title, text = watch.visible_text(VI_PAGE)
    assert title == "Hội nghị Quốc gia FAIR 2027"
    assert "2099" not in text and "2098" not in text and "15/06/2027" in text


def test_vietnamese_dates_and_labels():
    _, text = watch.visible_text(VI_PAGE)
    got = {(d["date"], d["label"]) for d in watch.extract_dates(text)}
    assert ("2027-06-15", "paper") in got
    assert ("2027-07-20", "notification") in got
    assert ("2027-10-01", "event") in got
    assert ("2027-09-01", "registration") in got  # "đăng ký" needs the d-stroke folded to "d"
    ev = next(d["evidence"] for d in watch.extract_dates(text) if d["date"] == "2027-06-15")
    assert "Hạn nộp toàn văn" in ev  # evidence keeps the original accents


def test_english_dates_labels_and_invalid_dates():
    _, text = watch.visible_text(EN_PAGE)
    got = [(d["date"], d["label"]) for d in watch.extract_dates(text)]
    assert ("2027-01-05", "abstract") in got
    assert ("2027-01-12", "paper") in got
    assert ("2027-03-01", "notification") in got
    assert not any(d.startswith("2027-02-31") for d, _ in got)


def test_charset_from_meta_when_headers_omit_it():
    html = '<html><head><meta charset="utf-8"><title>Trang chủ</title></head><body>x</body></html>'.encode("utf-8")
    assert watch.visible_text(watch.decode_html(html, None))[0] == "Trang chủ"
    # A non-UTF-8 page declared only in <meta>: decoding as UTF-8 would garble it.
    latin = '<html><head><meta charset="windows-1252"><title>Café résumé</title></head><body>x</body></html>'.encode("cp1252")
    assert watch.visible_text(watch.decode_html(latin, None))[0] == "Café résumé"


def test_url_templates_cover_this_year_and_next():
    s = {"id": "r", "acronym": "R", "urls": ["https://a.example/"], "url_templates": ["https://r{year}.example/"]}
    assert watch.expand_urls(s, date(2026, 11, 22)) == ["https://a.example/", "https://r2026.example/", "https://r2027.example/"]


@pytest.mark.parametrize("bad, why", [
    ([{"acronym": "X", "urls": ["u"]}], "id"),
    ([{"id": "x", "acronym": "X"}], "urls"),
    ([{"id": "x", "acronym": "X", "url_templates": ["https://x.example/"]}], "template"),
    ([{"id": "x", "acronym": "X", "urls": ["u"]}, {"id": "x", "acronym": "Y", "urls": ["v"]}], "duplicate"),
])
def test_series_file_validation(tmp_path, bad, why):
    import yaml
    p = tmp_path / "s.yml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match=why):
        watch.load_series(p)


class FakeResponse:
    def __init__(self, status, body, url):
        self.status_code, self.content, self.url = status, body.encode("utf-8"), url
        self.headers = {"content-type": "text/html"}
        self.encoding = None


class FakeSession:
    """Serves pages from a dict; a value of None raises like a network failure."""
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **_):
        body = self.pages.get(url, "")
        if body is None:
            raise ConnectionError("no route")
        return FakeResponse(200 if body else 404, body or "not found", url)


SERIES = [{"id": "fair", "acronym": "FAIR", "urls": ["https://fair.example/"]},
          {"id": "down", "acronym": "DOWN", "urls": ["https://down.example/"]}]


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_history_appends_only_on_change(tmp_path):
    t1 = datetime(2026, 11, 22, tzinfo=timezone.utc)
    pages = {"https://fair.example/": VI_PAGE, "https://down.example/": None}
    r1 = watch.run(SERIES, tmp_path, FakeSession(pages), t1)
    assert (r1["pages"], len(r1["changed"]), r1["errors"]) == (2, 1, 1)
    assert r1["changed"][0]["first_seen"] is True
    assert len(lines(tmp_path / "history" / "fair.jsonl")) == 1
    assert len(lines(tmp_path / "history" / "down.jsonl")) == 1  # the failure is recorded once

    # Same content a week later: no new history lines, last_checked moves, last_changed stays.
    t2 = datetime(2026, 11, 29, tzinfo=timezone.utc)
    r2 = watch.run(SERIES, tmp_path, FakeSession(pages), t2)
    assert r2["changed"] == []
    assert len(lines(tmp_path / "history" / "fair.jsonl")) == 1
    st = json.loads((tmp_path / "status.json").read_text())["fair"]["pages"]["https://fair.example/"]
    assert st["last_checked"].startswith("2026-11-29") and st["last_changed"].startswith("2026-11-22")

    # The page changes: one more line, reported with its labelled dates.
    pages["https://fair.example/"] = VI_PAGE.replace("15/06/2027", "30/06/2027")
    t3 = datetime(2026, 12, 6, tzinfo=timezone.utc)
    r3 = watch.run(SERIES, tmp_path, FakeSession(pages), t3)
    assert len(r3["changed"]) == 1 and not r3["changed"][0]["first_seen"]
    assert ("2027-06-30", "paper") in {(d["date"], d["label"]) for d in r3["changed"][0]["dates"]}
    assert len(lines(tmp_path / "history" / "fair.jsonl")) == 2

    # The site comes back: the recovery is a change too.
    pages["https://down.example/"] = EN_PAGE
    r4 = watch.run(SERIES, tmp_path, FakeSession(pages), datetime(2026, 12, 13, tzinfo=timezone.utc))
    assert [c["series"] for c in r4["changed"]] == ["down"]
    assert len(lines(tmp_path / "history" / "down.jsonl")) == 2


def test_issue_lists_changes_and_says_dates_are_unpublished(tmp_path):
    r = watch.run(SERIES[:1], tmp_path, FakeSession({"https://fair.example/": VI_PAGE}),
                  datetime(2026, 11, 22, tzinfo=timezone.utc))
    md = watch.issue_markdown(r)
    assert "not published" in md and "**2027-06-15** (paper)" in md and "https://fair.example/" in md
