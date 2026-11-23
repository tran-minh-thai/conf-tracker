// SPDX-License-Identifier: MIT
// Browser-run tests for assets/rules.js against the sample rule packs in data/rules/.
let R, hd, sch;

const base = { kind: "journal", year: 2025, international_journal: true, issn_online: true };
const conf = { kind: "conference", year: 2025, conference_scope: "international", full_paper: true, peer_reviewed: true, has_isbn: true };
const bonus = (facts) => R.scoreWithPacks({ points: hd, bonus: sch }, facts).bonus;
const points = (facts) => R.scorePublication(hd, facts);

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

export function run(rulesModule, packs) {
  R = rulesModule; hd = packs.points; sch = packs.bonus;
  const results = [];
  for (const [name, fn] of Object.entries(tests)) {
    try { fn(); results.push({ name, pass: true }); } catch (e) { results.push({ name, pass: false, error: e.message }); }
  }
  return results;
}
