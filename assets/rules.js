// SPDX-License-Identifier: MIT
// Declarative rule packs for research points and bonuses.
//
// A rule pack is JSON written from an official document (a state council list or a
// university regulation). It never contains code: conditions are data, evaluated
// here against the facts of one publication. Every result names the rule that
// produced it, so a lecturer can check it against the document line by line.

export const FACTS = {
  kind: { type: "enum", values: ["journal", "conference", "book_chapter"] },
  year: { type: "number" },
  wos_index: { type: "enum", values: ["SCI", "SCIE", "SSCI", "AHCI", "ESCI", "none"] },
  impact_factor: { type: "number" },
  scopus_quartile: { type: "enum", values: ["Q1", "Q2", "Q3", "Q4", "none"] },
  scopus_indexed: { type: "bool" },
  core_rank: { type: "enum", values: ["A*", "A", "B", "C", "none"] },
  conference_scope: { type: "enum", values: ["international", "national"] },
  international_journal: { type: "bool" },
  issn_online: { type: "bool" },
  has_isbn: { type: "bool" },
  peer_reviewed: { type: "bool" },
  full_paper: { type: "bool" },
  nafosted_list: { type: "bool" },
  reputable_publisher: { type: "bool" },
  institution_journal: { type: "bool" },
  series: { type: "string" },
  hdgsnn_max: { type: "number" },
};

const OPS = ["eq", "ne", "in", "gte", "gt", "lte", "lt", "known"];

/** Validate a condition tree; returns a list of problems (empty when valid). */
export function checkCondition(cond, path = "when") {
  if (!cond || typeof cond !== "object" || Array.isArray(cond)) return [`${path}: condition must be an object`];
  if ("all" in cond || "any" in cond) {
    const key = "all" in cond ? "all" : "any";
    if (!Array.isArray(cond[key]) || !cond[key].length) return [`${path}.${key}: needs a non-empty list`];
    return cond[key].flatMap((c, i) => checkCondition(c, `${path}.${key}[${i}]`));
  }
  if ("not" in cond) return checkCondition(cond.not, `${path}.not`);
  if (!(cond.fact in FACTS)) return [`${path}: unknown fact ${JSON.stringify(cond.fact)}`];
  const ops = Object.keys(cond).filter((k) => k !== "fact");
  if (ops.length !== 1 || !OPS.includes(ops[0])) return [`${path}: needs exactly one operator out of ${OPS.join(", ")}`];
  if (ops[0] === "in" && !Array.isArray(cond.in)) return [`${path}: "in" needs a list`];
  return [];
}

/**
 * Evaluate a condition. Returns true, false, or null when a fact it needs is missing;
 * a missing fact never counts as a match, but it is reported so the user can fill it.
 */
export function evaluate(cond, facts, missing = new Set()) {
  if ("all" in cond) {
    let unknown = false;
    for (const c of cond.all) {
      const r = evaluate(c, facts, missing);
      if (r === false) return false;
      if (r === null) unknown = true;
    }
    return unknown ? null : true;
  }
  if ("any" in cond) {
    let unknown = false;
    for (const c of cond.any) {
      const r = evaluate(c, facts, missing);
      if (r === true) return true;
      if (r === null) unknown = true;
    }
    return unknown ? null : false;
  }
  if ("not" in cond) {
    const r = evaluate(cond.not, facts, missing);
    return r === null ? null : !r;
  }
  const v = facts[cond.fact];
  if ("known" in cond) return (v !== undefined && v !== null && v !== "") === cond.known;
  if (v === undefined || v === null || v === "") { missing.add(cond.fact); return null; }
  if ("eq" in cond) return v === cond.eq;
  if ("ne" in cond) return v !== cond.ne;
  if ("in" in cond) return cond.in.includes(v);
  if (typeof v !== "number") return false;
  if ("gte" in cond) return v >= cond.gte;
  if ("gt" in cond) return v > cond.gt;
  if ("lte" in cond) return v <= cond.lte;
  if ("lt" in cond) return v < cond.lt;
  return false;
}

/** Value of a list entry for a publication year: the last step that has started. */
export function valueForYear(history, year) {
  let value = null;
  for (const step of history || []) {
    if (step.from == null || (year != null && year >= step.from)) value = step.max;
  }
  return value;
}

const normIssn = (s) => String(s || "").toUpperCase().replace(/[^0-9X]/g, "");
const normName = (s) => String(s || "").toLowerCase().replace(/\u0111/g, "d").normalize("NFKD")
  .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();  // lower-case first: "D-stroke" has no NFKD form

/** Find a publication's venue in a pack's list, by ISSN first, then by exact normalised name. */
export function findInList(pack, facts) {
  const list = pack.list || [];
  const issns = (facts.issn || "").split(/[\s,;/]+/).map(normIssn).filter((x) => x.length === 8);
  if (issns.length) {
    const hit = list.find((e) => (e.issn || []).some((i) => issns.includes(normIssn(i))));
    if (hit) return { entry: hit, by: "issn" };
  }
  const name = normName(facts.venue);
  if (name) {
    const hit = list.find((e) => [e.name, ...(e.aliases || [])].some((n) => normName(n) === name));
    if (hit) return { entry: hit, by: "name" };
  }
  return null;
}

/**
 * Score one publication with one pack.
 * policy "max": every rule is evaluated and the highest value applies (how bonus
 * tables are read: one award per paper, the best tier it qualifies for).
 * Returns {value, rule, matched, unknown, missing, listHit}.
 */
export function scorePublication(pack, facts) {
  const matched = [], unknown = [];
  const missing = new Set();
  let listHit = null;
  if (pack.list && pack.list.length) {
    const found = findInList(pack, facts);
    if (found) {
      const v = valueForYear(found.entry.history, facts.year);
      listHit = { ...found, value: v };
      if (v != null) matched.push({ id: `list:${found.entry.id}`, label: found.entry.name, value: v, from: "list" });
    }
  }
  for (const rule of pack.rules || []) {
    if (rule.manual) continue;
    const m = new Set();
    const r = evaluate(rule.when, facts, m);
    if (r === true) matched.push({ id: rule.id, label: rule.label, value: rule.value, note: rule.note });
    else if (r === null) { unknown.push({ id: rule.id, label: rule.label, value: rule.value, needs: [...m] }); m.forEach((f) => missing.add(f)); }
  }
  matched.sort((a, b) => b.value - a.value);
  const best = matched[0] || null;
  // A rule that could beat the best match if a missing fact were filled is worth showing.
  const couldBeat = unknown.filter((u) => !best || u.value > best.value);
  // Only facts that could raise the result are reported as missing.
  const needed = [...new Set(couldBeat.flatMap((u) => u.needs))];
  return { value: best ? best.value : 0, rule: best, matched, unknown: couldBeat, missing: needed, listHit };
}

/** Rules that need a person-level decision (e.g. a bonus range) and are never summed. */
export function manualRules(pack) {
  return (pack.rules || []).filter((r) => r.manual);
}

/** Check a whole pack; returns problems (empty when valid). */
export function checkPack(pack) {
  const p = [];
  if (!pack || typeof pack !== "object") return ["pack is not an object"];
  for (const k of ["id", "title", "unit"]) if (!pack[k]) p.push(`missing ${k}`);
  if (!pack.source || !pack.source.document) p.push("source.document is required (which official text this pack transcribes)");
  const ids = new Set();
  (pack.rules || []).forEach((r, i) => {
    const w = `rules[${i}] (${r.id || "?"})`;
    if (!r.id) p.push(`${w}: missing id`);
    if (ids.has(r.id)) p.push(`${w}: duplicate id`);
    ids.add(r.id);
    if (!r.label) p.push(`${w}: missing label`);
    if (r.manual) {
      if (!r.range || !(r.range.min <= r.range.max)) p.push(`${w}: manual rule needs range {min, max}`);
      return;
    }
    if (typeof r.value !== "number" || r.value < 0) p.push(`${w}: value must be a non-negative number`);
    p.push(...checkCondition(r.when, `${w}.when`));
  });
  (pack.list || []).forEach((e, i) => {
    const w = `list[${i}] (${e.name || "?"})`;
    if (!e.id || !e.name) p.push(`${w}: needs id and name`);
    if (!Array.isArray(e.history) || !e.history.length) p.push(`${w}: needs a non-empty history`);
    else {
      const years = e.history.map((s) => (s.from == null ? -Infinity : s.from));
      if (years.some((y, j) => j && y <= years[j - 1])) p.push(`${w}: history steps must be in increasing year order`);
      if (e.history.some((s) => typeof s.max !== "number" || s.max < 0)) p.push(`${w}: every step needs max >= 0`);
    }
  });
  if (!(pack.rules || []).length && !(pack.list || []).length) p.push("pack has neither rules nor list");
  p.push(...checkTranslations(pack));
  return p;
}

// ---- Translations of a pack's text ------------------------------------------------

/** Numbers in a text, decimal comma read as a point, sorted: a translation must keep them all. */
export function numbersIn(s) {
  return (String(s || "").match(/\d+(?:[.,]\d+)?/g) || []).map((x) => x.replace(",", ".")).sort();
}

const sameNumbers = (a, b) => numbersIn(a).join("|") === numbersIn(b).join("|");

/**
 * Optional "translations": {"en": {...}} give the pack's text in another language: title,
 * unit_label, value_note, list_label, source.{document, warning}, ambiguities (same count),
 * rules: {id: {label, note}}, list: {id: {publisher, raw, notes}}. Every translated text must
 * carry the same numbers as the original, so a translation cannot change a threshold or a date.
 */
export function checkTranslations(pack) {
  const p = [];
  if (pack.language != null && !/^[a-z]{2}$/.test(pack.language)) p.push("language must be a two-letter code");
  const tr = pack.translations;
  if (tr == null) return p;
  if (typeof tr !== "object" || Array.isArray(tr)) return ["translations must be an object keyed by language"];
  const rules = new Map((pack.rules || []).map((r) => [r.id, r]));
  const list = new Map((pack.list || []).map((e) => [e.id, e]));
  const cmp = (w, orig, text) => {
    if (text == null) return;
    if (typeof text !== "string" || !text.trim()) p.push(`${w}: must be a non-empty text`);
    else if (orig == null) p.push(`${w}: translates a text the pack does not have`);
    else if (!sameNumbers(orig, text)) p.push(`${w}: numbers differ from the original (${numbersIn(orig).join(", ")} vs ${numbersIn(text).join(", ")})`);
  };
  for (const [lang, t] of Object.entries(tr)) {
    const w = `translations.${lang}`;
    if (!/^[a-z]{2}$/.test(lang)) p.push(`${w}: language must be a two-letter code`);
    if (!t || typeof t !== "object") { p.push(`${w}: must be an object`); continue; }
    for (const k of ["title", "unit_label", "value_note", "list_label"]) cmp(`${w}.${k}`, pack[k], t[k]);
    for (const k of ["document", "warning"]) cmp(`${w}.source.${k}`, pack.source?.[k], t.source?.[k]);
    if (t.ambiguities != null) {
      if (!Array.isArray(t.ambiguities) || t.ambiguities.length !== (pack.ambiguities || []).length) p.push(`${w}.ambiguities: needs one text per original`);
      else t.ambiguities.forEach((a, i) => cmp(`${w}.ambiguities[${i}]`, pack.ambiguities[i], a));
    }
    for (const [id, r] of Object.entries(t.rules || {})) {
      if (!rules.has(id)) { p.push(`${w}.rules.${id}: no rule with this id`); continue; }
      cmp(`${w}.rules.${id}.label`, rules.get(id).label, r.label);
      cmp(`${w}.rules.${id}.note`, rules.get(id).note, r.note);
    }
    for (const [id, e] of Object.entries(t.list || {})) {
      if (!list.has(id)) { p.push(`${w}.list.${id}: no list entry with this id`); continue; }
      const o = list.get(id);
      cmp(`${w}.list.${id}.publisher`, o.publisher, e.publisher);
      cmp(`${w}.list.${id}.raw`, o.raw, e.raw);
      if (e.notes != null) {
        if (!Array.isArray(e.notes) || e.notes.length !== (o.notes || []).length) p.push(`${w}.list.${id}.notes: needs one text per original`);
        else e.notes.forEach((n, i) => cmp(`${w}.list.${id}.notes[${i}]`, o.notes[i], n));
      }
    }
  }
  return p;
}

/**
 * The pack with its text in `lang` where a translation gives it; other text stays as written.
 * `inLang` says whether the text is in `lang` (written or translated), so the page can say the rest is in the
 * document's own language. Scoring is unaffected: only text changes.
 */
export function localizePack(pack, lang) {
  if (!pack) return pack;
  const t = pack.translations?.[lang];
  if (!t || lang === pack.language) return { ...pack, inLang: lang === pack.language };
  const pick = (a, b) => (b != null ? b : a);
  return {
    ...pack,
    inLang: true,
    title: pick(pack.title, t.title),
    unit_label: pick(pack.unit_label, t.unit_label),
    value_note: pick(pack.value_note, t.value_note),
    list_label: pick(pack.list_label, t.list_label),
    source: { ...pack.source, document: pick(pack.source?.document, t.source?.document), warning: pick(pack.source?.warning, t.source?.warning) },
    ambiguities: t.ambiguities || pack.ambiguities,
    rules: (pack.rules || []).map((r) => ({ ...r, label: pick(r.label, t.rules?.[r.id]?.label), note: pick(r.note, t.rules?.[r.id]?.note) })),
    list: pack.list && pack.list.map((e) => {
      const x = t.list?.[e.id] || {};
      return { ...e, publisher: pick(e.publisher, x.publisher), raw: pick(e.raw, x.raw), notes: pick(e.notes, x.notes) };
    }),
  };
}

// ---- Reading the point notation of HDGSNN lists ---------------------------------

/**
 * Parse the point notation of HDGSNN lists, e.g. "0-0,5; 0-0,75 tu 2019; 0-1,0 tu 2024"
 * or "0-1,0 (0-1,25 tu 2020)" or "0-0,50 (0 diem tu 2025)" ("tu" = from, "diem" = points), into
 * {history: [{from, max}], notes: [...]}. A segment without a year applies from the start.
 * Parenthesised text that carries no points (e.g. "(Scopus tu 2022)") becomes a note.
 */
export function parsePointHistory(raw) {
  // NFC first: text pasted from a PDF often arrives decomposed (NFD).
  const text = String(raw || "").normalize("NFC").replace(/[\u2013\u2014]/g, "-");
  const notes = [];
  const segments = [];
  const pieces = [];
  // Split off parenthesised groups, keep them as candidate segments or notes.
  let depth = 0, cur = "";
  for (const ch of text) {
    if (ch === "(") { if (depth === 0) { pieces.push({ t: cur, paren: false }); cur = ""; } depth++; continue; }
    if (ch === ")") { depth = Math.max(0, depth - 1); if (depth === 0) { pieces.push({ t: cur, paren: true }); cur = ""; } continue; }
    cur += ch;
  }
  pieces.push({ t: cur, paren: false });
  for (const { t, paren } of pieces) {
    for (const part of t.split(/[;/]/)) {
      const s = part.trim();
      if (!s) continue;
      const range = s.match(/(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)/);
      const zero = /^0\s*(?:\u0111|d)i(?:\u1ec3|e)m/i.test(s);  // "0 diem tu 2025": zero points from that year
      const year = s.match(/t(?:\u1eeb|u)\s*(?:n(?:\u0103|a)m\s*)?(\d{4})|from\s*(\d{4})/i);
      const from = year ? Number(year[1] || year[2]) : null;
      if (range) segments.push({ from, max: Number(range[2].replace(",", ".")) });
      else if (zero && from) segments.push({ from, max: 0 });
      else if (paren || s) notes.push(s);
    }
  }
  segments.sort((a, b) => (a.from ?? -Infinity) - (b.from ?? -Infinity));
  return { history: segments, notes };
}

/** Turn a pasted table (tab or semicolon separated) of a domestic journal list into list entries. */
export function parseListTable(text) {
  const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return { entries: [], errors: ["empty input"] };
  const sep = lines[0].includes("\t") ? "\t" : lines[0].includes(";") ? ";" : ",";
  const cells = lines.map((l) => l.split(sep).map((c) => c.trim()));
  const head = cells[0].map((h) => normName(h));
  const col = (...names) => head.findIndex((h) => names.some((n) => h.includes(n)));
  const iName = col("ten tap chi", "name", "journal", "title");
  const iIssn = col("issn");
  const iPub = col("co quan", "publisher", "xuat ban");
  const iPts = col("diem", "points");
  const iNo = col("tt", "stt", "no");
  if (iName < 0 || iPts < 0) return { entries: [], errors: ["header must name the journal column and the points column"] };
  const entries = [], errors = [];
  cells.slice(1).forEach((row, k) => {
    const name = row[iName];
    if (!name) return;
    const parsed = parsePointHistory(row[iPts]);
    if (!parsed.history.length) { errors.push(`row ${k + 2} (${name}): no points found in ${JSON.stringify(row[iPts])}`); return; }
    const issn = iIssn >= 0 ? (row[iIssn].match(/\d{4}-?\d{3}[\dXx]/g) || []) : [];
    entries.push({
      id: iNo >= 0 && row[iNo] ? `item-${row[iNo]}` : `row-${k + 2}`,
      name, issn, publisher: iPub >= 0 ? row[iPub] : "", history: parsed.history, notes: parsed.notes, raw: row[iPts],
    });
  });
  return { entries, errors };
}

/**
 * Score a publication with a points pack and a bonus pack. The points result feeds
 * the bonus pack as the fact hdgsnn_max: its value when a rule or list entry matched,
 * 0 when nothing could match, and unknown (null) when missing facts might change it.
 */
export function scoreWithPacks({ points, bonus }, facts) {
  const out = { points: null, bonus: null, facts: { ...facts } };
  if (points) {
    out.points = scorePublication(points, facts);
    const p = out.points;
    out.facts.hdgsnn_max = p.value > 0 ? p.value : (p.unknown.length ? null : 0);
  }
  if (bonus) out.bonus = scorePublication(bonus, out.facts);
  return out;
}
