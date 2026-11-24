// SPDX-License-Identifier: MIT
// Browser-run tests for assets/core.js. Open tests/core.test.html through a local server.
// run(core) takes the module under test so mutated copies can be checked too.
let core, match, fixtures;

const NOW = Date.parse("2026-11-22T12:00:00Z");
const conf = (over = {}) => ({
  id: "x27", acronym: "X", year: 2027, full_name: "X Conf", kind: "conference", sub: "DB", topic: "DB",
  rank: { ccf: "A", core: "A*" }, url: "https://x.example", timezone: "AoE", status: "confirmed",
  place: "Hanoi, Vietnam", city: "Hanoi", country: "Vietnam", mode: "in-person",
  event_start: "2027-06-01", event_end: "2027-06-03", accept_rates: [{ year: 2026, rate: 0.2 }],
  deadlines: [
    { type: "abstract", iso: "2026-11-20T11:59:59Z", comment: "" },
    { type: "paper", iso: "2026-11-27T11:59:59Z", comment: "" },
    { type: "notification", iso: "2027-02-01T11:59:59Z", comment: "" },
  ],
  ...over,
});

export const tests = {
  "open when a paper deadline is ahead"() {
    eq(core.submissionStatus(conf(), NOW), "open");
  },
  "closed when only notification is ahead"() {
    const c = conf({ deadlines: [{ type: "paper", iso: "2026-11-01T00:00:00Z" }, { type: "notification", iso: "2027-01-01T00:00:00Z" }] });
    eq(core.submissionStatus(c, NOW), "closed");
  },
  "estimated stays estimated even with future dates"() {
    eq(core.submissionStatus(conf({ status: "estimated" }), NOW), "estimated");
  },
  "boundary: a deadline exactly now counts as passed"() {
    const c = conf({ deadlines: [{ type: "paper", iso: new Date(NOW).toISOString() }] });
    eq(core.submissionStatus(c, NOW), "closed");
  },
  "default filter shows only open conferences"() {
    const list = [conf({ id: "o" }), conf({ id: "e", status: "estimated" }),
      conf({ id: "c", deadlines: [{ type: "paper", iso: "2026-01-01T00:00:00Z" }] }), conf({ id: "j", kind: "journal" })];
    const r = core.filterConfs(list, {}, NOW);
    eq(r.items.map((c) => c.id), ["o"]);
    eq(r.hidden, { closed: 1, estimated: 1, journals: 1 });
    eq(core.filterConfs(list, { showClosed: true, showEstimated: true, showJournals: true }, NOW).items.length, 4);
  },
  "rank, area, country, mode and text filters"() {
    const list = [conf({ id: "a" }), conf({ id: "b", rank: { ccf: null, core: "B" }, sub: "AI", country: "Japan", mode: "hybrid" }),
      conf({ id: "u", rank: { ccf: null, core: null } })];
    eq(core.filterConfs(list, { rankedOnly: true }, NOW).items.map((c) => c.id).sort(), ["a", "b"]);
    eq(core.filterConfs(list, { ccf: ["A"] }, NOW).items.map((c) => c.id), ["a"]);
    eq(core.filterConfs(list, { core: ["B"] }, NOW).items.map((c) => c.id), ["b"]);
    eq(core.filterConfs(list, { areas: ["AI"] }, NOW).items.map((c) => c.id), ["b"]);
    eq(core.filterConfs(list, { country: "Japan" }, NOW).items.map((c) => c.id), ["b"]);
    eq(core.filterConfs(list, { modes: ["hybrid"] }, NOW).items.map((c) => c.id), ["b"]);
    // Every fixture shares acronym X and place Hanoi; only "b" is in Japan. All terms must match.
    eq(core.filterConfs(list, { q: "hanoi x" }, NOW).items.length, 3);
    eq(core.filterConfs(list, { q: "x japan" }, NOW).items.map((c) => c.id), ["b"]);
    eq(core.filterConfs(list, { q: "nowhere" }, NOW).items.length, 0);
  },
  "deadline window uses the key deadline"() {
    const soon = conf({ id: "s" });
    const late = conf({ id: "l", deadlines: [{ type: "paper", iso: "2027-03-01T00:00:00Z" }] });
    eq(core.filterConfs([soon, late], { within: 7 }, NOW).items.map((c) => c.id), ["s"]);
  },
  "event date range overlap, including missing dates"() {
    const a = conf({ id: "a" }), b = conf({ id: "b", event_start: null, event_end: null });
    eq(core.filterConfs([a, b], { from: "2027-06-03" }, NOW).items.map((c) => c.id), ["a"]);
    eq(core.filterConfs([a, b], { from: "2027-06-04" }, NOW).items.length, 0);
    eq(core.filterConfs([a, b], { to: "2027-06-01" }, NOW).items.map((c) => c.id), ["a"]);
  },
  "sorting by deadline, rank and acceptance"() {
    const a = conf({ id: "a", deadlines: [{ type: "paper", iso: "2027-01-01T00:00:00Z" }], rank: { ccf: "C" }, accept_rates: [{ rate: 0.4 }] });
    const b = conf({ id: "b", deadlines: [{ type: "paper", iso: "2026-12-01T00:00:00Z" }], rank: { core: "A*" }, accept_rates: [{ rate: 0.1 }] });
    const c = conf({ id: "c", deadlines: [{ type: "paper", iso: "2026-12-15T00:00:00Z" }], rank: {}, accept_rates: [] });
    eq(core.sortConfs([a, b, c], "deadline", NOW).map((x) => x.id), ["b", "c", "a"]);
    eq(core.sortConfs([a, b, c], "rank", NOW).map((x) => x.id), ["b", "a", "c"]);
    eq(core.sortConfs([a, b, c], "acceptance", NOW).map((x) => x.id), ["b", "a", "c"]);
  },
  "urgency buckets at their boundaries"() {
    const d = 86400000;
    eq([0, 1, 3 * d - 1, 3 * d, 7 * d, 30 * d].map(core.urgency), ["past", "critical", "critical", "soon", "month", "later"]);
  },
  "venue-time formatting for AoE, UTC offsets and Pacific time"() {
    const iso = "2027-01-16T11:59:59Z";
    ok(core.formatInZone(iso, "AoE", "en-GB").includes("15 Jan 2027, 23:59"), core.formatInZone(iso, "AoE", "en-GB"));
    ok(core.formatInZone(iso, "UTC+8", "en-GB").includes("16 Jan 2027, 19:59"));
    ok(core.formatInZone("2026-12-02T01:00:00Z", "PT", "en-GB").includes("1 Dec 2026, 17:00"));
    ok(core.formatInZone("2026-07-02T00:00:00Z", "PT", "en-GB").includes("1 Jul 2026, 17:00"));
    eq(core.fixedOffsetMinutes("UTC-5:30"), -330);
    eq(core.fixedOffsetMinutes("UTC"), 0);
    eq(core.fixedOffsetMinutes("PT"), null);
  },
  "URL state round trip keeps only non-defaults"() {
    const s = { ...core.DEFAULT_STATE, q: "graph mining", areas: ["DB", "AI"], ccf: ["A"], rankedOnly: true, within: 30 };
    const enc = core.encodeState(s);
    ok(!enc.includes("showClosed") && !enc.includes("sort="), enc);
    const dec = core.decodeState(enc);
    eq(dec.q, "graph mining"); eq(dec.areas, ["DB", "AI"]); eq(dec.ccf, ["A"]); eq(dec.rankedOnly, true); eq(dec.within, 30);
    eq(core.encodeState(core.DEFAULT_STATE), "");
    eq(core.decodeState("bogus=1&within=-5").within, 0);
  },
  "escaping and URL safety"() {
    eq(core.escapeHtml(`<img src=x onerror="a">&'`), "&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;");
    eq(core.safeUrl("javascript:alert(1)"), "");
    eq(core.safeUrl("not a url"), "");
    eq(core.safeUrl("https://a.example/x?y=1"), "https://a.example/x?y=1");
  },
  "ICS: only future deadlines, escaped, folded, with alarms"() {
    const c = conf({ full_name: "Long, name; with\\stuff " + "z".repeat(120) });
    const { text, count } = core.buildIcs([c], NOW);
    eq(count, 2);
    ok(text.includes("SUMMARY:X 2027: Paper deadline"));
    ok(text.includes("Long\\, name\\; with\\\\stuff"));
    ok(text.split("\r\n").every((l) => new TextEncoder().encode(l).length <= 75), "line longer than 75 octets");
    ok(text.includes("TRIGGER:-P7D") && text.includes("TRIGGER:-P1D"));
    ok(text.includes("DTSTART:20261127T115959Z"));
    eq(core.buildIcs([conf({ status: "estimated" })], NOW).text.includes("(estimated)"), true);
  },
  "ICS fold reaches exactly 75 octets on ASCII"() {
    const f = core.icsFold("DESCRIPTION:" + "x".repeat(300));
    eq(Math.max(...f.split("\r\n").map((l) => l.length)), 75);
    eq(f.replace(/\r\n /g, ""), "DESCRIPTION:" + "x".repeat(300));
  },
  "CSV quotes commas and quotes"() {
    const csv = core.buildCsv([conf({ full_name: 'A "quoted", name' })], NOW);
    ok(csv.includes('"A ""quoted"", name"'));
    eq(csv.split("\r\n")[1].split(",")[0], "X");
  },
  "where filter: home, abroad, and online/TBD in neither"() {
    const list = [conf({ id: "vn" }), conf({ id: "jp", country: "Japan" }), conf({ id: "on", country: "Online", mode: "online" }),
      conf({ id: "tbd", country: "TBD" })];
    const ids = (s, home) => core.filterConfs(list, s, NOW, { home }).items.map((c) => c.id).sort();
    eq(ids({ where: "home" }, "Vietnam"), ["vn"]);
    eq(ids({ where: "abroad" }, "Vietnam"), ["jp"]);
    eq(ids({ where: "" }, "Vietnam"), ["jp", "on", "tbd", "vn"]);
    eq(ids({ where: "home" }, ""), []);  // unknown location: the filter cannot match anything
  },
  "city and conference level filters"() {
    const list = [conf({ id: "h" }), conf({ id: "d", city: "Da Nang" }), conf({ id: "n", scope: "national" })];
    eq(core.filterConfs(list, { city: "Da Nang" }, NOW).items.map((c) => c.id), ["d"]);
    eq(core.filterConfs(list, { level: "national" }, NOW).items.map((c) => c.id), ["n"]);
    eq(core.filterConfs(list, { level: "international" }, NOW).items.map((c) => c.id).sort(), ["d", "h"]);
  },
  "hidden counts only venues that pass the other filters"() {
    const list = [conf({ id: "a" }), conf({ id: "b", acronym: "Y", full_name: "Y Conf", deadlines: [{ type: "paper", iso: "2026-01-01T00:00:00Z" }] })];
    eq(core.filterConfs(list, { q: "x" }, NOW).hidden.closed, 0);
    eq(core.filterConfs(list, { q: "y" }, NOW).hidden.closed, 1);
  },
  "match sort orders by score"() {
    const list = [conf({ id: "a" }), conf({ id: "b" }), conf({ id: "c" })];
    const scores = new Map([["a", 0.1], ["b", 0.9], ["c", 0.5]]);
    eq(core.filterConfs(list, { sort: "match" }, NOW, { scores }).items.map((c) => c.id), ["b", "c", "a"]);
  },
  "fee summary shows the lowest fee per currency"() {
    const fees = { items: [{ amount: 520, currency: "USD" }, { amount: 350, currency: "USD" }, { amount: 8000000, currency: "VND" }] };
    eq(core.feeSummary(fees, "en-GB"), "350 USD · 8,000,000 VND");
    eq(core.feeSummary(null, "en-GB"), "");
    eq(core.feeSummary({ items: [] }, "en-GB"), "");
  },
  "tokenizer agrees with the Python fixture"() {
    match.setStopwords(fixtures.stopwords);
    for (const c of fixtures.cases) eq(match.tokens(c.text), c.tokens);
  },
  "match vectors: cosine ranking and shared terms"() {
    match.setStopwords(fixtures.stopwords);
    const idf = { graph: 2, neural: 2, network: 1.5, graph_neural: 3, pattern: 2, utility: 3 };
    const q = match.textVector("Graph neural networks", idf);
    const gnn = new Map([["graph", 0.6], ["graph_neural", 0.8]]), spm = new Map([["pattern", 0.6], ["utility", 0.8]]);
    ok(match.dot(q, gnn) > match.dot(q, spm), "graph query should prefer the graph venue");
    eq(match.dot(q, spm), 0);
    eq(match.topShared(q, gnn, 2), ["graph neural", "graph"]);
    const norm = [...q.values()].reduce((s, w) => s + w * w, 0);
    ok(Math.abs(norm - 1) < 1e-9, "query vector not normalised");
    eq(match.textVector("", idf).size, 0);
  },
  "term specificity follows the shared formula"() {
    const u = fixtures.paper.specificity_unit;
    const got = match.termSpecificity(u.vectors.map((v) => new Map(v.map((t) => [t, 1]))));
    eq([...got.keys()].sort(), Object.keys(u.expected).sort());
    for (const [t, w] of Object.entries(u.expected)) ok(Math.abs(got.get(t) - w) < 1e-12, `specificity of ${t}`);
  },
  "paper query and ranking agree with the Python fixture"() {
    const f = fixtures.paper;
    match.setStopwords(f.stopwords);
    const spec = new Map(Object.entries(f.specificity));
    const vecs = Object.entries(f.profiles).map(([k, p]) => [k, new Map(Object.entries(p.terms))]);
    for (const c of f.cases) {
      const q = match.paperVector(c.fields, f.idf, spec);
      eq([...q.keys()].sort(), Object.keys(c.query).sort());
      for (const [t, w] of Object.entries(c.query)) ok(Math.abs(q.get(t) - w) < 1e-12, `${c.name}: weight of ${t}`);
      const ranked = vecs.map(([k, v]) => [k, match.dot(q, v)]).filter(([, s]) => s > 0)
        .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
      eq(ranked.map(([k]) => k), c.ranking.map(([k]) => k));
      ranked.forEach(([, s], i) => ok(Math.abs(s - c.ranking[i][1]) < 1e-12, `${c.name}: score ${i}`));
    }
    match.setStopwords(fixtures.stopwords);
  },
  "high-utility abstract ranks database venues above theory venues"() {
    const f = fixtures.paper, c = f.cases.find((x) => x.name.startsWith("high-utility"));
    match.setStopwords(f.stopwords);
    const q = match.paperVector(c.fields, f.idf, new Map(Object.entries(f.specificity)));
    const order = Object.entries(f.profiles).map(([k, p]) => [k, match.dot(q, new Map(Object.entries(p.terms)))])
      .sort((a, b) => b[1] - a[1]).map(([k]) => k);
    for (const db of ["edbt", "dexa"]) for (const th of ["soda", "coco", "stoc"]) ok(order.indexOf(db) < order.indexOf(th), `${db} above ${th}`);
    match.setStopwords(fixtures.stopwords);
  },
  "channel ranking agrees with the Python fixture"() {
    const f = fixtures.channels;
    match.setStopwords(f.set.stopwords);
    for (const c of f.cases) {
      const data = JSON.parse(JSON.stringify(f.set));
      const got = [...match.fusedScores(c.text, data)].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
      eq(got.map(([k]) => k), c.ranking.map(([k]) => k));
      got.forEach(([, s], i) => ok(Math.abs(s - c.ranking[i][1]) < 1e-12, `${c.name}: score ${i}`));
      for (const [k, terms] of Object.entries(c.shared)) eq(match.channelSharedTerms(c.text, data, k, 4), terms);
    }
    match.setStopwords(fixtures.stopwords);
  },
  "plan import validates entries"() {
    const good = { plan: { a: { status: "submitted", title: "T", snapshot: { acronym: "A" } }, b: { status: "weird", snapshot: { acronym: "B" } }, c: {} } };
    const r = core.parsePlanImport(JSON.stringify(good));
    eq(Object.keys(r.plan).sort(), ["a", "b"]);
    eq(r.plan.b.status, "considering");
    eq(r.errors.length, 1);
    eq(core.parsePlanImport("{oops").plan, null);
    eq(core.parsePlanImport("[1,2]").plan, null);
  },
};

function eq(a, b) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`expected ${sb}, got ${sa}`);
}
function ok(cond, msg = "assertion failed") {
  if (!cond) throw new Error(msg);
}

export function run(module, matchModule, fixtureData) {
  core = module;
  match = matchModule;
  fixtures = fixtureData;
  const results = [];
  for (const [name, fn] of Object.entries(tests)) {
    try { fn(); results.push({ name, pass: true }); } catch (e) { results.push({ name, pass: false, error: e.message }); }
  }
  return results;
}
