// SPDX-License-Identifier: MIT
// A rule pack as a spreadsheet (CSV) a lecturer can fill in Excel and import back.
//
// Layout:
//   sep=,                       hint for Excel; skipped on import
//   @title,<text>               settings rows: first cell starts with "@"
//   @kind,points|bonus|hours    (also @unit, @unit_label, @language, @source, @warning, @value_note,
//                               @policy, @period_start_month, @share, @share_main, @quota)
//   No.,Rule,Value,Type,...     header: only the columns the table uses, named in the page language
//   # ...                       rows whose first cell starts with "#" are notes, skipped on import
//   1,Q1 journal,450,Journal article,...
// The header may name a column by its key (kind, wos_index, ...) or by its name in any language the
// caller passes as aliases, so files written before (key header, one column per fact) still import.
// A fact cell is a condition on that fact; empty means "any value". Cell syntax:
//   a          equals a                     a|b|c     one of
//   !a         differs from a               yes / no  for yes/no facts (also Co/Khong, true/false)
//   >=3  >3  <=3  <3  =3                    numbers; join several with &: >=2&<3
//   *          is known                     !*        is not known
// Values may be written as keys (journal) or as their names in the page language (Journal article).
// Rows sharing an id are alternatives: the rule holds when any of its rows holds; the export writes
// "or" in the value cell of such a row so it reads as one.
// A value written min..max makes a manual rule (a range decided case by case, never summed).
// The domestic journal list of a points pack is not part of the sheet; it keeps its own paste box.
import { FACTS, checkPack } from "./rules.js";

// Yes/no words: English and Vietnamese ("co"/"khong", with or without accents).
const BOOL_WORDS = { yes: true, true: true, co: true, "c\u00f3": true, no: false, false: false, khong: false, "kh\u00f4ng": false };
// Words an alternative row may carry in its value cell (English and Vietnamese, with or without accents).
const OR_WORDS = ["or", "ho\u1eb7c", "hoac"];
const FIXED = ["id", "label", "value", "note", "valid_from", "valid_until"];
const SETTINGS = ["kind", "id", "title", "language", "unit", "unit_label", "source", "warning", "checked", "value_note", "policy", "period_start_month", "share", "share_main", "quota"];
const NUM_OPS = [[">=", "gte"], ["<=", "lte"], [">", "gt"], ["<", "lt"], ["=", "eq"]];

/** Split CSV text into rows of cells; quoted cells may hold the separator, quotes and line breaks. */
export function parseCsv(text, sep) {
  const rows = [];
  let row = [], cell = "", q = false;
  const s = String(text || "").replace(/^\uFEFF/, "");
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) {
      if (ch === '"') { if (s[i + 1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += ch;
    } else if (ch === '"' && cell === "") q = true;
    else if (ch === sep) { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && s[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

const cellOut = (v, sep) => {
  const s = v == null ? "" : String(v);
  return s.includes(sep) || /["\r\n]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** Separator of a sheet: the "sep=" hint, else the first of tab / semicolon / comma found in the first row. */
function detectSep(text) {
  const first = String(text || "").replace(/^\uFEFF/, "").split(/\r?\n/, 1)[0];
  const hint = first.match(/^sep=(.)\s*$/i);
  if (hint) return { sep: hint[1], hinted: true };
  for (const c of ["\t", ";", ","]) if (first.includes(c)) return { sep: c, hinted: false };
  return { sep: ",", hinted: false };
}

// ---- export ----------------------------------------------------------------------------

/** Condition as alternatives of conjunctions of leaves; throws when it cannot be a sheet row. */
export function dnf(cond) {
  if ("all" in cond) {
    let acc = [[]];
    for (const c of cond.all) {
      const alts = dnf(c);
      acc = acc.flatMap((a) => alts.map((b) => [...a, ...b]));
    }
    return acc;
  }
  if ("any" in cond) return cond.any.flatMap(dnf);
  if ("not" in cond) {
    const n = cond.not;
    if (n.fact && "eq" in n) return [[{ fact: n.fact, ne: n.eq }]];
    if (n.fact && "ne" in n) return [[{ fact: n.fact, eq: n.ne }]];
    throw new Error("a 'not' around a group cannot be written as a sheet row");
  }
  return [[cond]];
}

const fmtNum = (n, dec) => (dec === "," ? String(n).replace(".", ",") : String(n));

/** A conjunction with each fact's numeric bounds reduced to the tightest lower and upper bound. */
function tighten(conj) {
  const lower = {}, upper = {};
  // A strict bound beats an inclusive one at the same number (> 2 is tighter than >= 2).
  const stronger = (a, b, side) => b == null || (side === "lo" ? a.v > b.v : a.v < b.v) || (a.v === b.v && a.strict && !b.strict);
  for (const l of conj) {
    for (const [op, side, strict] of [["gte", "lo", false], ["gt", "lo", true], ["lte", "hi", false], ["lt", "hi", true]]) {
      if (!(op in l)) continue;
      const box = side === "lo" ? lower : upper;
      const cand = { v: l[op], strict, leaf: l };
      if (stronger(cand, box[l.fact], side)) box[l.fact] = cand;
    }
  }
  return conj.filter((l) => {
    const lo = ["gte", "gt"].some((o) => o in l), hi = ["lte", "lt"].some((o) => o in l);
    if (lo) return lower[l.fact].leaf === l;
    if (hi) return upper[l.fact].leaf === l;
    return true;
  });
}

function leafText(leaf, dec, words, values) {
  const type = FACTS[leaf.fact]?.type;
  const val = (v) => (typeof v === "boolean" ? (v ? words.yes : words.no) : typeof v === "number" ? fmtNum(v, dec)
    : values?.[leaf.fact]?.[v] || String(v));
  if ("known" in leaf) return leaf.known ? "*" : "!*";
  if ("in" in leaf) return leaf.in.map(val).join("|");
  if ("ne" in leaf) return `!${val(leaf.ne)}`;
  if ("eq" in leaf) return type === "number" ? `=${val(leaf.eq)}` : val(leaf.eq);
  const [sym, op] = NUM_OPS.find(([, o]) => o in leaf);
  return `${sym}${val(leaf[op])}`;
}

/**
 * The pack as a sheet with only the columns the table uses (a table without rules gets every column,
 * as a template). Optional names in the page language: `labels` for column headers (key -> name),
 * `words` for yes / no / or, `values` for enum values ({fact: {key: name}}). Without them the sheet
 * uses keys. Throws when a condition cannot be written as rows (a "not" around a group).
 */
export function packToCsv(pack, { labels = null, words = null, values = null, help = null, sep = "," } = {}) {
  const dec = sep === "," ? "." : ",";
  const w = { yes: "yes", no: "no", or: "or", ...(words || {}) };
  const rules = pack.rules || [];
  const rows = [];
  for (const r of rules) {
    if (r.manual) { rows.push({ r, conj: null, first: true }); continue; }
    dnf(r.when).forEach((conj, k) => rows.push({ r, conj: tighten(conj), first: k === 0 }));
  }
  const used = new Set(rows.flatMap((x) => (x.conj || []).map((l) => l.fact)));
  const facts = Object.keys(FACTS).filter((f) => !rules.length || used.has(f));
  const fixed = FIXED.filter((k) => !rules.length || ["id", "label", "value"].includes(k)
    || (k === "note" && rules.some((r) => r.note)) || (k === "valid_from" && rules.some((r) => r.valid?.from))
    || (k === "valid_until" && rules.some((r) => r.valid?.until)));
  const out = [];
  for (const line of help || []) out.push([`# ${line}`]);
  const set = (k, v) => { if (v != null && v !== "") out.push([`@${k}`, v]); };
  set("kind", pack.kind); set("id", pack.id); set("title", pack.title); set("language", pack.language);
  set("unit", pack.unit); set("unit_label", pack.unit_label); set("source", pack.source?.document);
  set("warning", pack.source?.warning); set("checked", pack.source?.checked); set("value_note", pack.value_note);
  if (pack.policy && pack.policy !== "max") set("policy", pack.policy);   // "max" is what an absent policy means
  set("period_start_month", pack.period_start_month);
  if (pack.share) { set("share", pack.share.scheme); if (pack.share.main != null) set("share_main", fmtNum(pack.share.main, dec)); }
  if (pack.quota?.length) set("quota", pack.quota.map((q) => `${q.from || ""}=${fmtNum(q.hours, dec)}`).join("; "));
  out.push([]);
  out.push([...fixed, ...facts].map((k) => labels?.[k] || k));
  for (const { r, conj, first } of rows) {
    const cellOf = { id: r.id, label: first ? r.label : "",
      value: !first ? w.or : r.manual ? `${fmtNum(r.range.min, dec)}..${fmtNum(r.range.max, dec)}` : fmtNum(r.value, dec),
      note: first ? r.note || "" : "", valid_from: first ? r.valid?.from || "" : "", valid_until: first ? r.valid?.until || "" : "" };
    const byFact = {};
    for (const leaf of conj || []) (byFact[leaf.fact] ||= []).push(leafText(leaf, dec, w, values));
    out.push([...fixed.map((k) => cellOf[k]), ...facts.map((f) => (byFact[f] || []).join("&"))]);
  }
  // The sep= hint is written as is: quoting it (it holds the separator) would hide it from Excel.
  return `\uFEFFsep=${sep}\r\n` + out.map((row) => row.map((c) => cellOut(c, sep)).join(sep)).join("\r\n") + "\r\n";
}

/**
 * Column, yes/no/or and value names of the sheet in one language, from that language's string
 * table (keys sh_*, f_<fact>, v_<fact>_<value>, tri_yes, tri_no).
 */
export function sheetVocab(s) {
  const labels = { id: s.sh_id, label: s.sh_label, value: s.sh_value, note: s.sh_note, valid_from: s.sh_from, valid_until: s.sh_until };
  for (const k of Object.keys(FACTS)) labels[k] = s[`f_${k}`];
  const values = {};
  for (const [f, d] of Object.entries(FACTS)) {
    if (d.type !== "enum") continue;
    for (const v of d.values) if (s[`v_${f}_${v}`]) (values[f] ||= {})[v] = s[`v_${f}_${v}`];
  }
  return { labels, values, words: { yes: s.tri_yes, no: s.tri_no, or: s.sh_or } };
}

/**
 * Names the import accepts besides keys, from the vocabularies of every language the app speaks
 * (each {labels, words, values} as packToCsv takes them): column name -> key, value name -> key.
 */
export function sheetAliases(vocabs) {
  const norm = (s) => String(s || "").trim().toLowerCase();
  const columns = {}, values = {}, or = [...OR_WORDS], bools = { ...BOOL_WORDS };
  for (const v of vocabs || []) {
    for (const [k, name] of Object.entries(v.labels || {})) if (name && !(norm(name) in columns)) columns[norm(name)] = k;
    for (const [f, m] of Object.entries(v.values || {})) for (const [k, name] of Object.entries(m)) if (name) (values[f] ||= {})[norm(name)] = k;
    if (v.words?.or && !or.includes(norm(v.words.or))) or.push(norm(v.words.or));
    if (v.words?.yes) bools[norm(v.words.yes)] = true;
    if (v.words?.no) bools[norm(v.words.no)] = false;
  }
  return { columns, values, or, bools };
}

// ---- import ----------------------------------------------------------------------------

function parseNumber(s, dec) {
  const t = String(s).trim().replace(/\s/g, "");
  const n = Number(dec === "," ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, ""));
  return t !== "" && Number.isFinite(n) ? n : null;
}

/** One cell -> list of leaves, or an error text. */
function cellLeaves(fact, raw, dec, aliases) {
  const type = FACTS[fact].type;
  const leaves = [];
  for (const partRaw of String(raw).split("&")) {
    const part = partRaw.trim();
    if (!part) continue;
    if (part === "*" || part === "!*") { leaves.push({ fact, known: part === "*" }); continue; }
    if (type === "number") {
      const hit = NUM_OPS.find(([sym]) => part.startsWith(sym));
      const neg = part.startsWith("!");
      const body = hit ? part.slice(hit[0].length) : neg ? part.slice(1) : part;
      const n = parseNumber(body, dec);
      if (n == null) return `${fact}: "${part}" is not a number condition (examples: >=3, <0.75, =2025)`;
      leaves.push({ fact, [hit ? hit[1] : neg ? "ne" : "eq"]: n });
      continue;
    }
    const neg = part.startsWith("!");
    const vals = (neg ? part.slice(1) : part).split("|").map((v) => v.trim()).filter(Boolean);
    const conv = [];
    for (const v of vals) {
      if (type === "bool") {
        const b = (aliases.bools || BOOL_WORDS)[v.toLowerCase()];
        if (b === undefined) return `${fact}: "${v}" should be yes or no`;
        conv.push(b);
      } else if (type === "enum") {
        const hit = FACTS[fact].values.find((x) => x.toLowerCase() === v.toLowerCase()) || aliases.values?.[fact]?.[v.toLowerCase()];
        if (!hit) return `${fact}: "${v}" is not one of ${FACTS[fact].values.join(", ")}`;
        conv.push(hit);
      } else conv.push(v);
    }
    if (!conv.length) return `${fact}: empty condition "${part}"`;
    if (neg && conv.length > 1) return `${fact}: "!" takes one value, not a list`;
    leaves.push(neg ? { fact, ne: conv[0] } : conv.length > 1 ? { fact, in: conv } : { fact, eq: conv[0] });
  }
  return leaves;
}

/**
 * Read a sheet back into a pack. `base` (optional) is the pack being replaced: its domestic journal
 * list and its kind are kept when the sheet does not say otherwise. `aliases` (from sheetAliases)
 * are the column and value names accepted besides keys. Returns {pack, errors}; the pack is null when
 * anything is wrong, and every error names its row (1-based, as Excel shows it).
 */
export function packFromCsv(text, base = null, aliases = sheetAliases([])) {
  const { sep, hinted } = detectSep(text);
  const rows = parseCsv(text, sep);
  const dec = sep === "," ? "." : ",";
  const errors = [];
  const settings = {};
  let header = null;
  const groups = new Map();
  rows.forEach((cells, i) => {
    const line = i + 1;
    const first = (cells[0] || "").trim();
    if (i === 0 && hinted) return;
    if (!cells.some((c) => c.trim())) return;
    if (first.startsWith("#")) return;
    if (first.startsWith("@")) {
      const key = first.slice(1).trim().toLowerCase();
      if (!SETTINGS.includes(key)) errors.push(`row ${line}: unknown setting @${key}`);
      else settings[key] = (cells[1] || "").trim();
      return;
    }
    if (!header) {
      header = cells.map((c) => { const k = c.trim().toLowerCase(); return FIXED.includes(k) || k in FACTS ? k : aliases.columns?.[k] || k; });
      const miss = ["id", "label", "value"].filter((k) => !header.includes(k));
      if (miss.length) { errors.push(`row ${line}: the header row needs the columns ${miss.join(", ")}`); header = []; }
      header.forEach((h, k) => { if (h && !FIXED.includes(h) && !(h in FACTS)) errors.push(`row ${line}: unknown column "${cells[k]}"`); });
      return;
    }
    if (!header.length) return;
    const get = (k) => { const j = header.indexOf(k); return j >= 0 ? (cells[j] || "").trim() : ""; };
    const id = get("id");
    if (!id) { errors.push(`row ${line}: id is empty`); return; }
    const leaves = [];
    for (const [j, h] of header.entries()) {
      if (!(h in FACTS) || !(cells[j] || "").trim()) continue;
      const got = cellLeaves(h, cells[j], dec, aliases);
      if (typeof got === "string") errors.push(`row ${line}: ${got}`); else leaves.push(...got);
    }
    const g = groups.get(id) || { line, label: "", value: "", note: "", from: "", until: "", alts: [] };
    // An alternative row may say "or" in its value cell instead of leaving it empty.
    const value = groups.has(id) && (aliases.or || OR_WORDS).includes(get("value").toLowerCase()) ? "" : get("value");
    for (const [k, v] of [["label", get("label")], ["value", value], ["note", get("note")], ["from", get("valid_from")], ["until", get("valid_until")]]) {
      if (!v) continue;
      if (g[k] && g[k] !== v) errors.push(`row ${line}: rule ${id} already has ${k === "from" || k === "until" ? `valid_${k}` : k} "${g[k]}" (row ${g.line}); repeat rows of a rule leave it empty`);
      else g[k] = v;
    }
    g.alts.push({ line, leaves });
    groups.set(id, g);
  });
  if (!header) errors.push("the sheet has no header row (id, label, value, ...)");
  const rules = [];
  for (const [id, g] of groups) {
    const r = { id, label: g.label };
    const range = g.value.match(/^(.+?)\.\.(.+)$/);
    if (range) {
      const min = parseNumber(range[1], dec), max = parseNumber(range[2], dec);
      if (min == null || max == null) errors.push(`row ${g.line}: range "${g.value}" needs two numbers, like 500000..2000000`);
      r.manual = true; r.range = { min, max };
      if (g.alts.some((a) => a.leaves.length)) errors.push(`row ${g.line}: rule ${id} has a range, so it takes no conditions`);
    } else {
      r.value = parseNumber(g.value, dec);
      if (r.value == null) errors.push(`row ${g.line}: rule ${id} needs a number in value (got "${g.value}")`);
      const empty = g.alts.find((a) => !a.leaves.length);
      if (empty) errors.push(`row ${empty.line}: rule ${id} has no condition; fill at least one fact column`);
      const alls = g.alts.map((a) => ({ all: a.leaves }));
      r.when = alls.length === 1 ? alls[0] : { any: alls };
    }
    if (g.note) r.note = g.note;
    if (g.from || g.until) r.valid = { ...(g.from ? { from: g.from } : {}), ...(g.until ? { until: g.until } : {}) };
    rules.push(r);
  }
  const S = settings;
  const pack = {
    schema_version: 1,
    ...(S.language || base?.language ? { language: S.language || base.language } : {}),
    id: S.id || base?.id || "my-table",
    kind: S.kind || base?.kind || "points",
    unit: S.unit || base?.unit || "",
    ...(S.unit_label ? { unit_label: S.unit_label } : {}),
    title: S.title || "",
    source: { document: S.source || "", ...(S.checked ? { checked: S.checked } : {}), ...(S.warning ? { warning: S.warning } : {}) },
    policy: S.policy || "max",
    ...(S.value_note ? { value_note: S.value_note } : {}),
    ...(base?.depends_on ? { depends_on: base.depends_on } : {}),
    rules,
  };
  if (S.period_start_month) pack.period_start_month = parseNumber(S.period_start_month, dec);
  if (S.share) {
    pack.share = { scheme: S.share };
    if (S.share_main) pack.share.main = parseNumber(S.share_main, dec);
  }
  if (S.quota) {
    pack.quota = S.quota.split(/[;\n]/).map((x) => x.trim()).filter(Boolean).map((x) => {
      const [from, hours] = x.split("=").map((y) => y.trim());
      return { ...(from ? { from } : {}), hours: parseNumber(hours, dec) };
    });
  }
  if (base?.list?.length) { pack.list = base.list; if (base.list_label) pack.list_label = base.list_label; }
  errors.push(...checkPack(pack).filter((e) => !errors.some((x) => x.endsWith(e))));
  return { pack: errors.length ? null : pack, errors };
}
