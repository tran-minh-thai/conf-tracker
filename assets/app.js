// SPDX-License-Identifier: MIT
import {
  CCF_RANKS, CORE_RANKS, DEFAULT_STATE, PLAN_STATUSES, buildCsv, buildIcs, countBy, countdownParts,
  decodeState, encodeState, escapeHtml as h, feeSummary, filterConfs, formatEventRange, formatInZone,
  formatLocal, isRanked, keyDeadline, latestAcceptRate, localDay, nextDeadline, parsePlanImport, safeUrl,
  snapshot, submissionStatus, urgency,
} from "./core.js";
import { AREA_NAMES, makeT } from "./i18n.js";
import { CITIES, browserTimeZone, citiesOf, countryFromTimeZone, nearestCity } from "./geo.js";
import { combine, dot, paperVector as paperQuery, setStopwords, termSpecificity, textVector, topShared, venueVector } from "./match.js";
import { createPubs } from "./pubs.js";
import { scoreWithPacks } from "./rules.js";

const KEYS = {
  plan: "conf_tracker_plan_v1",
  legacy: "cs_conf_bookmarks",
  lang: "conf_tracker_lang",
  theme: "conf_tracker_theme",
  loc: "conf_tracker_location",
  profile: "conf_tracker_profile_v1",
  activity: "conf_tracker_activity_v1",
};
const STALE_DAYS = 2;
const MAX_SIGNALS = 60;
const VIEWS = ["list", "foryou", "calendar", "plan", "pubs"];
let pubs = null;  // publications view, created after the data loads

const $ = (sel) => document.querySelector(sel);

// ---- storage (every access guarded: private windows can throw) -------------
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
  },
  raw(key) { try { return localStorage.getItem(key); } catch { return null; } },
  setRaw(key, value) { try { localStorage.setItem(key, value); } catch { /* ignore */ } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};

// ---- application state -----------------------------------------------------
const app = {
  data: null,
  confs: [],
  byId: new Map(),
  areas: {},
  state: { ...DEFAULT_STATE },
  view: "list",
  calMonth: null,
  lang: "en",
  t: makeT("en"),
  plan: {},
  open: new Set(),
  loc: { country: "", city: "", source: "" },
  profile: { interests: "", learn: true, abstract: "", contrib: "", target: "venues" },
  watch: {},               // acronym -> watched pages (data/watch/status.json)
  journals: null,          // journal topic profiles, loaded on demand
  journalsState: "idle",
  activity: { searches: [], opened: [] },
  profiles: null,          // venue topic profiles, loaded on demand
  profilesState: "idle",   // idle | loading | ready | error
  venueVecs: new Map(),
  matchMode: "profile",    // which text the For you tab ranks by: profile | abstract
};

function detectLang() {
  const saved = store.raw(KEYS.lang);
  if (saved === "en" || saved === "vi") return saved;
  return (navigator.language || "").toLowerCase().startsWith("vi") ? "vi" : "en";
}
const locale = () => (app.lang === "vi" ? "vi-VN" : "en-GB");
const areaName = (code) => AREA_NAMES[app.lang]?.[code] || app.areas[code] || code;

// ---- URL hash: #view?filters ----------------------------------------------
function readHash() {
  const raw = location.hash.replace(/^#/, "");
  const [view, query = ""] = raw.split("?");
  if (VIEWS.includes(view)) app.view = view;
  app.state = decodeState(query);
}
function writeHash() {
  const q = encodeState(app.state);
  const next = `#${app.view}${q ? `?${q}` : ""}`;
  if (location.hash !== next) history.replaceState(null, "", next);
}

// ---- location ---------------------------------------------------------------
function loadLocation() {
  const saved = store.get(KEYS.loc, null);
  if (saved && typeof saved.country === "string" && saved.source) { app.loc = saved; return; }
  const country = countryFromTimeZone(browserTimeZone());
  app.loc = { country, city: "", source: country ? "timezone" : "" };
}
function saveLocation(loc) {
  app.loc = loc;
  store.set(KEYS.loc, loc);
  renderLocation();
  renderFilters();
  renderView();
}
function renderLocation() {
  const t = app.t, l = app.loc;
  const label = l.country ? `📍 ${[l.city, l.country].filter(Boolean).join(", ")}` : `📍 ${t("locUnknown")}`;
  $("#btn-loc").textContent = label;
  $("#btn-loc").title = l.source ? `${t("locTitle")}: ${t({ timezone: "locDetected", precise: "locPrecise", manual: "locManual" }[l.source])}` : t("locTitle");
}
function openLocationDialog() {
  const t = app.t;
  const countries = [...new Set([...app.confs.map((c) => c.country), ...CITIES.map((c) => c[1])])]
    .filter((c) => c && c !== "TBD" && c !== "Online").sort((a, b) => a.localeCompare(b));
  $("#loc-title").textContent = t("locTitle");
  $("#loc-note").textContent = t("locPreciseNote");
  $("#loc-precise").textContent = `🎯 ${t("locUsePrecise")}`;
  $("#loc-save").textContent = t("locSave");
  $("#loc-close").textContent = t("close");
  $("#loc-country-label").textContent = t("country");
  $("#loc-city-label").textContent = t("city");
  $("#loc-country").innerHTML = `<option value="">—</option>` +
    countries.map((c) => `<option ${c === app.loc.country ? "selected" : ""}>${h(c)}</option>`).join("");
  fillLocCities(app.loc.country, app.loc.city);
  $("#loc-status").textContent = "";
  $("#dlg-loc").showModal();
}
function fillLocCities(country, selected) {
  const cities = cityOptions(country);
  $("#loc-city").innerHTML = `<option value="">—</option>` +
    cities.map(({ name }) => `<option ${name === selected ? "selected" : ""}>${h(name)}</option>`).join("");
}
/** Cities of a country: those in the data plus the gazetteer, with venue counts. */
function cityOptions(country) {
  if (!country) return [];
  const counts = countBy(app.confs.filter((c) => c.country === country && c.city), "city");
  const names = new Set([...counts.keys(), ...citiesOf(country)]);
  return [...names].map((name) => ({ name, n: counts.get(name) || 0 })).sort((a, b) => a.name.localeCompare(b.name));
}

// ---- profile and activity ------------------------------------------------------
function loadPersonal() {
  const p = store.get(KEYS.profile, null);
  if (p && typeof p === "object") app.profile = { ...app.profile, ...p };
  const a = store.get(KEYS.activity, null);
  if (a && Array.isArray(a.searches) && Array.isArray(a.opened)) app.activity = a;
}
function saveProfile() { store.set(KEYS.profile, app.profile); }
function saveActivity() { store.set(KEYS.activity, app.activity); }
function recordSearch(q) {
  if (!app.profile.learn) return;
  const v = q.trim().toLowerCase();
  if (v.length < 3) return;
  const list = app.activity.searches.filter((x) => x !== v && !v.startsWith(x));
  list.push(v);
  app.activity.searches = list.slice(-MAX_SIGNALS);
  saveActivity();
}
function recordOpen(id) {
  if (!app.profile.learn) return;
  app.activity.opened = [...app.activity.opened.filter((x) => x !== id), id].slice(-MAX_SIGNALS);
  saveActivity();
}

// ---- matching --------------------------------------------------------------------
async function ensureProfiles() {
  if (app.profilesState === "ready" || app.profilesState === "loading") return;
  app.profilesState = "loading";
  try {
    const res = await fetch("data/venue_profiles.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    app.profiles = await res.json();
    setStopwords(app.profiles.stopwords);
    app.profiles.specificity = termSpecificity(Object.values(app.profiles.profiles).map((p) => new Map(Object.entries(p.terms))));
    app.profilesState = "ready";
  } catch (err) {
    console.error(err);
    app.profilesState = "error";
  }
  renderView();
}
async function ensureJournals() {
  if (app.journalsState === "ready" || app.journalsState === "loading") return;
  app.journalsState = "loading";
  try {
    const res = await fetch("data/journal_profiles.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    app.journals = await res.json();
    setStopwords(app.journals.stopwords);
    app.journals.vecs = Object.fromEntries(Object.entries(app.journals.profiles).map(([k, p]) => [k, new Map(Object.entries(p.terms))]));
    app.journals.specificity = termSpecificity(Object.values(app.journals.vecs));
    app.journalsState = "ready";
  } catch (err) {
    console.error(err);
    app.journalsState = "error";
  }
  renderView();
}
const normTitle = (s) => String(s || "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ")
  .replace(/\b(the|of|and|on|in|for|journal)\b/g, " ").replace(/\s+/g, " ").trim();
/** Scimago entries keyed by normalised title (DBLP gives journal names, not ISSNs). */
function sjrByTitle() {
  const sjr = pubs?.state.sjr;
  if (!sjr) return null;
  if (sjrByTitle.cache?.src === sjr) return sjrByTitle.cache.map;
  const map = new Map();
  for (const e of Object.values(sjr.byIssn)) if (e.title && !map.has(normTitle(e.title))) map.set(normTitle(e.title), e);
  sjrByTitle.cache = { src: sjr, map };
  return map;
}
/** Abstract plus main contributions as one query over the given profile set (venues or journals). */
function paperVector(set) {
  const v = paperQuery([app.profile.abstract, app.profile.contrib], set.idf, set.specificity);
  return v.size ? v : null;
}

function journalResults(t) {
  if (app.journalsState !== "ready") {
    if (app.journalsState === "idle") ensureJournals();
    return `<p class="empty">${h(t(app.journalsState === "error" ? "journalsError" : "journalsLoading"))}</p>`;
  }
  const q = paperVector(app.journals);
  if (!q) return `<p class="empty">${h(t("matchNone"))}</p>`;
  const ranked = Object.entries(app.journals.vecs).map(([k, v]) => [k, dot(q, v)]).filter(([, s]) => s > 0)
    .sort((a, b) => b[1] - a[1]).slice(0, 25);
  if (!ranked.length) return `<p class="empty">${h(t("matchNone"))}</p>`;
  const top = ranked[0][1];
  const sjr = sjrByTitle();
  const packs = pubs?.state.packs || {};
  const money = (v, unit) => (unit === "VND" ? `${new Intl.NumberFormat(locale()).format(v)} ${t("currencyVnd")}`
    : `${new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 }).format(v)} ${t("pointsUnit")}`);
  return `<h3 class="section-title">${h(t("journalResults"))}</h3>
    <p class="hint">${h(t("matchNote"))} ${sjr ? "" : h(t("journalNoSjr"))}</p>
    <div class="list">${ranked.map(([key, s]) => {
      const p = app.journals.profiles[key];
      // ISSN join first (exact); the normalised title is only a fallback.
      const byIssn = (p.issn || []).map((i) => pubs?.state.sjr?.byIssn[i]).find(Boolean);
      const hit = byIssn || sjr?.get(normTitle(p.name));
      const joinedBy = byIssn ? "issn" : "name";
      let estimate = "";
      if (hit && (packs.points || packs.bonus)) {
        const facts = { kind: "journal", year: new Date().getFullYear(), international_journal: true, issn_online: true,
          scopus_indexed: true, scopus_quartile: hit.q };
        const r = scoreWithPacks(packs, facts);
        const parts = [];
        if (r.points) parts.push(`${t("packPoints")}: ${r.points.value ? money(r.points.value, packs.points.unit) : "—"}`);
        if (r.bonus) parts.push(`${t("packBonus")}: ${r.bonus.value ? money(r.bonus.value, packs.bonus.unit) : "—"}`);
        estimate = `<div class="hint">${h(t("journalEstimate", { parts: parts.join(" · ") }))}</div>`;
      }
      return `<article class="card"><div>
        <div class="title-row"><a class="name" href="https://dblp.org/db/journals/${encodeURIComponent(key)}/" target="_blank" rel="noopener">${h(p.name)}</a>
          ${p.abbrev && p.abbrev !== p.name ? `<span class="muted">${h(p.abbrev)}</span>` : ""}
          ${hit ? `<span class="badge ${hit.q === "Q1" ? "rank-top" : hit.q === "Q2" ? "rank-mid" : "rank-low"}">${h(hit.q === "none" ? "Scopus" : `Scopus ${hit.q}`)}</span>` : ""}</div>
        <div class="match"><span class="match-bar"><i style="width:${Math.max(1, Math.round((s / top) * 100))}%"></i></span>
          <strong>${h(t("matchScore", { pct: Math.max(1, Math.round((s / top) * 100)) }))}</strong>
          <span>${h(t("matchWhy", { terms: topShared(q, app.journals.vecs[key]).join(", ") }))}</span></div>
        <div class="meta"><span>${h(t("journalTitles", { n: p.n_titles, from: app.journals.years[0], to: app.journals.years[1] }))}</span>
          ${p.issn?.length ? `<span>ISSN ${h(p.issn.join(", "))}</span>` : ""}${p.publisher ? `<span>${h(p.publisher)}</span>` : ""}
          ${hit ? `<span>${h(t(joinedBy === "issn" ? "journalSjrIssn" : "journalSjrMatch", { year: pubs.state.sjr.year || "?" }))}</span>` : ""}</div>
        ${estimate}
      </div></article>`;
    }).join("")}</div>`;
}

function vecOf(c) {
  if (!app.venueVecs.has(c.id)) {
    const names = Object.fromEntries(Object.keys(app.areas).map((k) => [k, app.areas[k]]));
    app.venueVecs.set(c.id, venueVector(c, app.profiles, names));
  }
  return app.venueVecs.get(c.id);
}
/** The researcher's vector: interests plus (if allowed) in-app activity. */
function userVector() {
  if (app.profilesState !== "ready") return null;
  const idf = app.profiles.idf;
  const parts = [];
  if (app.profile.interests.trim()) parts.push({ vec: textVector(app.profile.interests, idf), weight: 1 });
  if (app.profile.learn) {
    if (app.activity.searches.length) parts.push({ vec: textVector(app.activity.searches.join(" . "), idf), weight: 0.4 });
    const tracked = Object.keys(app.plan).map((id) => app.byId.get(id)).filter(Boolean);
    for (const c of tracked) parts.push({ vec: vecOf(c).vec, weight: 0.5 / tracked.length * Math.min(3, tracked.length) });
    const opened = app.activity.opened.map((id) => app.byId.get(id)).filter(Boolean);
    for (const c of opened) parts.push({ vec: vecOf(c).vec, weight: 0.3 / opened.length * Math.min(3, opened.length) });
  }
  const vec = combine(parts);
  return vec.size ? vec : null;
}
function scoresFor(vec, list) {
  const scores = new Map();
  if (!vec) return scores;
  for (const c of list) { const v = vecOf(c); scores.set(c.id, dot(vec, v.vec) * v.weight); }
  return scores;
}
function hasPersonalSignal() {
  return Boolean(app.profile.interests.trim()) || (app.profile.learn &&
    (app.activity.searches.length > 0 || app.activity.opened.length > 0 || Object.keys(app.plan).length > 0));
}

// ---- plan --------------------------------------------------------------------
function loadPlan() {
  app.plan = store.get(KEYS.plan, {}) || {};
  const legacy = store.get(KEYS.legacy, null);
  if (Array.isArray(legacy) && legacy.length) {
    for (const id of legacy) {
      const c = app.byId.get(id);
      if (c && !app.plan[id]) app.plan[id] = newPlanEntry(c);
    }
    savePlan();
    store.remove(KEYS.legacy);
  }
  for (const [id, e] of Object.entries(app.plan)) {
    const c = app.byId.get(id);
    if (c) e.snapshot = snapshot(c);
  }
}
function newPlanEntry(c) {
  return { status: "considering", title: "", notes: "", added: new Date().toISOString(), snapshot: snapshot(c) };
}
function savePlan() {
  if (!store.set(KEYS.plan, app.plan)) toast("Storage unavailable: the plan will not persist.");
  updateTabCounts();
}
function toggleTrack(id) {
  if (app.plan[id]) delete app.plan[id];
  else if (app.byId.get(id)) app.plan[id] = newPlanEntry(app.byId.get(id));
  savePlan();
}

// ---- helpers -----------------------------------------------------------------
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2600);
}
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function countdownText(iso, now) {
  const diff = Date.parse(iso) - now;
  if (diff <= 0) return app.t("passed");
  const { days, hours, minutes } = countdownParts(diff);
  return app.t("left", { d: days, h: hours, m: minutes });
}
function rankBadges(c) {
  const out = [];
  const cls = (r) => (r === "A*" || r === "A" ? "rank-top" : r === "B" ? "rank-mid" : "rank-low");
  if (c.rank?.ccf) out.push(`<span class="badge ${cls(c.rank.ccf)}" title="China Computer Federation">CCF ${h(c.rank.ccf)}</span>`);
  if (c.rank?.core) out.push(`<span class="badge ${cls(c.rank.core)}" title="CORE conference ranking">CORE ${h(c.rank.core)}</span>`);
  if (!isRanked(c)) out.push(`<span class="badge">${h(app.t("badgeUnranked"))}</span>`);
  return out.join("");
}
function modeLabel(mode) {
  return app.t({ "in-person": "modeInPerson", hybrid: "modeHybrid", online: "modeOnline", tbd: "modeTbd" }[mode] || "modeTbd");
}
const ctx = (extra = {}) => ({ home: app.loc.country, ...extra });

// ---- static texts ---------------------------------------------------------------
function applyTexts() {
  const t = app.t;
  document.documentElement.lang = app.lang;
  $("#app-name").textContent = t("appName");
  $("#lang").value = app.lang;
  $("#tagline").textContent = t("tagline");
  $("#btn-subscribe").textContent = `📅 ${t("subscribe")}`;
  $("#btn-theme").title = t("theme");
  $("#footer").textContent = `${t("footer")} ${t("privacyNote")}`;
  $("#sub-title").textContent = t("subscribeTitle");
  $("#sub-body").textContent = t("subscribeBody");
  $("#sub-copy").textContent = t("copy");
  $("#sub-close").textContent = t("close");
  $("#sub-url").value = new URL("data/deadlines.ics", location.href).href;
  renderLocation();
  updateTabCounts();
  renderFresh();
}
function updateTabCounts() {
  const n = Object.keys(app.plan).length;
  $("#tab-list").textContent = app.t("tabList");
  $("#tab-foryou").textContent = `✨ ${app.t("tabForYou")}`;
  $("#tab-calendar").textContent = app.t("tabCalendar");
  $("#tab-plan").innerHTML = `${h(app.t("tabPlan"))}<span class="count">${n}</span>`;
  $("#tab-pubs").textContent = `🎓 ${app.t("tabPubs")}`;
  for (const b of document.querySelectorAll(".tab")) b.setAttribute("aria-selected", String(b.dataset.view === app.view));
}
function renderFresh() {
  const el = $("#fresh");
  if (!app.data) { el.textContent = app.t("loading"); return; }
  const when = new Date(app.data.last_updated);
  const days = Math.floor((Date.now() - when) / 86400000);
  el.classList.toggle("stale", days >= STALE_DAYS);
  el.textContent = days >= STALE_DAYS
    ? app.t("stale", { days })
    : app.t("updated", { when: new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(when) });
}

// ---- filters panel ---------------------------------------------------------------
function renderFilters() {
  const t = app.t, s = app.state, home = app.loc.country;
  const chip = (group, value, label) =>
    `<button type="button" class="chip" data-chip="${group}" data-value="${h(value)}" aria-pressed="${s[group].includes(value)}">${h(label)}</button>`;
  const radio = (field, value, label, disabled = false) =>
    `<button type="button" class="chip" data-radio="${field}" data-value="${h(value)}" aria-pressed="${s[field] === value}" ${disabled ? "disabled" : ""}>${h(label)}</button>`;
  const check = (key, label) =>
    `<label class="check"><input type="checkbox" data-bool="${key}" ${s[key] ? "checked" : ""}/> <span>${h(label)}</span></label>`;
  const countries = [...new Set(app.confs.map((c) => c.country).filter((c) => c && c !== "TBD"))].sort((a, b) => a.localeCompare(b));
  if (home && !countries.includes(home)) countries.push(home);
  const ordered = home ? [home, ...countries.filter((c) => c !== home)] : countries;
  const cityCountry = s.country || (s.where === "home" ? home : "");
  const cities = cityOptions(cityCountry);
  $("#filters").innerHTML = `
    <fieldset class="fgroup">
      <label class="sr-only" for="f-q">${h(t("search"))}</label>
      <input id="f-q" class="search" type="search" placeholder="${h(t("search"))}" value="${h(s.q)}" />
    </fieldset>
    <fieldset class="fgroup">
      <legend>${h(t("submission"))}</legend>
      <label class="check"><input type="checkbox" checked disabled /> <span>${h(t("onlyOpen"))}</span></label>
      ${check("showEstimated", t("showEstimated"))}
      ${check("showClosed", t("showClosed"))}
      ${check("showJournals", t("showJournals"))}
      <label class="field">${h(t("within"))}
        <select data-field="within">
          ${[0, 7, 14, 30, 60, 90].map((d) => `<option value="${d}" ${Number(s.within) === d ? "selected" : ""}>${h(d ? t("days", { n: d }) : t("anyTime"))}</option>`).join("")}
        </select>
      </label>
    </fieldset>
    <fieldset class="fgroup">
      <legend>${h(t("where"))}</legend>
      <div class="chips">
        ${radio("where", "", t("whereAll"))}
        ${radio("where", "home", t("whereHome", { country: home || "…" }), !home)}
        ${radio("where", "abroad", t("whereAbroad"), !home)}
      </div>
      ${home ? "" : `<p class="hint">${h(t("whereNeedsLoc"))}</p>`}
      <div class="chip-label">${h(t("level"))}</div>
      <div class="chips">
        ${radio("level", "", t("whereAll"))}${radio("level", "international", t("levelInternational"))}${radio("level", "national", t("levelNational"))}
      </div>
      <label class="field">${h(t("country"))}
        <select data-field="country">
          <option value="">${h(t("allCountries"))}</option>
          ${ordered.map((c) => `<option value="${h(c)}" ${s.country === c ? "selected" : ""}>${c === home ? "📍 " : ""}${h(c)}</option>`).join("")}
        </select>
      </label>
      ${cityCountry ? `<label class="field">${h(t("city"))}
        <select data-field="city">
          <option value="">${h(t("allCities"))}</option>
          ${cities.map(({ name, n }) => `<option value="${h(name)}" ${s.city === name ? "selected" : ""}>${name === app.loc.city ? "📍 " : ""}${h(name)} (${n})</option>`).join("")}
        </select></label>` : ""}
      <div class="chip-label">${h(t("mode"))}</div>
      <div class="chips">
        ${chip("modes", "in-person", t("modeInPerson"))}${chip("modes", "hybrid", t("modeHybrid"))}
        ${chip("modes", "online", t("modeOnline"))}${chip("modes", "tbd", t("modeTbd"))}
      </div>
      <div class="row2">
        <label class="field">${h(t("eventFrom"))}<input type="date" data-field="from" value="${h(s.from)}" /></label>
        <label class="field">${h(t("eventTo"))}<input type="date" data-field="to" value="${h(s.to)}" /></label>
      </div>
    </fieldset>
    <fieldset class="fgroup">
      <legend>${h(t("rank"))}</legend>
      ${check("rankedOnly", t("rankedOnly"))}
      <div class="chip-label">${h(t("ccf"))}</div>
      <div class="chips">${CCF_RANKS.map((r) => chip("ccf", r, r)).join("")}</div>
      <div class="chip-label">${h(t("core"))}</div>
      <div class="chips">${CORE_RANKS.map((r) => chip("core", r, r)).join("")}</div>
    </fieldset>
    <fieldset class="fgroup">
      <legend>${h(t("area"))}</legend>
      ${Object.keys(app.areas).map((code) => `
        <label class="check"><input type="checkbox" data-area="${h(code)}" ${s.areas.includes(code) ? "checked" : ""}/>
          <span>${h(areaName(code))}</span><span class="n" data-area-count="${h(code)}"></span></label>`).join("")}
    </fieldset>
    <fieldset class="fgroup">
      <button type="button" class="btn" data-action="reset">${h(t("reset"))}</button>
      <button type="button" class="btn" data-action="copy-view">${h(t("copyLink"))}</button>
    </fieldset>`;
}

function updateAreaCounts() {
  const { items } = filterConfs(app.confs, { ...app.state, areas: [] }, Date.now(), ctx());
  const counts = countBy(items, "sub");
  for (const el of document.querySelectorAll("[data-area-count]")) el.textContent = counts.get(el.dataset.areaCount) || 0;
}

// ---- cards -------------------------------------------------------------------------
function deadlineRows(c, now) {
  const next = nextDeadline(c, now);
  return (c.deadlines || []).map((d) => {
    const past = Date.parse(d.iso) <= now;
    return `<li class="${past ? "past" : ""}${next === d ? " next" : ""}">
      <span class="dtype">${h(app.t(d.type))}</span>
      <span><span class="when">${h(formatInZone(d.iso, c.timezone, locale()))}</span>
        <small>${h(formatLocal(d.iso, locale()))} (${h(app.t("yourTime"))})</small>
        ${d.comment ? ` <span class="cmt">· ${h(d.comment)}</span>` : ""}</span>
    </li>`;
  }).join("");
}
function trimDeadlines(list, now) {
  const past = list.filter((d) => Date.parse(d.iso) <= now);
  const future = list.filter((d) => Date.parse(d.iso) > now);
  return [...past.slice(-1), ...future.slice(0, 4)];
}
function summaryRow(c) {
  const t = app.t;
  const when = formatEventRange(c, locale()) || t("modeTbd");
  const place = [c.city && c.city !== c.country ? c.city : "", c.country !== "TBD" && c.country !== "Online" ? c.country : ""]
    .filter(Boolean).join(", ");
  const placeText = `${place || (c.mode === "online" ? t("modeOnline") : t("modeTbd"))}${c.mode === "hybrid" ? ` · ${t("modeHybrid")}` : ""}`;
  const home = app.loc.country && c.country === app.loc.country;
  const fee = feeSummary(c.fees, locale());
  const feeUrl = safeUrl(c.fees?.url) || safeUrl(c.url);
  const feeHtml = fee
    ? `${h(t("feesFrom", { amount: fee }))} <a href="${h(feeUrl)}" target="_blank" rel="noopener" title="${h(t("feesChecked", { date: c.fees.checked }))}">↗</a>`
    : `<span class="muted">${h(t("feesUnknown"))}</span>${feeUrl ? ` <a href="${h(feeUrl)}" target="_blank" rel="noopener">↗</a>` : ""}`;
  return `<dl class="summary-row">
    <div><dt>${h(t("summaryTime"))}</dt><dd>${h(when)}</dd></div>
    <div><dt>${h(t("summaryPlace"))}</dt><dd>${home ? "📍 " : ""}${h(placeText)}</dd></div>
    <div><dt>${h(t("summaryFees"))}</dt><dd>${feeHtml}</dd></div>
  </dl>`;
}

function cardHtml(c, now, match = null) {
  const t = app.t;
  const status = submissionStatus(c, now);
  const key = keyDeadline(c, now);
  const u = key ? urgency(Date.parse(key.iso) - now) : "past";
  const ar = latestAcceptRate(c);
  const url = safeUrl(c.url);
  const tracked = Boolean(app.plan[c.id]);
  const isOpen = app.open.has(c.id);
  const shown = isOpen ? c : { ...c, deadlines: trimDeadlines(c.deadlines || [], now) };
  const badges = [
    rankBadges(c),
    `<span class="badge area">${h(areaName(c.sub))}</span>`,
    c.scope === "national" ? `<span class="badge">${h(t("levelNational"))}</span>` : "",
    status === "estimated" ? `<span class="badge est">${h(t("badgeEstimated", { year: c.estimated_from }))}</span>` : "",
    status === "closed" ? `<span class="badge">${h(t("badgeClosed"))}</span>` : "",
    c.kind === "journal" ? `<span class="badge">${h(t("badgeJournal"))}</span>` : "",
    c.tz_known === false && c.source !== "wikicfp" ? `<span class="badge warn">${h(t("badgeTz"))}</span>` : "",
  ].join("");
  return `
  <article class="card u-${u} s-${status}" data-id="${h(c.id)}">
    <div>
      <div class="title-row">
        ${url ? `<a class="name" href="${h(url)}" target="_blank" rel="noopener">${h(c.acronym)} ${h(c.year)}</a>` : `<strong class="name">${h(c.acronym)} ${h(c.year)}</strong>`}
        ${badges}
      </div>
      <p class="full">${h(c.full_name)}</p>
      ${match ? `<div class="match"><span class="match-bar"><i style="width:${match.pct}%"></i></span>
        <strong>${h(t("matchScore", { pct: match.pct }))}</strong>
        ${match.terms.length ? `<span>${h(t("matchWhy", { terms: match.terms.join(", ") }))}</span>` : ""}
        ${match.basis === "name" ? `<span class="badge warn">${h(t("matchBasisName"))}</span>` : ""}</div>` : ""}
      ${summaryRow(c)}
      ${ar ? `<div class="meta"><span title="${h(t("acceptanceHistory"))}">📊 ${h(t("acceptance"))} ${(ar.rate * 100).toFixed(1)}% (${h(ar.year)})</span></div>` : ""}
      <ul class="deadlines">${deadlineRows(shown, now)}</ul>
    </div>
    <div class="side">
      ${key ? `<div class="countdown u-${u}" data-deadline="${h(key.iso)}">${h(countdownText(key.iso, now))}</div>
      <div class="countdown-label">${h(t(key.type))} · ${h(t("venueTime"))}: ${h(c.timezone || "AoE")}</div>` : ""}
      <div class="actions">
        <button type="button" class="btn small ${tracked ? "on" : ""}" data-action="track" data-id="${h(c.id)}" aria-pressed="${tracked}">${tracked ? "★ " + h(t("tracked")) : "☆ " + h(t("track"))}</button>
        <button type="button" class="btn small" data-action="ics" data-id="${h(c.id)}">＋ ${h(t("addCalendar"))}</button>
        ${c.dblp ? `<a class="btn small" href="https://dblp.org/db/conf/${encodeURIComponent(c.dblp)}/" target="_blank" rel="noopener">${h(t("dblp"))}</a>` : ""}
        <button type="button" class="btn small ghost" data-action="details" data-id="${h(c.id)}" aria-expanded="${isOpen}">${h(isOpen ? t("hideDetails") : t("details"))}</button>
      </div>
    </div>
    ${isOpen ? detailsHtml(c) : ""}
  </article>`;
}

function detailsHtml(c) {
  const t = app.t;
  const rates = c.accept_rates || [];
  const max = Math.max(0.01, ...rates.map((r) => r.rate));
  const fees = c.fees?.items || [];
  return `<div class="details">
    ${c.status === "estimated" ? `<div>⚠️ ${h(t("estimatedNote"))}</div>` : ""}
    ${fees.length ? `<div><strong>${h(t("summaryFees"))}</strong> (${h(t("feesChecked", { date: c.fees.checked }))},
      <a href="${h(safeUrl(c.fees.url))}" target="_blank" rel="noopener">${h(t("feesSource"))}</a>)
      <ul class="fees">${fees.map((f) => `<li>${h(f.label)}: ${h(new Intl.NumberFormat(locale()).format(f.amount))} ${h(f.currency)}</li>`).join("")}</ul></div>` : ""}
    ${rates.length ? `<div><strong>${h(t("acceptanceHistory"))}</strong>
      <div class="rates">${rates.map((r) => `<span class="rate-bar" title="${h(r.accepted ?? "?")}/${h(r.submitted ?? "?")}">
        ${(r.rate * 100).toFixed(1)}%<i style="height:${Math.round((r.rate / max) * 46) + 4}px"></i>${h(r.year)}</span>`).join("")}</div></div>` : ""}
    ${watchLine(c)}
    <div>${h(t("source"))}: ${h({ ccfddl: "ccfddl/ccf-deadlines", wikicfp: "WikiCFP", curated: `hand-checked list (${c.checked || ""})` }[c.source] || c.source)}${c.publisher ? ` · ${h(c.publisher)}` : ""}${c.place && c.place !== "TBD" ? ` · ${h(c.place)}` : ""}${c.date && c.date !== "TBD" ? ` · ${h(c.date)}` : ""}</div>
  </div>`;
}

/** "Website checked weekly" line for venues whose site the watcher follows. */
function watchLine(c) {
  const w = app.watch[String(c.acronym || "").toUpperCase()];
  if (!w) return "";
  const pages = Object.entries(w.pages || {}).filter(([, p]) => p.status === 200);
  if (!pages.length) return "";
  const latest = (k) => pages.map(([, p]) => p[k]).sort().slice(-1)[0];
  const day = (iso) => new Intl.DateTimeFormat(locale(), { dateStyle: "medium" }).format(new Date(iso));
  return `<div>🔁 ${h(app.t("watchStatus", { checked: day(latest("last_checked")), changed: day(latest("last_changed")) }))}
    ${pages.map(([url]) => `<a href="${h(safeUrl(url))}" target="_blank" rel="noopener">${h(new URL(url).host)}</a>`).join(" · ")}</div>`;
}

function toolbar(items, extraButtons = "") {
  const t = app.t, now = Date.now();
  const soon = items.filter((c) => { const k = keyDeadline(c, now); return k && Date.parse(k.iso) - now < 7 * 86400000; }).length;
  const sorts = [["deadline", "sortDeadline"], ["event", "sortEvent"], ["rank", "sortRank"], ["acceptance", "sortAcceptance"]];
  if (hasPersonalSignal()) sorts.push(["match", "sortMatch"]);
  return `<div class="toolbar">
      <button type="button" class="btn filter-toggle" data-action="toggle-filters">⚙ ${h(t("showFilters"))}</button>
      <div class="summary">${h(t("summary", { shown: items.length }))}${soon ? `<small>${h(t("summarySoon", { n: soon }))}</small>` : ""}</div>
      <label class="sr-only" for="f-sort">${h(t("sortBy"))}</label>
      <select id="f-sort" class="btn" data-field="sort" aria-label="${h(t("sortBy"))}">
        ${sorts.map(([v, k]) => `<option value="${v}" ${app.state.sort === v ? "selected" : ""}>${h(t(k))}</option>`).join("")}
      </select>
      ${extraButtons}
    </div>`;
}
function hiddenNote(hidden) {
  const s = app.state;
  const total = (s.showClosed ? 0 : hidden.closed) + (s.showEstimated ? 0 : hidden.estimated) + (s.showJournals ? 0 : hidden.journals);
  return total ? `<p class="hidden-note">${h(app.t("hiddenNote", hidden))} <button type="button" data-action="show-hidden">${h(app.t("showAll"))}</button></p>` : "";
}

// ---- list view ---------------------------------------------------------------------
function renderList() {
  const now = Date.now();
  const t = app.t;
  let scores;
  if (app.state.sort === "match") {
    if (app.profilesState !== "ready") ensureProfiles();
    else scores = scoresFor(userVector(), app.confs);
  }
  const { items, hidden } = filterConfs(app.confs, app.state, now, ctx({ scores }));
  const top = scores ? Math.max(1e-9, ...items.map((c) => scores.get(c.id) || 0)) : 0;
  $("#view").innerHTML = `
    ${toolbar(items, `<button type="button" class="btn" data-action="export-ics">📅 ${h(t("exportIcs"))}</button>
      <button type="button" class="btn" data-action="export-csv">⬇ ${h(t("exportCsv"))}</button>`)}
    ${hiddenNote(hidden)}
    ${app.state.sort === "match" && app.profilesState === "loading" ? `<p class="hint">${h(t("profilesLoading"))}</p>` : ""}
    <div class="list">
      ${items.length ? items.map((c) => cardHtml(c, now, scores ? matchInfo(c, scores, top, null) : null)).join("") : `<div class="empty">${h(t("noResults"))}</div>`}
    </div>`;
}
function matchInfo(c, scores, top, qvec) {
  const s = scores.get(c.id) || 0;
  if (s <= 0) return null;
  const v = vecOf(c);
  return { pct: Math.max(1, Math.round((s / top) * 100)), terms: qvec ? topShared(qvec, v.vec) : [], basis: v.basis };
}

// ---- for-you view ----------------------------------------------------------------------
function renderForYou() {
  const t = app.t, now = Date.now();
  if (app.profilesState === "idle") ensureProfiles();
  const nSignals = app.activity.searches.length + app.activity.opened.length;
  let body = "";
  if (app.profilesState === "loading" || app.profilesState === "idle") body = `<p class="empty">${h(t("profilesLoading"))}</p>`;
  else if (app.profilesState === "error") body = `<p class="empty">${h(t("profilesError"))}</p>`;
  else {
    const useAbstract = app.matchMode === "abstract" && (app.profile.abstract.trim() || app.profile.contrib.trim());
    const qvec = useAbstract ? paperVector(app.profiles) : userVector();
    if (useAbstract && app.profile.target === "journals") {
      body = journalResults(t);
    } else if (!qvec || !qvec.size) {
      body = `<p class="empty">${h(useAbstract ? t("matchNone") : t("matchEmpty"))}</p>`;
    } else {
      const scores = scoresFor(qvec, app.confs);
      const { items, hidden } = filterConfs(app.confs, { ...app.state, sort: "match" }, now, ctx({ scores }));
      const ranked = items.filter((c) => (scores.get(c.id) || 0) > 0).slice(0, 30);
      const top = Math.max(1e-9, ...ranked.map((c) => scores.get(c.id)));
      body = `<h3 class="section-title">${h(t("matchFor", { what: t(useAbstract ? "whatAbstract" : "whatProfile") }))}</h3>
        <p class="hint">${h(t("matchResults"))} · ${h(t("matchNote"))}</p>
        ${hiddenNote(hidden)}
        <div class="list">${ranked.length ? ranked.map((c) => cardHtml(c, now, matchInfo(c, scores, top, qvec))).join("")
          : `<div class="empty">${h(t("matchNone"))}</div>`}</div>`;
    }
  }
  $("#view").innerHTML = `
    <div class="toolbar"><button type="button" class="btn filter-toggle" data-action="toggle-filters">⚙ ${h(t("showFilters"))}</button></div>
    <div class="foryou">
      <section class="panel pad">
        <h3>${h(t("profileTitle"))}</h3>
        <p class="hint">${h(t("profileHint"))}</p>
        <textarea id="p-interests" rows="3" placeholder="${h(t("profilePlaceholder"))}">${h(app.profile.interests)}</textarea>
        <label class="check"><input type="checkbox" id="p-learn" ${app.profile.learn ? "checked" : ""}/> <span>${h(t("learnActivity"))}</span></label>
        <p class="hint">${h(t("activityCount", { n: nSignals }))} <button type="button" class="btn small" data-action="clear-activity" ${nSignals ? "" : "disabled"}>${h(t("clearActivity"))}</button></p>
        <button type="button" class="btn primary" data-action="match-profile">✨ ${h(t("sortMatch"))}</button>
      </section>
      <section class="panel pad">
        <h3>${h(t("abstractTitle"))}</h3>
        <p class="hint">${h(t("abstractHint"))}</p>
        <textarea id="p-abstract" rows="5" placeholder="${h(t("abstractPlaceholder"))}">${h(app.profile.abstract)}</textarea>
        <textarea id="p-contrib" rows="3" placeholder="${h(t("contribPlaceholder"))}">${h(app.profile.contrib)}</textarea>
        <div class="chips">
          <button type="button" class="chip" data-action="target" data-value="venues" aria-pressed="${app.profile.target !== "journals"}">${h(t("targetVenues"))}</button>
          <button type="button" class="chip" data-action="target" data-value="journals" aria-pressed="${app.profile.target === "journals"}">${h(t("targetJournals"))}</button>
        </div>
        <p></p>
        <button type="button" class="btn primary" data-action="match-abstract">🔎 ${h(t("findVenues"))}</button>
      </section>
    </div>
    <p class="hint">${h(t("privacyNote"))}</p>
    ${body}`;
}

// ---- calendar view -------------------------------------------------------------------
function renderCalendar() {
  const now = Date.now();
  const t = app.t;
  if (!app.calMonth) { const d = new Date(); app.calMonth = new Date(d.getFullYear(), d.getMonth(), 1); }
  const { items } = filterConfs(app.confs, app.state, now, ctx());
  const byDay = new Map();
  for (const c of items) {
    for (const d of c.deadlines || []) {
      const day = localDay(d.iso);
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push({ c, d });
    }
  }
  const first = app.calMonth;
  const startOffset = (first.getDay() + 6) % 7;
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - startOffset);
  const today = localDay(new Date().toISOString());
  const dowFmt = new Intl.DateTimeFormat(locale(), { weekday: "short" });
  const dows = [...Array(7)].map((_, i) => dowFmt.format(new Date(2024, 0, 1 + i)));
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const dayKey = dayKeyOf(d);
    const evs = (byDay.get(dayKey) || []).sort((a, b) => a.d.iso.localeCompare(b.d.iso));
    cells.push(`<div class="day ${d.getMonth() !== first.getMonth() ? "out" : ""} ${dayKey === today ? "today" : ""}">
      <span class="dnum">${d.getDate()}</span>
      ${evs.map(({ c, d: dl }) => `<button type="button" class="ev t-${h(dl.type)} ${c.status === "estimated" ? "est" : ""} ${app.plan[c.id] ? "tracked" : ""}"
        data-action="goto" data-id="${h(c.id)}" title="${h(`${c.acronym} ${c.year} · ${t(dl.type)} · ${formatInZone(dl.iso, c.timezone, locale())}`)}">${h(c.acronym)} · ${h(t(dl.type))}</button>`).join("")}
    </div>`);
  }
  const title = new Intl.DateTimeFormat(locale(), { month: "long", year: "numeric" }).format(first);
  $("#view").innerHTML = `
    <div class="cal-head">
      <button type="button" class="btn filter-toggle" data-action="toggle-filters">⚙ ${h(t("showFilters"))}</button>
      <h2>${h(title)}</h2>
      <button type="button" class="btn" data-action="cal-prev" aria-label="${h(t("calPrev"))}">‹</button>
      <button type="button" class="btn" data-action="cal-today">${h(t("calToday"))}</button>
      <button type="button" class="btn" data-action="cal-next" aria-label="${h(t("calNext"))}">›</button>
    </div>
    <p class="cal-note">${h(t("calNote"))}</p>
    <div class="cal">${dows.map((d) => `<div class="dow">${h(d)}</div>`).join("")}${cells.join("")}</div>
    <div class="legend">
      <span class="ev t-abstract">${h(t("abstract"))}</span><span class="ev t-paper">${h(t("paper"))}</span>
      <span class="ev t-rebuttal">${h(t("rebuttal"))}</span><span class="ev t-notification">${h(t("notification"))}</span>
      <span class="ev est">${h(t("badgeEstimated", { year: "…" }))}</span>
    </div>`;
}
function dayKeyOf(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ---- plan view ---------------------------------------------------------------------
function renderPlan() {
  const now = Date.now();
  const t = app.t;
  const entries = Object.entries(app.plan).map(([id, e]) => ({ id, e, c: app.byId.get(id) || e.snapshot }));
  entries.sort((a, b) => {
    const ka = nextDeadline(a.c, now), kb = nextDeadline(b.c, now);
    return (ka ? Date.parse(ka.iso) : Infinity) - (kb ? Date.parse(kb.iso) : Infinity);
  });
  $("#view").innerHTML = `
    <div class="toolbar">
      <div class="summary">${h(t("tabPlan"))} · ${entries.length}</div>
      <button type="button" class="btn" data-action="plan-ics" ${entries.length ? "" : "disabled"}>📅 ${h(t("planExportIcs"))}</button>
      <button type="button" class="btn" data-action="plan-export" ${entries.length ? "" : "disabled"}>⬇ ${h(t("planExport"))}</button>
      <button type="button" class="btn" data-action="plan-import">⬆ ${h(t("planImport"))}</button>
    </div>
    <p class="plan-note">${h(t("planLocal"))}</p>
    <div class="plan">
      ${entries.length ? entries.map(({ id, e, c }) => planItemHtml(id, e, c, now)).join("") : `<div class="empty">${h(t("planEmpty"))}</div>`}
    </div>`;
}

function planItemHtml(id, e, c, now) {
  const t = app.t;
  const next = nextDeadline(c, now);
  const u = next ? urgency(Date.parse(next.iso) - now) : "past";
  const url = safeUrl(c.url);
  return `<div class="plan-item" data-id="${h(id)}">
    <div>
      <h3>${url ? `<a href="${h(url)}" target="_blank" rel="noopener">${h(c.acronym)} ${h(c.year)}</a>` : `${h(c.acronym)} ${h(c.year)}`}
        <span class="status-pill st-${h(e.status)}">${h(t(`st_${e.status}`))}</span></h3>
      <div class="sub">${h(c.full_name)}</div>
      ${app.byId.has(id) ? "" : `<div class="gone">${h(t("planGone"))}</div>`}
      <div class="sub" style="margin-top:6px">${h(t("planNext"))}:
        ${next ? `<strong class="countdown u-${u}" data-deadline="${h(next.iso)}">${h(countdownText(next.iso, now))}</strong>
          · ${h(t(next.type))} · ${h(formatInZone(next.iso, c.timezone, locale()))}` : "—"}</div>
    </div>
    <div>
      <label class="field">${h(t("planTitle"))}<input data-plan="title" value="${h(e.title)}" /></label>
      <label class="field">${h(t("planNotes"))}<textarea data-plan="notes">${h(e.notes)}</textarea></label>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px">
      <label class="field">${h(t("planStatus"))}
        <select data-plan="status">${PLAN_STATUSES.map((s) => `<option value="${s}" ${e.status === s ? "selected" : ""}>${h(t(`st_${s}`))}</option>`).join("")}</select>
      </label>
      <button type="button" class="btn small" data-action="ics" data-id="${h(id)}">＋ ${h(t("addCalendar"))}</button>
      <button type="button" class="btn small" data-action="untrack" data-id="${h(id)}">✕ ${h(t("planRemove"))}</button>
    </div>
  </div>`;
}

// ---- render dispatch -------------------------------------------------------------------
function renderView() {
  writeHash();
  updateTabCounts();
  const noFilters = app.view === "plan" || app.view === "pubs";
  $("#layout").classList.toggle("no-filters", noFilters);
  $("#filters").hidden = noFilters;
  if (!app.data) return;
  if (app.view === "pubs") { pubs.render($("#view")); return; }
  if (app.view === "calendar") renderCalendar();
  else if (app.view === "plan") renderPlan();
  else if (app.view === "foryou") renderForYou();
  else renderList();
  updateAreaCounts();
}
function setState(patch) {
  app.state = { ...app.state, ...patch };
  renderView();
}

// ---- events ------------------------------------------------------------------------------
function bindEvents() {
  document.addEventListener("click", (ev) => {
    if (app.view === "pubs" && pubs && ev.target.closest("[data-pact]") && ev.target.closest("[data-pact]").tagName !== "SELECT") {
      pubs.onClick(ev);
      return;
    }
    const tab = ev.target.closest(".tab");
    if (tab) { app.view = tab.dataset.view; renderView(); return; }
    const chipEl = ev.target.closest("[data-chip]");
    if (chipEl) {
      const g = chipEl.dataset.chip, v = chipEl.dataset.value;
      const cur = app.state[g];
      const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
      chipEl.setAttribute("aria-pressed", String(next.includes(v)));
      setState({ [g]: next });
      return;
    }
    const radioEl = ev.target.closest("[data-radio]");
    if (radioEl) {
      const patch = { [radioEl.dataset.radio]: radioEl.dataset.value };
      if (radioEl.dataset.radio === "where") Object.assign(patch, { country: "", city: "" });
      app.state = { ...app.state, ...patch };
      renderFilters();
      renderView();
      return;
    }
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const id = btn.dataset.id;
    const now = Date.now();
    switch (btn.dataset.action) {
      case "track": toggleTrack(id); renderView(); break;
      case "untrack": delete app.plan[id]; savePlan(); renderView(); break;
      case "details":
        if (app.open.has(id)) app.open.delete(id);
        else { app.open.add(id); recordOpen(id); }
        renderView();
        break;
      case "ics": {
        const c = app.byId.get(id) || app.plan[id]?.snapshot;
        if (!c) break;
        const { text, count } = buildIcs([c], now, `${c.acronym} ${c.year}`);
        if (!count) { toast(app.t("passed")); break; }
        download(`${c.acronym}_${c.year}_deadlines.ics`.replace(/[^\w.-]+/g, "_"), text, "text/calendar;charset=utf-8");
        break;
      }
      case "export-ics": {
        const { items } = filterConfs(app.confs, app.state, now, ctx());
        download("conference_deadlines.ics", buildIcs(items, now, "conf-tMtTracker: conference deadlines").text, "text/calendar;charset=utf-8");
        break;
      }
      case "export-csv": {
        const { items } = filterConfs(app.confs, app.state, now, ctx());
        download("conference_deadlines.csv", "\uFEFF" + buildCsv(items, now), "text/csv;charset=utf-8");
        break;
      }
      case "plan-ics": {
        const list = Object.entries(app.plan).map(([pid, e]) => app.byId.get(pid) || e.snapshot);
        download("my_submission_plan.ics", buildIcs(list, now, "conf-tMtTracker: my submission plan").text, "text/calendar;charset=utf-8");
        break;
      }
      case "plan-export":
        download(`conf_tracker_plan_${new Date().toISOString().slice(0, 10)}.json`,
          JSON.stringify({ app: "conf-tracker", version: 1, exported: new Date().toISOString(), plan: app.plan }, null, 1),
          "application/json");
        break;
      case "plan-import": $("#plan-file").click(); break;
      case "match-profile":
        app.profile.interests = $("#p-interests").value;
        saveProfile();
        app.matchMode = "profile";
        renderView();
        break;
      case "target":
        app.profile.target = btn.dataset.value;
        saveProfile();
        if (app.profile.abstract.trim() || app.profile.contrib.trim()) app.matchMode = "abstract";
        renderView();
        break;
      case "match-abstract":
        app.profile.contrib = $("#p-contrib").value;
        app.profile.abstract = $("#p-abstract").value;
        saveProfile();
        app.matchMode = "abstract";
        renderView();
        break;
      case "clear-activity":
        app.activity = { searches: [], opened: [] };
        saveActivity();
        renderView();
        break;
      case "reset":
        app.state = { ...DEFAULT_STATE, areas: [], ccf: [], core: [], modes: [] };
        renderFilters(); renderView();
        break;
      case "show-hidden":
        app.state = { ...app.state, showClosed: true, showEstimated: true, showJournals: true };
        renderFilters(); renderView();
        break;
      case "toggle-filters": $("#filters").classList.toggle("open"); break;
      case "copy-view": copy(location.href); break;
      case "copy-feed": copy($("#sub-url").value); break;
      case "cal-prev": app.calMonth = new Date(app.calMonth.getFullYear(), app.calMonth.getMonth() - 1, 1); renderView(); break;
      case "cal-next": app.calMonth = new Date(app.calMonth.getFullYear(), app.calMonth.getMonth() + 1, 1); renderView(); break;
      case "cal-today": app.calMonth = null; renderView(); break;
      case "goto": {
        const c = app.byId.get(id);
        if (!c) break;
        app.view = "list";
        app.open.add(id);
        app.state = { ...app.state, q: c.acronym, showClosed: true, showEstimated: true, showJournals: true };
        renderFilters();
        renderView();
        document.querySelector(`.card[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "center" });
        break;
      }
      default: break;
    }
  });

  $("#filters").addEventListener("input", (ev) => {
    const el = ev.target;
    if (el.id === "f-q") {
      setState({ q: el.value });
      clearTimeout(bindEvents.searchTimer);
      bindEvents.searchTimer = setTimeout(() => recordSearch(el.value), 1500);
      return;
    }
    if (el.dataset.bool) { setState({ [el.dataset.bool]: el.checked }); return; }
    if (el.dataset.area) {
      const cur = app.state.areas, v = el.dataset.area;
      setState({ areas: el.checked ? [...cur, v] : cur.filter((x) => x !== v) });
      return;
    }
    if (el.dataset.field === "country") {
      app.state = { ...app.state, country: el.value, city: "", where: "" };
      renderFilters();
      renderView();
      return;
    }
    if (el.dataset.field) setState({ [el.dataset.field]: el.dataset.field === "within" ? Number(el.value) : el.value });
  });
  $("#view").addEventListener("change", (ev) => {
    const el = ev.target;
    if (app.view === "pubs" && pubs && pubs.onChange(ev)) return;
    if (el.dataset.field === "sort") { setState({ sort: el.value }); return; }
    if (el.id === "p-learn") { app.profile.learn = el.checked; saveProfile(); renderView(); return; }
    const item = el.closest(".plan-item");
    if (item && el.dataset.plan) {
      app.plan[item.dataset.id][el.dataset.plan] = el.value;
      savePlan();
      if (el.dataset.plan === "status") renderView();
    }
  });
  $("#view").addEventListener("input", (ev) => {
    const el = ev.target, item = el.closest(".plan-item");
    if (item && (el.dataset.plan === "title" || el.dataset.plan === "notes")) {
      app.plan[item.dataset.id][el.dataset.plan] = el.value;
      clearTimeout(bindEvents.saveTimer);
      bindEvents.saveTimer = setTimeout(savePlan, 400);
    }
    if (el.id === "p-interests") { app.profile.interests = el.value; saveProfile(); }
    if (el.id === "p-abstract") { app.profile.abstract = el.value; saveProfile(); }
    if (el.id === "p-contrib") { app.profile.contrib = el.value; saveProfile(); }
  });

  $("#view").addEventListener("keydown", (ev) => { if (app.view === "pubs" && pubs) pubs.onKey(ev); });
  $("#plan-file").addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    const { plan, errors } = parsePlanImport(await file.text());
    if (!plan) { toast(app.t("planImportFailed", { why: errors.join("; ") })); return; }
    Object.assign(app.plan, plan);
    savePlan();
    toast(app.t("planImported", { n: Object.keys(plan).length }) + (errors.length ? ` (${errors.length} skipped)` : ""));
    renderView();
  });

  // Location dialog
  $("#btn-loc").addEventListener("click", openLocationDialog);
  $("#loc-country").addEventListener("change", (ev) => fillLocCities(ev.target.value, ""));
  $("#loc-save").addEventListener("click", (ev) => {
    ev.preventDefault();
    saveLocation({ country: $("#loc-country").value, city: $("#loc-city").value, source: "manual" });
    $("#dlg-loc").close();
  });
  $("#loc-precise").addEventListener("click", () => {
    const status = $("#loc-status");
    if (!navigator.geolocation) { status.textContent = app.t("locDenied"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      const near = nearestCity(pos.coords.latitude, pos.coords.longitude);
      if (!near) { status.textContent = app.t("locNoCity"); return; }
      saveLocation({ country: near.country, city: near.name, source: "precise" });
      $("#dlg-loc").close();
    }, () => { status.textContent = app.t("locDenied"); }, { maximumAge: 3600000, timeout: 15000 });
  });

  $("#lang").addEventListener("change", (ev) => {
    app.lang = ev.target.value;
    app.t = makeT(app.lang);
    store.setRaw(KEYS.lang, app.lang);
    applyTexts();
    renderFilters();
    renderView();
  });
  $("#btn-theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.setRaw(KEYS.theme, next);
  });
  $("#btn-subscribe").addEventListener("click", () => $("#dlg-subscribe").showModal());
  window.addEventListener("hashchange", () => { readHash(); renderFilters(); renderView(); });
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast(app.t("copied")); }
  catch { prompt(app.t("copy"), text); }
}

function tick() {
  const now = Date.now();
  let expired = false;
  for (const el of document.querySelectorAll("[data-deadline]")) {
    const diff = Date.parse(el.dataset.deadline) - now;
    if (diff <= 0) expired = true;
    el.textContent = countdownText(el.dataset.deadline, now);
    el.className = el.className.replace(/u-\w+/, `u-${urgency(diff)}`);
  }
  // Re-render only when nothing is being typed, so no input loses focus.
  const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (expired && app.view !== "plan" && !typing) renderView();
}

async function init() {
  app.lang = detectLang();
  app.t = makeT(app.lang);
  readHash();
  loadLocation();
  loadPersonal();
  applyTexts();
  bindEvents();
  try {
    const res = await fetch("data/conferences.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    app.data = await res.json();
  } catch (err) {
    console.error(err);
    $("#view").innerHTML = `<div class="empty">${h(app.t("loadError"))}</div>`;
    $("#fresh").textContent = "";
    return;
  }
  app.confs = app.data.conferences || [];
  try {
    const ws = await (await fetch("data/watch/status.json", { cache: "no-cache" })).json();
    for (const v of Object.values(ws)) app.watch[String(v.acronym || "").toUpperCase()] = v;
  } catch { /* the watch status is optional */ }
  app.areas = app.data.areas || {};
  for (const c of app.confs) app.byId.set(c.id, c);
  loadPlan();
  pubs = createPubs({ app, store, toast, download, locale, renderView });
  applyTexts();
  renderFilters();
  renderView();
  setInterval(tick, 30000);
}

init();
