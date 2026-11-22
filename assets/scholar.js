// SPDX-License-Identifier: MIT
// Publication metadata: DOI parsing, Crossref records, Scimago (SJR) exports.
// Pure functions, no DOM and no network: the caller fetches and passes JSON or text.

const BOM = String.fromCharCode(0xfeff);

/** Extract a DOI from a DOI, a doi.org link, or any URL or text containing one. */
export function parseDoi(input) {
  let s = String(input || "").trim();
  try { s = decodeURIComponent(s); } catch { /* keep as is */ }
  const m = s.match(/10\.\d{4,9}\/[^\s"'<>]+/i);
  if (!m) return null;
  // Trailing punctuation from a sentence or a URL fragment is not part of the DOI.
  return m[0].replace(/[).,;:\]}>]+$/, "").replace(/[?#].*$/, "").toLowerCase();
}

export const crossrefUrl = (doi) => `https://api.crossref.org/works/${encodeURIComponent(doi)}`;
export const crossrefSearchUrl = (q) =>
  `https://api.crossref.org/works?rows=5&select=DOI,title,container-title,issued,author,type&query.bibliographic=${encodeURIComponent(q)}`;

const KIND = {
  "journal-article": "journal",
  "proceedings-article": "conference",
  "book-chapter": "book_chapter",
  "book-part": "book_chapter",
  "book-section": "book_chapter",
};

/** [year, month|null] of the earliest stated publication date field. */
function firstDate(msg) {
  for (const k of ["published-print", "published-online", "published", "issued", "created"]) {
    const parts = msg[k]?.["date-parts"]?.[0] || [];
    if (Number.isInteger(parts[0])) return [parts[0], Number.isInteger(parts[1]) ? parts[1] : null];
  }
  return [null, null];
}

const fmtIssn = (s) => {
  const d = String(s || "").toUpperCase().replace(/[^0-9X]/g, "");
  return d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4)}` : "";
};

/**
 * Turn a Crossref work (the "message" object) into a publication record.
 * Only facts Crossref can state are filled; indexing (WoS, Scopus quartile, IF)
 * is left empty for the user or an SJR file to provide.
 */
export function fromCrossref(msg) {
  if (!msg || typeof msg !== "object") throw new Error("empty Crossref record");
  const issnTypes = msg["issn-type"] || [];
  const issn = [...new Set([...(msg.ISSN || []), ...issnTypes.map((x) => x.value)].map(fmtIssn).filter(Boolean))];
  const kind = KIND[msg.type] || null;
  const facts = {};
  if (kind) facts.kind = kind;
  const [year, month] = firstDate(msg);
  if (year) facts.year = year;
  if (issnTypes.some((x) => x.type === "electronic")) facts.issn_online = true;
  else if (issnTypes.length && issnTypes.every((x) => x.type === "print")) facts.issn_online = false;
  // Crossref often omits the ISBN of proceedings that have one, so absence is left
  // unknown for the user to confirm; only a listed ISBN counts as evidence.
  if ((msg.ISBN || []).length) facts.has_isbn = true;
  const venue = (msg["container-title"] || [])[0] || msg.event?.name || "";
  return {
    doi: String(msg.DOI || "").toLowerCase(),
    title: (msg.title || [])[0] || "",
    authors: (msg.author || []).map((a) => [a.given, a.family].filter(Boolean).join(" ") || a.name || "").filter(Boolean),
    venue,
    event: msg.event?.name || "",
    publisher: msg.publisher || "",
    issn,
    isbn: msg.ISBN || [],
    url: msg.URL || (msg.DOI ? `https://doi.org/${msg.DOI}` : ""),
    crossref_type: msg.type || "",
    month,
    facts,
  };
}

/** Split one CSV line with a given separator, honouring double quotes. */
export function splitCsvLine(line, sep) {
  const out = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') q = false;
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === sep) { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

/**
 * Parse a Scimago Journal Rank export (the "Download data" CSV, semicolon separated).
 * Returns {byIssn: {ISSN: {q, title, type}}, rows, year, errors}. Journals with
 * quartile "-" are kept as Scopus-indexed without a quartile.
 */
export function parseSjrCsv(text, year = null) {
  const lines = String(text || "").replace(BOM, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { byIssn: {}, rows: 0, year, errors: ["empty file"] };
  const sep = lines[0].includes(";") ? ";" : ",";
  const head = splitCsvLine(lines[0], sep).map((h) => h.trim().toLowerCase());
  const iIssn = head.indexOf("issn"), iQ = head.findIndex((h) => h.includes("best quartile"));
  const iTitle = head.indexOf("title"), iType = head.indexOf("type");
  if (iIssn < 0 || iQ < 0) return { byIssn: {}, rows: 0, year, errors: ["not a Scimago export: needs the Issn and SJR Best Quartile columns"] };
  const byIssn = {};
  let rows = 0;
  for (const line of lines.slice(1)) {
    const c = splitCsvLine(line, sep);
    const q = (c[iQ] || "").trim();
    const entry = { q: /^Q[1-4]$/.test(q) ? q : "none", title: (c[iTitle] || "").trim(), type: (c[iType] || "").trim() };
    let any = false;
    for (const raw of (c[iIssn] || "").split(/[,\s]+/)) {
      const issn = fmtIssn(raw);
      if (issn && !byIssn[issn]) { byIssn[issn] = entry; any = true; }
    }
    if (any) rows++;
  }
  return { byIssn, rows, year, errors: [] };
}

/** Facts an SJR table can supply for a publication's ISSNs, or null if none match. */
export function sjrFacts(sjr, issns) {
  if (!sjr || !sjr.byIssn) return null;
  for (const i of issns || []) {
    const e = sjr.byIssn[fmtIssn(i)];
    if (e) return { scopus_indexed: true, scopus_quartile: e.q, sjr_title: e.title, sjr_year: sjr.year };
  }
  return null;
}

/** Academic period of a publication year/month: calendar year or a school year starting in startMonth. */
export function periodOf(year, month, startMonth = 1) {
  if (!year) return "";
  if (startMonth <= 1 || !month) return String(year);
  return month >= startMonth ? `${year}-${year + 1}` : `${year - 1}-${year}`;
}

const words = (s) => new Set(String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").split(" ")
  .filter((w) => w.length > 2 && !["international", "conference", "ieee", "acm", "the", "and", "for", "proceedings", "annual", "workshop", "symposium"].includes(w)));

/**
 * Find the conference series of a proceedings paper among known venues, by an
 * acronym in the event or venue name plus overlapping name words (so a short
 * acronym alone never decides). Returns the venue or null.
 */
export function guessSeries(pub, venues) {
  const text = `${pub.event || ""} ${pub.venue || ""}`;
  const acronyms = new Set([...text.matchAll(/\(([A-Za-z][A-Za-z0-9&-]{1,15})\)|\b([A-Z][A-Z0-9&-]{2,15})\b/g)]
    .map((m) => (m[1] || m[2]).toUpperCase().replace(/[^A-Z0-9]/g, "")));
  const w = words(text);
  let best = null;
  for (const v of venues) {
    const a = String(v.acronym || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!a || !acronyms.has(a)) continue;
    const vw = words(v.full_name);
    const shared = [...vw].filter((x) => w.has(x)).length;
    const score = vw.size ? shared / vw.size : 0;
    if (score >= 0.5 && (!best || score > best.score)) best = { venue: v, score };
  }
  return best ? best.venue : null;
}
