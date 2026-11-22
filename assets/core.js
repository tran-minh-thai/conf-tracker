// SPDX-License-Identifier: MIT
// Pure logic for the tracker: no DOM access, so it can be tested in isolation.

export const DEADLINE_TYPES = ["abstract", "paper", "rebuttal", "notification"];
export const CCF_RANKS = ["A", "B", "C"];
export const CORE_RANKS = ["A*", "A", "B", "C"];
export const PLAN_STATUSES = ["considering", "writing", "submitted", "review", "accepted", "rejected", "withdrawn"];

export const DEFAULT_STATE = Object.freeze({
  q: "",
  areas: [],
  ccf: [],
  core: [],
  rankedOnly: false,
  showEstimated: false,
  showClosed: false,
  showJournals: false,
  within: 0,          // days; 0 = any
  country: "",
  city: "",
  where: "",          // "" | "home" (held in the viewer's country) | "abroad"
  level: "",          // "" | "international" | "national" (national-level conference)
  modes: [],          // in-person | hybrid | online | tbd
  from: "",           // event date range, YYYY-MM-DD
  to: "",
  sort: "deadline",
});

const ARRAY_KEYS = ["areas", "ccf", "core", "modes"];
const BOOL_KEYS = ["rankedOnly", "showEstimated", "showClosed", "showJournals"];

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

export function safeUrl(value) {
  try {
    const u = new URL(String(value));
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : "";
  } catch {
    return "";
  }
}

const ms = (iso) => Date.parse(iso);

/** Paper deadlines still ahead of now. */
export function openPaperDeadlines(conf, now) {
  return (conf.deadlines || []).filter((d) => d.type === "paper" && ms(d.iso) > now);
}

/** "open": a paper deadline is ahead; "estimated": projected from last year; "closed": otherwise. */
export function submissionStatus(conf, now) {
  if (conf.status === "estimated") return "estimated";
  return openPaperDeadlines(conf, now).length ? "open" : "closed";
}

/** The next deadline of any type, or null. */
export function nextDeadline(conf, now) {
  return (conf.deadlines || []).find((d) => ms(d.iso) > now) || null;
}

/** The deadline used for sorting and urgency: next paper deadline, else next of any type. */
export function keyDeadline(conf, now) {
  return openPaperDeadlines(conf, now)[0] || nextDeadline(conf, now) || null;
}

export function isRanked(conf) {
  return Boolean(conf.rank && (conf.rank.ccf || conf.rank.core));
}

export function latestAcceptRate(conf) {
  const rows = conf.accept_rates || [];
  return rows.length ? rows[rows.length - 1] : null;
}

/** Urgency bucket for a time difference in milliseconds. */
export function urgency(diffMs) {
  if (diffMs <= 0) return "past";
  const days = diffMs / 86400000;
  if (days < 3) return "critical";
  if (days < 7) return "soon";
  if (days < 30) return "month";
  return "later";
}

export function countdownParts(diffMs) {
  const total = Math.max(0, Math.floor(diffMs / 60000));
  return { days: Math.floor(total / 1440), hours: Math.floor((total % 1440) / 60), minutes: total % 60 };
}

function haystack(c) {
  return [c.acronym, c.full_name, c.place, c.city, c.country, c.topic, c.year].join(" ").toLowerCase();
}

/**
 * Apply the filter state. ctx.home is the viewer's country; ctx.scores maps id to
 * a match score for the "match" sort. Returns the visible list and why others were hidden.
 */
export function filterConfs(confs, state, now, ctx = {}) {
  const s = { ...DEFAULT_STATE, ...state };
  const q = s.q.trim().toLowerCase();
  const terms = q ? q.split(/\s+/) : [];
  const hidden = { closed: 0, estimated: 0, journals: 0 };
  const out = [];
  for (const c of confs) {
    if (s.areas.length && !s.areas.includes(c.sub)) continue;
    if (s.rankedOnly && !isRanked(c)) continue;
    if (s.ccf.length && !s.ccf.includes(c.rank?.ccf)) continue;
    if (s.core.length && !s.core.includes(c.rank?.core)) continue;
    if (s.country && c.country !== s.country) continue;
    if (s.city && c.city !== s.city) continue;
    if (s.where === "home" && (!ctx.home || c.country !== ctx.home)) continue;
    // Abroad: held in a known other country; online and unannounced venues are neither.
    if (s.where === "abroad" && (!ctx.home || c.country === ctx.home || c.country === "Online" || c.country === "TBD")) continue;
    if (s.level && (c.scope || "international") !== s.level) continue;
    if (s.modes.length && !s.modes.includes(c.mode)) continue;
    if (s.within > 0) {
      const k = keyDeadline(c, now);
      if (!k || ms(k.iso) - now > s.within * 86400000) continue;
    }
    if (s.from || s.to) {
      if (!c.event_start) continue;
      const end = c.event_end || c.event_start;
      if (s.from && end < s.from) continue;
      if (s.to && c.event_start > s.to) continue;
    }
    if (terms.length) {
      const h = haystack(c);
      if (!terms.every((t) => h.includes(t))) continue;
    }
    // Status and kind come last so "hidden" counts only venues that match everything else.
    const status = submissionStatus(c, now);
    if (status === "closed" && !s.showClosed) { hidden.closed++; continue; }
    if (status === "estimated" && !s.showEstimated) { hidden.estimated++; continue; }
    if (c.kind === "journal" && !s.showJournals) { hidden.journals++; continue; }
    out.push(c);
  }
  return { items: sortConfs(out, s.sort, now, ctx.scores), hidden };
}

const RANK_SCORE = { "A*": 0, A: 1, B: 2, C: 3 };

function rankScore(c) {
  const ccf = c.rank?.ccf ? RANK_SCORE[c.rank.ccf] ?? 9 : 9;
  const core = c.rank?.core ? RANK_SCORE[c.rank.core] ?? 9 : 9;
  return Math.min(ccf === 1 ? 0.5 : ccf, core);  // CCF A counts between CORE A* and A
}

export function sortConfs(list, sort, now, scores) {
  const dl = (c) => { const k = keyDeadline(c, now); return k ? ms(k.iso) : Number.MAX_SAFE_INTEGER; };
  const byDl = (a, b) => dl(a) - dl(b) || a.acronym.localeCompare(b.acronym);
  const copy = [...list];
  if (sort === "event") {
    copy.sort((a, b) => (a.event_start || "9999").localeCompare(b.event_start || "9999") || byDl(a, b));
  } else if (sort === "rank") {
    copy.sort((a, b) => rankScore(a) - rankScore(b) || byDl(a, b));
  } else if (sort === "match" && scores) {
    copy.sort((a, b) => (scores.get(b.id) || 0) - (scores.get(a.id) || 0) || byDl(a, b));
  } else if (sort === "acceptance") {
    const r = (c) => latestAcceptRate(c)?.rate ?? 2;
    copy.sort((a, b) => r(a) - r(b) || byDl(a, b));
  } else {
    copy.sort(byDl);
  }
  return copy;
}

/** Counts per area for the current list of candidate venues. */
export function countBy(list, key) {
  const m = new Map();
  for (const c of list) m.set(c[key], (m.get(c[key]) || 0) + 1);
  return m;
}

// ---- Fees ------------------------------------------------------------------

/** Lowest listed fee per currency, e.g. "350 USD · 8,000,000 VND"; "" when no fees are known. */
export function feeSummary(fees, locale) {
  if (!fees || !fees.items || !fees.items.length) return "";
  const low = new Map();
  for (const f of fees.items) if (!low.has(f.currency) || f.amount < low.get(f.currency)) low.set(f.currency, f.amount);
  return [...low].map(([cur, amt]) => `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amt)} ${cur}`).join(" · ");
}

// ---- Time zones -------------------------------------------------------------

const NAMED = {
  PT: "America/Los_Angeles", PST: "America/Los_Angeles", PDT: "America/Los_Angeles",
  ET: "America/New_York", EST: "America/New_York", EDT: "America/New_York",
  CET: "Europe/Paris", CEST: "Europe/Paris", BST: "Europe/London",
};

/** Fixed offset in minutes for "AoE", "UTC", "UTC+8", "UTC-5:30"; null for named or unknown zones. */
export function fixedOffsetMinutes(label) {
  const k = String(label || "AoE").trim().toUpperCase();
  if (k === "AOE") return -720;
  if (k === "UTC" || k === "GMT" || k === "Z") return 0;
  const m = k.match(/^(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$/);
  if (!m) return null;
  const v = Number(m[2]) * 60 + Number(m[3] || 0);
  return m[1] === "+" ? v : -v;
}

/** Format an instant as wall-clock time in the venue's stated zone. */
export function formatInZone(iso, label, locale) {
  const date = new Date(iso);
  const opts = { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false };
  const named = NAMED[String(label || "").trim().toUpperCase()];
  if (named) {
    return `${new Intl.DateTimeFormat(locale, { ...opts, timeZone: named }).format(date)} ${label}`;
  }
  const off = fixedOffsetMinutes(label);
  if (off === null) return `${new Intl.DateTimeFormat(locale, { ...opts, timeZone: "UTC" }).format(date)} UTC`;
  const shifted = new Date(date.getTime() + off * 60000);
  return `${new Intl.DateTimeFormat(locale, { ...opts, timeZone: "UTC" }).format(shifted)} ${label || "AoE"}`;
}

export function formatLocal(iso, locale) {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

export function formatDay(day, locale) {
  if (!day) return "";
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatEventRange(c, locale) {
  if (!c.event_start) return c.date && !/^(tbd|tba|n\/a|na|none|-)?$/i.test(c.date.trim()) ? c.date : "";
  if (!c.event_end || c.event_end === c.event_start) return formatDay(c.event_start, locale);
  return `${formatDay(c.event_start, locale)} – ${formatDay(c.event_end, locale)}`;
}

/** Local calendar day (YYYY-MM-DD) of an instant in the viewer's zone. */
export function localDay(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ---- URL state ---------------------------------------------------------------

export function encodeState(state) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    const def = DEFAULT_STATE[k];
    if (def === undefined) continue;
    if (ARRAY_KEYS.includes(k)) { if (v.length) p.set(k, v.join(",")); continue; }
    if (BOOL_KEYS.includes(k)) { if (v !== def) p.set(k, v ? "1" : "0"); continue; }
    if (v !== def && v !== "" && v !== null) p.set(k, String(v));
  }
  return p.toString();
}

export function decodeState(query) {
  const p = new URLSearchParams(query);
  const s = { ...DEFAULT_STATE, areas: [], ccf: [], core: [], modes: [] };
  for (const [k, v] of p.entries()) {
    if (!(k in DEFAULT_STATE)) continue;
    if (ARRAY_KEYS.includes(k)) s[k] = v.split(",").filter(Boolean);
    else if (BOOL_KEYS.includes(k)) s[k] = v === "1";
    else if (k === "within") s.within = Math.max(0, Number(v) || 0);
    else s[k] = v;
  }
  return s;
}

// ---- Calendar export (RFC 5545) -------------------------------------------

const ICS_LABEL = { abstract: "Abstract deadline", paper: "Paper deadline", rebuttal: "Rebuttal deadline", notification: "Notification" };

export function icsEscape(v) {
  return String(v ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

export function icsFold(line) {
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 75) return line;
  const parts = [];
  let cur = "", size = 0, limit = 75;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > limit) { parts.push(cur); cur = ""; size = 0; limit = 74; }
    cur += ch; size += n;
  }
  parts.push(cur);
  return parts.join("\r\n ");
}

const stamp = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

/** Calendar text with one event per future deadline of each edition. */
export function buildIcs(confs, now, name = "Conference deadlines") {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//conf-tracker//deadlines//EN",
    "CALSCALE:GREGORIAN", "METHOD:PUBLISH", `X-WR-CALNAME:${icsEscape(name)}`];
  const dtstamp = stamp(new Date(now));
  let count = 0;
  for (const c of confs) {
    (c.deadlines || []).forEach((d, i) => {
      if (ms(d.iso) <= now) return;
      const t = stamp(new Date(d.iso));
      const summary = `${c.acronym} ${c.year}: ${ICS_LABEL[d.type] || d.type}${c.status === "estimated" ? " (estimated)" : ""}`;
      const desc = [c.full_name, d.comment, `Time zone stated by the venue: ${c.timezone || "AoE"}`, safeUrl(c.url)]
        .filter(Boolean).join("\n");
      lines.push("BEGIN:VEVENT", `UID:${c.id}-${d.type}-${i}@conf-tracker`, `DTSTAMP:${dtstamp}`,
        `DTSTART:${t}`, `DTEND:${t}`, `SUMMARY:${icsEscape(summary)}`, `DESCRIPTION:${icsEscape(desc)}`);
      if (c.place && c.place !== "TBD") lines.push(`LOCATION:${icsEscape(c.place)}`);
      if (safeUrl(c.url)) lines.push(`URL:${safeUrl(c.url)}`);
      for (const days of [7, 1]) {
        lines.push("BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${icsEscape(summary)}`, `TRIGGER:-P${days}D`, "END:VALARM");
      }
      lines.push("END:VEVENT");
      count++;
    });
  }
  lines.push("END:VCALENDAR");
  return { text: lines.map(icsFold).join("\r\n") + "\r\n", count };
}

// ---- CSV export ------------------------------------------------------------

export function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function buildCsv(confs, now) {
  const head = ["acronym", "year", "full_name", "area", "ccf", "core", "status", "abstract_deadline_utc",
    "paper_deadline_utc", "notification_utc", "venue_timezone", "event_start", "event_end", "city", "country",
    "mode", "latest_acceptance_rate", "url"];
  const rows = confs.map((c) => {
    const first = (type) => (c.deadlines || []).find((d) => d.type === type && ms(d.iso) > now)?.iso
      || (c.deadlines || []).filter((d) => d.type === type).slice(-1)[0]?.iso || "";
    const ar = latestAcceptRate(c);
    return [c.acronym, c.year, c.full_name, c.topic, c.rank?.ccf || "", c.rank?.core || "", submissionStatus(c, now),
      first("abstract"), first("paper"), first("notification"), c.timezone, c.event_start || "", c.event_end || "",
      c.city, c.country, c.mode, ar ? ar.rate : "", c.url];
  });
  return [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

// ---- Personal plan -----------------------------------------------------------

/** Snapshot of an edition kept in the plan, so it survives when it leaves the data. */
export function snapshot(c) {
  return {
    id: c.id, acronym: c.acronym, year: c.year, full_name: c.full_name, url: c.url, timezone: c.timezone,
    deadlines: c.deadlines, status: c.status, rank: c.rank, place: c.place, event_start: c.event_start,
    event_end: c.event_end, sub: c.sub, topic: c.topic, kind: c.kind, accept_rates: c.accept_rates,
  };
}

/** Validate an imported plan file. Returns {plan, errors}. */
export function parsePlanImport(text) {
  let data;
  try { data = JSON.parse(text); } catch { return { plan: null, errors: ["not valid JSON"] }; }
  const entries = data && typeof data === "object" ? (data.plan ?? data) : null;
  if (!entries || typeof entries !== "object" || Array.isArray(entries)) return { plan: null, errors: ["no plan object"] };
  const plan = {}, errors = [];
  for (const [id, e] of Object.entries(entries)) {
    if (!e || typeof e !== "object" || !e.snapshot || typeof e.snapshot.acronym !== "string") {
      errors.push(`entry ${id}: missing snapshot`);
      continue;
    }
    plan[id] = {
      status: PLAN_STATUSES.includes(e.status) ? e.status : "considering",
      title: String(e.title || "").slice(0, 300),
      notes: String(e.notes || "").slice(0, 5000),
      added: String(e.added || ""),
      snapshot: e.snapshot,
    };
  }
  return { plan, errors };
}
