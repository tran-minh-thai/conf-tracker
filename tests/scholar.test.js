// SPDX-License-Identifier: MIT
// Browser-run tests for assets/scholar.js. Records mirror real Crossref responses (fields trimmed).
let S;

const JOURNAL = {
  DOI: "10.3390/sym14102032", type: "journal-article", title: ["An Efficient Algorithm for Mining Stable Periodic High-Utility Sequential Patterns"],
  author: [{ given: "Shiyong", family: "Xie" }, { given: "Long", family: "Zhao" }], "container-title": ["Symmetry"],
  publisher: "MDPI AG", ISSN: ["2073-8994"], "issn-type": [{ value: "2073-8994", type: "electronic" }],
  "published-online": { "date-parts": [[2022, 9, 28]] }, URL: "https://doi.org/10.3390/sym14102032",
};
const PROC = {
  DOI: "10.1109/ICDM.2013.148", type: "proceedings-article", title: ["Efficiently Mining Top-K High Utility Sequential Patterns"],
  author: [{ given: "Junfu", family: "Yin" }], "container-title": ["2013 IEEE 13th International Conference on Data Mining"],
  event: { name: "2013 IEEE International Conference on Data Mining (ICDM)" }, publisher: "IEEE",
  "published-print": { "date-parts": [[2013, 12]] },
};

export const tests = {
  "DOI extraction from links and text"() {
    eq(S.parseDoi("https://doi.org/10.1145/3292500.3330919."), "10.1145/3292500.3330919");
    eq(S.parseDoi("https://dl.acm.org/doi/10.1145/3292500.3330919?casa_token=x"), "10.1145/3292500.3330919");
    eq(S.parseDoi("see DOI:10.1007/978-3-030-47426-3_1)"), "10.1007/978-3-030-47426-3_1");
    eq(S.parseDoi("https://doi.org/10.1109%2FICDM.2013.148"), "10.1109/icdm.2013.148");
    eq(S.parseDoi("https://ieeexplore.ieee.org/document/9000000"), null);
    eq(S.parseDoi(""), null);
  },
  "Crossref journal record"() {
    const p = S.fromCrossref(JOURNAL);
    eq([p.title.slice(0, 13), p.venue, p.issn, p.month], ["An Efficient ", "Symmetry", ["2073-8994"], 9]);
    eq(p.facts, { kind: "journal", year: 2022, issn_online: true });
    eq(p.authors, ["Shiyong Xie", "Long Zhao"]);
  },
  "Crossref proceedings: missing ISBN stays unknown, not false"() {
    const p = S.fromCrossref(PROC);
    eq(p.facts, { kind: "conference", year: 2013 });
    ok(!("has_isbn" in p.facts), "absent ISBN must not become has_isbn=false");
    eq(S.fromCrossref({ ...PROC, ISBN: ["978-0-7695-5108-1"] }).facts.has_isbn, true);
    eq(p.doi, "10.1109/icdm.2013.148");
  },
  "print-only ISSN leaves the online ISSN unknown; unknown types give no kind"() {
    // EAAI: Crossref lists only the print ISSN 0952-1976, yet the journal has the online ISSN 1873-6769.
    eq(S.fromCrossref({ ...JOURNAL, "issn-type": [{ value: "0952-1976", type: "print" }] }).facts.issn_online, undefined);
    eq(S.fromCrossref({ ...JOURNAL, "issn-type": [] }).facts.issn_online, undefined);
    eq(S.fromCrossref({ ...JOURNAL, type: "posted-content" }).facts.kind, undefined);
  },
  "journal data: foreign publisher means international, two ISSNs mean an online one"() {
    const info = { journals: {
      eaai: { issn: ["0952-1976", "1873-6769"], country: "GB" },
      jaec: { issn: ["1859-2244", "2615-9767"], country: "VN" },
      tkde: { issn: ["1041-4347", "1558-2191", "2326-3865"], country: "US" },
      lone: { issn: ["1111-1111"], country: null } } };
    const idx = S.journalIndex(info);
    eq(S.journalFacts(idx, ["0952-1976"]), { international_journal: true, issn_online: true });
    eq(S.journalFacts(idx, ["18736769"]), { international_journal: true, issn_online: true });
    eq(S.journalFacts(idx, ["1859-2244"]), { issn_online: true });             // Vietnamese publisher: not stated
    eq(S.journalFacts(idx, ["1041-4347"]), { international_journal: true });   // three ISSNs: no online inference
    eq(S.journalFacts(idx, ["1111-1111"]), {});                                 // no country, one ISSN
    eq(S.journalFacts(idx, ["9999-9999"]), {});                                 // not in the data
    eq(S.journalFacts(idx, []), {});
  },
  "Scimago export: quartiles by ISSN, quotes, missing quartile"() {
    const csv = 'Rank;Sourceid;Title;Type;Issn;SJR;SJR Best Quartile\n1;123;"Journal; A";journal;"20738994, 1234567X";1,2;Q2\n2;124;Conf B;conference and proceedings;"00000001";0,1;-\n';
    const r = S.parseSjrCsv(String.fromCharCode(0xfeff) + csv, 2024);
    eq([r.rows, r.errors], [2, []]);
    eq(r.byIssn["2073-8994"], { q: "Q2", title: "Journal; A", type: "journal" });
    eq(r.byIssn["1234-567X"].q, "Q2");
    eq(r.byIssn["0000-0001"].q, "none");
    eq(S.sjrFacts(r, ["2073-8994"]), { scopus_indexed: true, scopus_quartile: "Q2", sjr_title: "Journal; A", sjr_year: 2024 });
    eq(S.sjrFacts(r, ["9999-9999"]), null);
    eq(S.parseSjrCsv("a;b\n1;2").errors.length, 1);
  },
  "conference series matching needs acronym and name overlap"() {
    const venues = [
      { acronym: "ICDM", full_name: "IEEE International Conference on Data Mining", rank: { core: "A*" } },
      { acronym: "PAKDD", full_name: "Pacific-Asia Conference on Knowledge Discovery and Data Mining", rank: { core: "B" } },
      { acronym: "ICDM", full_name: "International Conference on Disaster Management", rank: { core: null } },
    ];
    eq(S.guessSeries(S.fromCrossref(PROC), venues).full_name, "IEEE International Conference on Data Mining");
    eq(S.guessSeries({ event: "PAKDD 2020", venue: "Advances in Knowledge Discovery and Data Mining" }, venues).acronym, "PAKDD");
    eq(S.guessSeries({ event: "ICDM 2021", venue: "Proceedings on Something Else Entirely" }, venues), null);
    eq(S.guessSeries({ event: "", venue: "Symmetry" }, venues), null);
  },
  "academic period"() {
    eq(S.periodOf(2025, 10, 1), "2025");
    eq(S.periodOf(2025, 10, 9), "2025-2026");
    eq(S.periodOf(2025, 8, 9), "2024-2025");
    eq(S.periodOf(2025, null, 9), "2025");
    eq(S.periodOf(null, 3, 9), "");
  },
};

function eq(a, b) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`expected ${sb}, got ${sa}`);
}
function ok(c, m = "assertion failed") { if (!c) throw new Error(m); }

export function run(mod) {
  S = mod;
  const results = [];
  for (const [name, fn] of Object.entries(tests)) {
    try { fn(); results.push({ name, pass: true }); } catch (e) { results.push({ name, pass: false, error: e.message }); }
  }
  return results;
}
