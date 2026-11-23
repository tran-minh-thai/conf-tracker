// SPDX-License-Identifier: MIT
// Browser-run tests for assets/rules.js against the sample rule packs in data/rules/.
let R, hd, sch, hr, C, E;

const base = { kind: "journal", year: 2025, international_journal: true, issn_online: true };
const conf = { kind: "conference", year: 2025, conference_scope: "international", full_paper: true, peer_reviewed: true, has_isbn: true };
const bonus = (facts) => R.scoreWithPacks({ points: hd, bonus: sch }, facts).bonus;
const points = (facts) => R.scorePublication(hd, facts);
const hours = (facts) => R.scoreWithPacks({ points: hd, hours: hr }, facts).hours;
const clone = (x) => JSON.parse(JSON.stringify(x));
// Every combination of a few values per fact the samples test: scoring must agree after a sheet round trip.
function factGrid() {
  const axes = {
    kind: ["journal", "conference", "book_chapter"], wos_index: ["SCIE", "ESCI", "none", undefined],
    scopus_quartile: ["Q1", "Q2", "Q4", "none"], impact_factor: [0, 2.5, 6], international_journal: [true, false],
    scopus_indexed: [true, false], conference_scope: ["international", "national"], has_isbn: [true, false],
    held_abroad: [true, false, undefined], year: [2018, 2026], month: [10, undefined],
  };
  let grid = [{ issn_online: true, full_paper: true, peer_reviewed: true }];
  for (const [k, vs] of Object.entries(axes)) grid = grid.flatMap((g) => vs.map((v) => (v === undefined ? g : { ...g, [k]: v })));
  return grid;
}

export const tests = {
  "translations: English text for both samples, numbers kept"() {
    for (const pk of [hd, sch]) {
      eq(pk.language, "vi");
      const en = R.localizePack(pk, "en");
      ok(en.inLang, "English text applied");
      ok(en.rules.every((r) => !/[\u0300-\u036f]|[\u0110\u0111]/.test(r.label.normalize("NFD").replace(/H\u0110GSNN/g, ""))), "a rule label is still Vietnamese");
      eq(R.localizePack(pk, "vi").inLang, true);
      eq(R.localizePack(pk, "vi").title, pk.title);
      eq(R.localizePack(pk, "fr").inLang, false);
      // Scoring reads conditions, not text: same results in both languages.
      eq(R.scorePublication(en, { ...base, wos_index: "SCIE", scopus_quartile: "Q1", impact_factor: 6 }).value,
         R.scorePublication(pk, { ...base, wos_index: "SCIE", scopus_quartile: "Q1", impact_factor: 6 }).value);
    }
    eq(R.localizePack(hd, "en").list.find((e) => e.id === "item-12").raw, "0\u20130.5; 0\u20130.75 from 2020; 0\u20131.0 from 2024 (Scopus from 2022)");
  },
  "translation checker catches injected faults"() {
    const broken = (f) => { const p = JSON.parse(JSON.stringify(hd)); f(p.translations.en, p); return R.checkTranslations(p).length > 0; };
    const faults = {
      "changed threshold": (t) => { t.rules["intl-q1-if5"].label = "SCI, SCIE and Scopus Q1, IF \u2265 4"; },
      "dropped year": (t) => { t.list["item-6"].raw = "0\u20130.5 from 2020; 0\u20130.75"; },
      "unknown rule id": (t) => { t.rules["no-such-rule"] = { label: "x" }; },
      "unknown list id": (t) => { t.list["item-99"] = { raw: "0" }; },
      "missing ambiguity": (t) => { t.ambiguities.pop(); },
      "empty title": (t) => { t.title = " "; },
      "bad language code": (t, p) => { p.translations.english = t; },
      "note without original": (t) => { t.rules["intl-q1"].note = "extra"; },
      "decimal changed in document": (t) => { t.source.document = t.source.document.replace("2025", "2024"); },
    };
    const missed = Object.entries(faults).filter(([, f]) => !broken(f)).map(([k]) => k);
    eq(missed, []);
    eq(R.numbersIn("0\u20131,25 t\u1eeb 2020"), R.numbersIn("0\u20131.25 from 2020"));
  },
  "both sample packs are valid"() {
    eq(R.checkPack(hd), []);
    eq(R.checkPack(sch), []);
  },
  "pack checker catches injected faults"() {
    const broken = (f) => { const p = JSON.parse(JSON.stringify(sch)); f(p); return R.checkPack(p).length > 0; };
    const faults = {
      "unknown fact": (p) => { p.rules[0].when.all[0].fact = "colour"; },
      "two operators": (p) => { p.rules[0].when.all[0].ne = "x"; },
      "negative value": (p) => { p.rules[0].value = -1; },
      "duplicate id": (p) => { p.rules[1].id = p.rules[0].id; },
      "manual without range": (p) => { delete p.rules[11].range; },
      "missing source": (p) => { delete p.source; },
      "empty all": (p) => { p.rules[0].when = { all: [] }; },
    };
    const missed = Object.entries(faults).filter(([, f]) => !broken(f)).map(([k]) => k);
    eq(missed, []);
    const h = JSON.parse(JSON.stringify(hd));
    h.list[0].history = [{ from: 2020, max: 1 }, { from: 2019, max: 1 }];
    ok(R.checkPack(h).some((x) => x.includes("increasing")), "unordered history not caught");
  },
  "point notation parser reproduces the hand transcription of all 18 list entries"() {
    for (const e of hd.list) {
      const got = R.parsePointHistory(e.raw);
      eq({ name: e.name, history: got.history }, { name: e.name, history: e.history });
    }
    eq(R.parsePointHistory("0 – 0,5 / 0 – 0,75 từ 2019").history, [{ from: null, max: 0.5 }, { from: 2019, max: 0.75 }]);
    eq(R.parsePointHistory("0–1,0; 0–1,25 từ 2020; 0–1,0 từ 2025 (ACI)").notes, ["ACI"]);
    eq(R.parsePointHistory("0–0,50 (0 điểm từ 2025)".normalize("NFD")).history.length, 2);
    eq(R.parsePointHistory("không rõ").history, []);
  },
  "list value follows the publication year"() {
    const vnu = hd.list.find((e) => e.issn.includes("2588-1086"));
    eq([2015, 2018, 2019, 2023, 2024, 2026].map((y) => R.valueForYear(vnu.history, y)), [0.5, 0.5, 0.75, 0.75, 1.0, 1.0]);
    const ato = hd.list.find((e) => e.name === "An toàn thông tin");
    eq(R.valueForYear(ato.history, 2019), null);   // not listed before 2020
    const utt = hd.list.find((e) => e.name === "Ứng dụng Toán học");
    eq(R.valueForYear(utt.history, 2025), 0);      // dropped to zero from 2025
  },
  "HDGSNN international journals: tiers and IF boundaries"() {
    const v = (f) => points({ ...base, wos_index: "SCIE", scopus_quartile: "Q1", ...f }).value;
    eq(v({ impact_factor: 5 }), 3.0);
    eq(v({ impact_factor: 4.99 }), 2.5);
    eq(v({ impact_factor: 3 }), 2.5);
    eq(v({ impact_factor: 2.99 }), 2.0);
    eq(points({ ...base, wos_index: "SCIE", scopus_quartile: "Q2", impact_factor: 9 }).value, 1.75);
    eq(points({ ...base, wos_index: "SCI", scopus_quartile: "Q3" }).value, 1.5);
    eq(points({ ...base, scopus_quartile: "Q4", wos_index: "none" }).value, 1.0);
  },
  "HDGSNN literal reading: Scopus Q1 without SCI/SCIE is not the Q1 tier"() {
    eq(points({ ...base, wos_index: "none", scopus_quartile: "Q1" }).value, 1.0);  // other international journal, online ISSN
    eq(points({ ...base, wos_index: "none", scopus_quartile: "none", issn_online: false }).value, 0.75);
  },
  "HDGSNN missing IF is reported as a fact that could raise the score"() {
    const r = points({ ...base, wos_index: "SCIE", scopus_quartile: "Q1" });
    eq(r.value, 2.0);
    ok(r.missing.includes("impact_factor"), "impact_factor not reported as missing");
    eq(r.unknown.map((u) => u.id).sort(), ["intl-q1-if3", "intl-q1-if5"]);
  },
  "HDGSNN conferences and national conferences"() {
    eq(points({ ...conf, core_rank: "A*" }).value, 1.5);
    eq(points({ ...conf, core_rank: "A" }).value, 1.25);
    eq(points({ ...conf, core_rank: "B" }).value, 1.0);
    eq(points({ ...conf, core_rank: "A*", has_isbn: false }).value, 0);
    const nat = { ...conf, conference_scope: "national" };
    eq(points({ ...nat, year: 2016 }).value, 0);
    eq(points({ ...nat, year: 2017 }).value, 0.5);
    eq(points({ ...nat, year: 2018, series: "FAIR" }).value, 0.5);
    eq(points({ ...nat, year: 2019, series: "FAIR" }).value, 0.75);
  },
  "HDGSNN domestic list by ISSN and by name"() {
    const r = points({ kind: "journal", year: 2024, international_journal: false, issn: "1859-0209" });
    eq([r.value, r.listHit.by], [1.0, "issn"]);
    const n = points({ kind: "journal", year: 2020, international_journal: false, venue: "Tin hoc va Dieu khien hoc (J. of Comp. Sci. and Cybernetics)" });
    eq([n.value, n.listHit.by], [1.25, "name"]);
  },
  "school bonus: IF boundaries and best tier wins"() {
    const b = (f) => bonus({ ...base, wos_index: "SCIE", scopus_quartile: "none", ...f }).value;
    eq(b({ impact_factor: 3.0 }), 32000000);
    eq(b({ impact_factor: 2.999 }), 22000000);
    eq(b({ impact_factor: 2.0 }), 22000000);
    eq(b({ impact_factor: 1.0 }), 16000000);
    eq(b({ impact_factor: 0.999 }), 12000000);
    // IF = 0 fails row 5 (0 < IF), but the journal still has an ISSN, so HDGSNN gives
    // it 0.75 as "another international journal", which meets row 11.
    const zero = bonus({ ...base, wos_index: "SCIE", scopus_quartile: "none", impact_factor: 0, issn_online: false });
    ok(!zero.matched.some((m) => m.id === "5"), "row 5 matched with IF = 0");
    eq([zero.value, zero.rule.id], [1500000, "11"]);
    eq(b({ impact_factor: 2.5, scopus_quartile: "Q1" }), 22000000);
    eq(bonus({ ...base, wos_index: "none", scopus_quartile: "Q2" }).value, 12000000);
    eq(bonus({ ...base, wos_index: "none", scopus_quartile: "Q3" }).value, 9000000);
    eq(bonus({ ...base, wos_index: "ESCI", scopus_quartile: "none" }).value, 6000000);
    eq(bonus({ ...base, wos_index: "none", scopus_quartile: "none", nafosted_list: true }).value, 6000000);
  },
  "school bonus: proceedings, book chapters, HDGSNN threshold chaining"() {
    eq(bonus({ ...conf, scopus_indexed: true, scopus_quartile: "Q4" }).value, 6000000);
    eq(bonus({ ...conf, scopus_indexed: true, scopus_quartile: "none" }).value, 4000000);
    eq(bonus({ ...conf, scopus_indexed: false, scopus_quartile: "none" }).value, 0);
    eq(bonus({ kind: "book_chapter", year: 2025, reputable_publisher: true }).value, 4000000);
    // Domestic journal with 0.75 (KH CNTT&TT from 2024) -> row 11; 0.5 (same journal in 2021) -> nothing
    const dom = { kind: "journal", international_journal: false, issn: "2525-2224", wos_index: "none", scopus_quartile: "none" };
    eq(bonus({ ...dom, year: 2024 }).value, 1500000);
    eq(bonus({ ...dom, year: 2021 }).value, 0);
    eq(bonus({ ...dom, year: 2021, institution_journal: true }).value, 1500000);
  },
  "manual person-level rule is never summed"() {
    eq(R.manualRules(sch).map((r) => r.id), ["12"]);
    const r = bonus({ ...base, wos_index: "SCIE", impact_factor: 5 });
    ok(!r.matched.some((m) => m.id === "12"), "manual rule matched a paper");
  },
  "hours sample: valid, English text, values by category"() {
    eq(R.checkPack(hr), []);
    ok(R.localizePack(hr, "en").inLang, "English text applied");
    const j = { kind: "journal", year: 2025, month: 10, international_journal: true, issn_online: true };
    eq(hours({ ...j, wos_index: "SCIE", scopus_quartile: "Q1" }).value, 450);
    eq(hours({ ...j, wos_index: "AHCI", scopus_quartile: "Q4" }).value, 260);
    eq(hours({ ...j, wos_index: "ESCI", scopus_quartile: "none" }).value, 200);
    eq(hours({ ...j, wos_index: "none", scopus_quartile: "none", scopus_indexed: true }).value, 200);
    // State council points feed the hours pack: 0.75 (2024) -> rule 6, 0.5 (2021) -> rule 7.
    const dom = { kind: "journal", month: 5, international_journal: false, issn: "2525-2224", wos_index: "none", scopus_quartile: "none", scopus_indexed: false };
    eq([hours({ ...dom, year: 2024 }).value, hours({ ...dom, year: 2024 }).rule.id], [170, "6"]);
    eq([hours({ ...dom, year: 2021 }).value, hours({ ...dom, year: 2021 }).rule.id], [130, "7"]);
    const c = { kind: "conference", conference_scope: "international", has_isbn: true, year: 2025, month: 6 };
    eq(hours({ ...c, held_abroad: true }).value, 180);
    eq(hours({ ...c, held_abroad: false }).value, 150);
    const u = hours(c);
    eq(u.value, 0);
    ok(u.missing.includes("held_abroad"), "held_abroad not reported as missing");
  },
  "hours: a table that changes on a date"() {
    const nat = { kind: "conference", conference_scope: "national", has_isbn: true };
    eq(hours({ ...nat, year: 2026, month: 8 }).value, 90);
    eq(hours({ ...nat, year: 2026, month: 9 }).value, 60);
    eq(hours({ ...nat, year: 2025 }).value, 90);   // every month of 2025 is before the change
    eq(hours({ ...nat, year: 2027 }).value, 60);
    const amb = hours({ ...nat, year: 2026 });
    eq(amb.value, 0);
    ok(amb.missing.includes("month"), "month not reported as missing");
    eq(R.inEffect({ from: "2026-09-01" }, 2026, 9), true);
    eq(R.inEffect({ until: "2026-09-01" }, 2026, 9), false);
    eq(R.inEffect({ from: "2026-01-01", until: "2027-01-01" }, 2026, null), true);
    eq(R.inEffect({ from: "2026-09-01" }, null, 9), null);
    eq(R.inEffect(null, null, null), true);
  },
  "hours: author share, every case"() {
    const m = { share: { scheme: "main_plus_equal", main: 0.4 } };
    eq(R.authorShare(m, 1, undefined), { share: 1, missing: null });
    eq(R.authorShare(m, 4, "main").share.toFixed(6), "0.550000");
    eq(R.authorShare(m, 4, "co").share.toFixed(6), "0.150000");
    eq((R.authorShare(m, 4, "main").share + 3 * R.authorShare(m, 4, "co").share).toFixed(9), "1.000000000");
    eq(R.authorShare(m, 2, "main").share.toFixed(6), "0.700000");
    eq(R.authorShare(m, 3, undefined), { share: null, missing: "role" });
    eq(R.authorShare(m, 0, "main"), { share: null, missing: "authors" });
    eq(R.authorShare(m, 2.5, "main").missing, "authors");
    eq(R.authorShare({ share: { scheme: "equal" } }, 4, undefined), { share: 0.25, missing: null });
    eq(R.authorShare({ share: { scheme: "full" } }, 9, undefined).share, 1);
    eq(R.authorShare({}, undefined, undefined).share, 1);   // no share stated: whole value
  },
  "hours: quota and academic year"() {
    eq([2023, 2024, 2025, 2026, 2030].map((y) => R.quotaFor(hr, y)), [null, 160, 160, 210, 210]);
    eq(R.periodYear(2025, 10, 9), 2025);
    eq(R.periodYear(2025, 8, 9), 2024);
    eq(R.periodYear(2025, 9, 9), 2025);
    eq(R.periodYear(2025, null, 9), null);
    eq(R.periodYear(2025, null, 1), 2025);
    eq(R.periodYear(null, 5, 9), null);
  },
  "hours pack checker catches injected faults"() {
    const broken = (f) => { const p = clone(hr); f(p); return R.checkPack(p).length > 0; };
    const faults = {
      "unknown scheme": (p) => { p.share.scheme = "half"; },
      "main share above 1": (p) => { p.share.main = 1.2; },
      "main share missing": (p) => { delete p.share.main; },
      "quota out of order": (p) => { p.quota.reverse(); },
      "negative quota": (p) => { p.quota[0].hours = -5; },
      "bad quota date": (p) => { p.quota[0].from = "1/9/2024"; },
      "month 13": (p) => { p.period_start_month = 13; },
      "valid mid-month": (p) => { p.rules[10].valid.until = "2026-09-15"; },
      "valid until before from": (p) => { p.rules[10].valid = { from: "2027-01-01", until: "2026-01-01" }; },
      "empty valid": (p) => { p.rules[10].valid = {}; },
      "value not a number": (p) => { p.rules[0].value = NaN; },
    };
    eq(Object.entries(faults).filter(([, f]) => !broken(f)).map(([k]) => k), []);
  },
  "sheet round trip: all three samples score the same on every grid case"() {
    const grid = factGrid();
    for (const pk of [hd, sch, hr]) {
      for (const sep of [",", ";"]) {
        const csv = C.packToCsv(pk, { sep, labels: { id: "Mã", label: "Tên mục" }, help: ["Ghi chú, có dấu phẩy; và chấm phẩy", "@ không phải cài đặt"] });
        const { pack, errors } = C.packFromCsv(csv, pk);
        eq(errors, []);
        eq(pack.rules.map((r) => [r.id, r.label, r.value ?? r.range]), pk.rules.map((r) => [r.id, r.label, r.value ?? r.range]));
        eq([pack.share, pack.quota, pack.period_start_month, pack.kind, pack.title], [pk.share, pk.quota, pk.period_start_month, pk.kind, pk.title]);
        let n = 0;
        for (const f of grid) {
          const want = R.scoreWithPacks({ points: hd, bonus: pk.kind === "bonus" ? pk : null, hours: pk.kind === "hours" ? pk : null }, f);
          const got = R.scoreWithPacks({ points: pk.kind === "points" ? pack : hd, bonus: pk.kind === "bonus" ? pack : null, hours: pk.kind === "hours" ? pack : null }, f);
          const role = pk.kind === "points" ? "points" : pk.kind;
          eq(got[role].value, want[role].value);
          eq(got[role].missing, want[role].missing);
          n++;
        }
        ok(n > 10000, `only ${n} grid cases`);
      }
    }
  },
  "sheet import: Excel-style file, quoted cells, alternatives"() {
    const csv = "\uFEFF@kind;hours\r\n@title;Bảng thử\r\n@source;Quy định số 1\r\n@unit;hours\r\n@share;equal\r\n@quota;2025-09-01=150,5\r\n\r\n" +
      "id;label;value;kind;wos_index;impact_factor;scopus_indexed\r\n# Mã;Tên;Giờ;;;;\r\n" +
      "1;\"Bài WoS; IF \"\"cao\"\"\nhai dòng\";300,5;journal;SCIE|SSCI;>=2&<10;\r\n" +
      "2;Scopus hoặc ESCI;100;journal;ESCI;;\r\n2;;;journal;;;có\r\n";
    const { pack, errors } = C.packFromCsv(csv);
    eq(errors, []);
    eq(pack.rules[0].label, 'Bài WoS; IF "cao"\nhai dòng');
    eq(pack.rules[0].value, 300.5);
    eq(pack.quota, [{ from: "2025-09-01", hours: 150.5 }]);
    eq(pack.rules[0].when.all.find((l) => l.fact === "impact_factor" && "lt" in l).lt, 10);
    eq(pack.rules[1].when.any.length, 2);
    eq(R.scorePublication(pack, { kind: "journal", scopus_indexed: true, wos_index: "none" }).value, 100);
    eq(R.scorePublication(pack, { kind: "journal", wos_index: "SCIE", impact_factor: 12 }).value, 0);
  },
  "sheet import catches injected faults, each with its row"() {
    const good = C.packToCsv(hr);
    const lines = good.split("\r\n");
    const head = lines.findIndex((l) => l.startsWith("id,"));
    const row1 = lines.findIndex((l, i) => i > head && !l.startsWith("#"));   // first rule row, after the note rows
    const edit = (f) => { const ls = [...lines]; f(ls); return C.packFromCsv(ls.join("\r\n"), hr); };
    const cell = (ls, i, col, v) => { const c = C.parseCsv(ls[i], ",")[0]; c[C.parseCsv(ls[head], ",")[0].indexOf(col)] = v; ls[i] = c.map((x) => (/[,"\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x)).join(","); };
    const faults = {
      "unknown column": (ls) => { ls[head] = ls[head].replace("held_abroad", "held_abraod"); },
      "bad enum value": (ls) => cell(ls, row1, "scopus_quartile", "Q5"),
      "bad yes/no": (ls) => cell(ls, row1 + 8, "has_isbn", "maybe"),
      "bad number condition": (ls) => cell(ls, row1 + 5, "hdgsnn_max", ">=abc"),
      "value not a number": (ls) => cell(ls, row1, "value", "nhiều"),
      "conflicting label on repeat row": (ls) => cell(ls, row1 + 4, "label", "khác"),
      "row without condition": (ls) => { ls.splice(row1 + 1, 0, "99,Mục trống,10"); },
      "unknown setting": (ls) => { ls.splice(1, 0, "@colour,red"); },
      "empty id": (ls) => cell(ls, row1, "id", ""),
      "bad share": (ls) => { const i = ls.findIndex((l) => l.startsWith("@share,")); ls[i] = "@share,half"; },
      "no header": (ls) => { ls.splice(head); },
    };
    const missed = [], unnumbered = [];
    for (const [k, f] of Object.entries(faults)) {
      const { pack, errors } = edit(f);
      if (pack || !errors.length) missed.push(k);
      else if (!["bad share", "no header"].includes(k) && !errors.some((e) => /^row \d+/.test(e))) unnumbered.push(k);
    }
    eq(missed, []);
    eq(unnumbered, []);
    eq(C.packFromCsv(good, hr).errors, []);   // the unedited sheet is clean, so the faults above are what failed
  },
  "table editor: an untouched draft scores the same, edits keep translations honest"() {
    const grid = factGrid().filter((_, i) => i % 7 === 0);
    for (const pk of [hd, sch, hr]) {
      const back = E.fromDraft(E.toDraft(pk), pk);
      eq(R.checkPack(back), []);
      eq(E.draftProblems(E.toDraft(pk)), []);
      for (const f of grid) {
        const role = pk.kind === "points" ? "points" : pk.kind;
        const a = R.scoreWithPacks({ points: hd, [role]: pk }, f)[role], b = R.scoreWithPacks({ points: hd, [role]: back }, f)[role];
        eq([b.value, b.missing], [a.value, a.missing]);
      }
      eq(back.translations, pk.translations);   // nothing edited: every translation kept
    }
    const d = E.toDraft(hr);
    d.rules[0].label = "Q1 (sửa)"; d.title = "Bảng của tôi";
    const out = E.fromDraft(d, hr);
    ok(!out.translations.en.rules["1"], "stale English label kept for an edited rule");
    ok(!out.translations.en.title, "stale English title kept");
    eq(out.translations.en.rules["2"].label, hr.translations.en.rules["2"].label);
    eq(R.checkPack(out), []);
    const bad = (f) => { const x = E.toDraft(hr); f(x); return E.draftProblems(x).length > 0; };
    const faults = {
      "alternative with no condition": (x) => { x.rules[0]._alts[0] = []; },
      "rule with no alternative": (x) => { x.rules[0]._alts = []; },
      "one-of with nothing chosen": (x) => { x.rules[0]._alts[0][1].value = []; },
      "negative value": (x) => { x.rules[0].value = -1; },
      "duplicate id": (x) => { x.rules[1].id = x.rules[0].id; },
      "quota out of order": (x) => { x.quota.reverse(); },
      "empty label": (x) => { x.rules[2].label = ""; },
    };
    eq(Object.entries(faults).filter(([, f]) => !bad(f)).map(([k]) => k), []);
    ok(E.describeCondition(hr.rules[3].when, (k, p, fb) => fb || k).includes(" "), "condition text empty");
  },
  "pasted table import"() {
    const tsv = "TT\tTên tạp chí\tISSN\tCơ quan xuất bản\tĐiểm\n8\tVNU Journal of Science: CS & Comm. Eng.\tp-2615-9260 / e-2588-1086\tĐHQG Hà Nội\t0–0,5; 0–0,75 từ 2019; 0–1,0 từ 2024\n9\tX\t\t\tkhông có điểm";
    const r = R.parseListTable(tsv);
    eq(r.entries.length, 1);
    eq(r.entries[0].issn, ["2615-9260", "2588-1086"]);
    eq(r.entries[0].history.length, 3);
    eq(r.errors.length, 1);
    eq(R.parseListTable("a,b\n1,2").errors.length, 1);
  },
};

function eq(a, b) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`expected ${sb}, got ${sa}`);
}
function ok(c, m = "assertion failed") { if (!c) throw new Error(m); }

export function run(rulesModule, packs, csvModule, editModule) {
  R = rulesModule; hd = packs.points; sch = packs.bonus; hr = packs.hours; C = csvModule; E = editModule;
  const results = [];
  for (const [name, fn] of Object.entries(tests)) {
    try { fn(); results.push({ name, pass: true }); } catch (e) { results.push({ name, pass: false, error: e.message }); }
  }
  return results;
}
