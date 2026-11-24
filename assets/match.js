// SPDX-License-Identifier: MIT
// Topic matching between a researcher (interests, activity, paper abstract) and
// venues. Mirrors scripts/conftracker/profiles.py: same tokenizer, same weights.

let STOP = new Set();

export function setStopwords(list) {
  STOP = new Set(list || []);
}

function fold(text) {
  return String(text || "").replace(/\u0111/g, "d").replace(/\u0110/g, "D")
    .normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

export function stem(tok) {
  if (tok.length > 4 && tok.endsWith("ies")) return tok.slice(0, -3) + "y";
  if (tok.length > 4 && /(ss|x|ch|sh)es$/.test(tok)) return tok.slice(0, -2);
  if (tok.length > 3 && tok.endsWith("s") && !/(ss|us|is)$/.test(tok)) return tok.slice(0, -1);
  return tok;
}

export function tokens(text) {
  const words = fold(text).split(/[^a-z0-9]+/).filter(Boolean);
  const kept = words.map((w) => (w.length < 2 || /^\d+$/.test(w) || STOP.has(w) ? null : stem(w)));
  const out = kept.filter(Boolean);
  for (let i = 0; i + 1 < kept.length; i++) if (kept[i] && kept[i + 1]) out.push(`${kept[i]}_${kept[i + 1]}`);
  return out;
}

function normalize(vec) {
  let s = 0;
  for (const w of vec.values()) s += w * w;
  const n = Math.sqrt(s) || 1;
  for (const [t, w] of vec) vec.set(t, w / n);
  return vec;
}

/** Sublinear tf x idf over known terms, L2-normalised (same as query_vector in Python). */
export function textVector(text, idf) {
  const counts = new Map();
  for (const t of tokens(text)) if (idf[t] !== undefined) counts.set(t, (counts.get(t) || 0) + 1);
  const vec = new Map();
  for (const [t, k] of counts) vec.set(t, (1 + Math.log(k)) * idf[t]);
  return normalize(vec);
}

/**
 * Specificity of each term over a set of venue vectors (Maps):
 * (ln((N + 1) / (n + 1)) + 1) / (ln(N + 1) + 1), where n is the number of vectors holding the term.
 * A term held by one venue gets about 0.9, one held by every venue about 0.15.
 */
export function termSpecificity(vectors) {
  const n = new Map();
  let total = 0;
  for (const vec of vectors) {
    total++;
    for (const t of vec.keys()) n.set(t, (n.get(t) || 0) + 1);
  }
  const top = Math.log(total + 1) + 1;
  const out = new Map();
  for (const [t, k] of n) out.set(t, (Math.log((total + 1) / (k + 1)) + 1) / top);
  return out;
}

/** Exponent on termSpecificity in paperVector, chosen on held-out abstracts (evaluation/paper-matching-*.json). */
export const SPECIFICITY_EXPONENT = 0.5;

/**
 * Query for a paper: its fields (abstract, main contributions) joined as one text, so a short
 * field adds its terms to the counts instead of carrying as much weight as the whole abstract;
 * each term is then weighted by its specificity across venues and the vector renormalised.
 */
export function paperVector(fields, idf, specificity) {
  const vec = textVector(fields.filter((f) => f && f.trim()).join("\n"), idf);
  for (const [t, w] of vec) vec.set(t, w * Math.pow(specificity.get(t) ?? 1, SPECIFICITY_EXPONENT));
  return normalize(vec);
}

/** Weighted sum of vectors, renormalised. parts: [{vec: Map, weight}] */
export function combine(parts) {
  const out = new Map();
  for (const { vec, weight } of parts) {
    if (!vec || !weight) continue;
    for (const [t, w] of vec) out.set(t, (out.get(t) || 0) + w * weight);
  }
  return normalize(out);
}

export function dot(a, b) {
  let s = 0;
  const [small, big] = a.size <= b.size ? [a, b] : [b, a];
  for (const [t, w] of small) { const v = big.get(t); if (v) s += w * v; }
  return s;
}

/** Terms contributing most to a match, for the "why" explanation. */
export function topShared(a, b, n = 5) {
  const shared = [];
  for (const [t, w] of a) { const v = b.get(t); if (v) shared.push([t, w * v]); }
  return shared.sort((x, y) => y[1] - x[1]).slice(0, n).map(([t]) => t.replace(/_/g, " "));
}

/**
 * Vector of a venue: its DBLP title profile when one exists, otherwise its name,
 * area and curated keywords (much weaker; such matches are labelled in the UI).
 */
export function venueVector(conf, profiles, areaNames = {}) {
  const p = conf.dblp && profiles.profiles[conf.dblp];
  if (p) return { vec: new Map(Object.entries(p.terms)), basis: "titles", weight: 1 };
  const text = [conf.full_name, (conf.keywords || []).join(" "), areaNames[conf.sub] || conf.topic].join(" ");
  // A name has only a handful of terms, so after normalisation its cosine is inflated
  // compared with a 120-term title profile. Its score is scaled by how reliable name
  // matching measured in the held-out evaluation (see nameMatchWeight).
  return { vec: textVector(text, profiles.idf), basis: "name", weight: nameMatchWeight(profiles) };
}

/** MRR of name-only profiles divided by MRR of title profiles, from the published evaluation. */
export function nameMatchWeight(profiles) {
  const ev = profiles.evaluation || {};
  const name = ev.name_only_baseline?.mrr, title = ev.title_profiles?.mrr;
  return name > 0 && title > 0 ? Math.min(1, name / title) : 1;
}

// ---- ranking channels (data/venue_channels.json); mirrors scripts/conftracker/channels.py ----

function channelQuery(text, channel, phrase) {
  const qw = channel.query_weight;
  const counts = new Map();
  for (const t of tokens(text)) if (qw[t] !== undefined) counts.set(t, (counts.get(t) || 0) + 1);
  const q = new Map();
  for (const [t, x] of counts) q.set(t, (1 + Math.log(x)) * qw[t] * (t.includes("_") ? phrase : 1));
  return q;
}

function channelIndex(channel) {
  if (!channel._inv) {
    const inv = new Map();
    for (const [k, terms] of Object.entries(channel.venues)) {
      for (const [t, w] of Object.entries(terms)) {
        if (!inv.has(t)) inv.set(t, []);
        inv.get(t).push([k, w]);
      }
    }
    Object.defineProperty(channel, "_inv", { value: inv, enumerable: false });
  }
  return channel._inv;
}

/** One channel's score per venue (dblp key) for a text. */
export function channelScores(text, channel) {
  const q = channelQuery(text, channel, channel.phrase);
  const inv = channelIndex(channel);
  const sc = new Map();
  for (const [t, w] of q) for (const [k, x] of inv.get(t) || []) sc.set(k, (sc.get(k) || 0) + w * x);
  return sc;
}

/** Weighted sum of channel scores, each divided by the query's best score in that channel. */
export function fusedScores(text, data) {
  const out = new Map();
  for (const name of data.fusion.order) {
    const weight = data.fusion.weights[name] || 0;
    const sc = channelScores(text, data.channels[name]);
    let top = 0;
    for (const v of sc.values()) if (v > top) top = v;
    if (top <= 0 || weight === 0) continue;
    for (const [k, v] of sc) out.set(k, (out.get(k) || 0) + weight * v / top);
  }
  return out;
}

/** Terms contributing most to a venue's fused score, for the explanation shown with each result. */
export function channelSharedTerms(text, data, venue, n = 5) {
  const contrib = new Map();
  for (const name of data.fusion.order) {
    const weight = data.fusion.weights[name] || 0;
    const ch = data.channels[name];
    const q = channelQuery(text, ch, ch.phrase);
    const sc = channelScores(text, ch);
    let top = 0;
    for (const v of sc.values()) if (v > top) top = v;
    const terms = ch.venues[venue];
    if (top <= 0 || !terms) continue;
    for (const [t, w] of q) if (terms[t] !== undefined) contrib.set(t, (contrib.get(t) || 0) + weight * w * terms[t] / top);
  }
  return [...contrib].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, n).map(([t]) => t.replace(/_/g, " "));
}
