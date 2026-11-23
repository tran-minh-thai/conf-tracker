// SPDX-License-Identifier: MIT
// "Publications & points" view: the user's own rule documents, their publications
// (added by DOI, link or title through Crossref), facts per publication with their
// source, points and bonus per publication, and totals per academic period.
import { FACTS as FACT_KEYS, authorShare, checkPack, findInList, localizePack, manualRules, parseListTable, periodYear, quotaFor, scoreWithPacks, valueForYear } from "./rules.js";
import { crossrefSearchUrl, crossrefUrl, fromCrossref, guessSeries, journalFacts, journalIndex, parseDoi, parseSjrCsv, sjrFacts } from "./scholar.js";
import { packFromCsv, packToCsv, sheetAliases, sheetVocab } from "./packcsv.js";
import { STRINGS } from "./i18n.js";
import { describeCondition, draftProblems, editorChange, editorClick, fromDraft, renderEditor, toDraft } from "./packedit.js";
import { csvCell, escapeHtml as h, safeUrl } from "./core.js";
import { icon } from "./icons.js";

const KEYS = { pubs: "conf_tracker_pubs_v1", packs: "conf_tracker_packs_v1", sjr: "conf_tracker_sjr_v1", period: "conf_tracker_period_start" };
const SAMPLES = { points: "data/rules/hdgsnn-cntt-2025.json", bonus: "data/rules/sample-university-bonus.json", hours: "data/rules/sample-research-hours.json" };
const ROLES = ["points", "bonus", "hours"];
const ROLE_LABEL = { points: "packPoints", bonus: "packBonus", hours: "packHours" };
const ROLE_HINT = { points: "packPointsHint", bonus: "packBonusHint", hours: "packHoursHint" };
const TRI = ["", "yes", "no"];
const BOOL_FACTS = ["international_journal", "issn_online", "scopus_indexed", "has_isbn", "peer_reviewed", "full_paper", "nafosted_list", "reputable_publisher", "institution_journal", "held_abroad"];
const ENUMS = {
  kind: ["", "journal", "conference", "book_chapter"],
  wos_index: ["", "SCI", "SCIE", "SSCI", "AHCI", "ESCI", "none"],
  scopus_quartile: ["", "Q1", "Q2", "Q3", "Q4", "none"],
  core_rank: ["", "A*", "A", "B", "C", "none"],
  conference_scope: ["", "international", "national"],
};

export function createPubs(ctx) {
  const { store, toast, download } = ctx;
  const t = (...a) => ctx.app.t(...a);
  const st = {
    pubs: store.get(KEYS.pubs, []) || [],
    packs: { points: null, bonus: null, hours: null, ...(store.get(KEYS.packs, {}) || {}) },
    sjr: store.get(KEYS.sjr, null),
    periodStart: Number(store.raw(KEYS.period)) || 1,
    lookup: { busy: false, results: null, error: "" },
    openFacts: new Set(),
    pasteFor: null,
    edit: null,          // {role, draft, problems}: the table being edited
    dashYear: null,      // academic year shown in the dashboard (first calendar year)
  };
  // Saved publications gain the facts the journal data states (only facts still unknown).
  if (st.pubs.length && ctx.journalInfo) {
    ctx.journalInfo().then((info) => { if (info) { st.pubs.forEach(autofill); save(); ctx.renderView(); } });
  }
  // Crossref work types in the page language; an unlisted type is shown as Crossref names it.
  const CR_TYPES = { "journal-article": "v_kind_journal", "proceedings-article": "v_kind_conference", "book-chapter": "v_kind_book_chapter",
    "book-part": "v_kind_book_chapter", "book-section": "v_kind_book_chapter", book: "crBook", "posted-content": "crPreprint",
    dissertation: "crThesis", report: "crReport", dataset: "crDataset", "edited-book": "crBook", monograph: "crBook" };
  const crType = (type) => (CR_TYPES[type] ? t(CR_TYPES[type]) : t("crOther", { type: type || "?" }));
  // Packs as shown: their text in the page language where the pack gives it (scoring is unchanged).
  const shown = (role) => localizePack(st.packs[role], ctx.app.lang);
  const view = () => ({ points: shown("points"), bonus: shown("bonus"), hours: shown("hours") });
  const save = () => {
    if (!store.set(KEYS.pubs, st.pubs) || !store.set(KEYS.packs, st.packs)) toast(t("storageFull"));
  };

  // ---- scoring -------------------------------------------------------------------
  function factsOf(p) {
    const f = { ...p.facts, issn: (p.issn || []).join(" "), venue: p.venue };
    if (p.month && f.month == null) f.month = p.month;
    if (p.list_entry && st.packs.points) {
      // A manual choice of list entry (for grouped journals without one ISSN).
      const e = (st.packs.points.list || []).find((x) => x.id === p.list_entry);
      if (e) { f.issn = (e.issn || []).join(" ") || f.issn; f.venue = e.name; }
    }
    return f;
  }
  const score = (p) => scoreWithPacks(view(), factsOf(p));
  const authorsOf = (p) => p.author_count ?? ((p.authors || []).length || undefined);
  /** This lecturer's hours for a publication: {total, share, mine, missing}. */
  function myHours(p, r = score(p)) {
    if (!r.hours) return null;
    const total = r.hours.value;
    const { share, missing } = authorShare(st.packs.hours, authorsOf(p), p.my_role);
    return { total, share, mine: share == null ? null : total * share, missing };
  }
  /** Month the academic year starts: the hours table decides it when it says, else the user's choice. */
  const startMonth = () => st.packs.hours?.period_start_month || st.periodStart;
  const periodLabel = (y) => (startMonth() <= 1 ? String(y) : `${y}-${y + 1}`);

  // ---- auto-fill -------------------------------------------------------------------
  let jIndex = { src: null, map: null };
  function autofill(pub) {
    const sources = { ...(pub.sources || {}) };
    // Sources are stored as codes and translated when shown.
    for (const k of Object.keys(pub.facts)) sources[k] = sources[k] || "crossref";
    // Earlier versions read a print-only Crossref ISSN as "no online ISSN"; Crossref cannot state that.
    if (pub.facts.issn_online === false && sources.issn_online === "crossref") { delete pub.facts.issn_online; delete sources.issn_online; }
    const fromSjr = sjrFacts(st.sjr, pub.issn);
    if (fromSjr) {
      pub.facts.scopus_indexed = true;
      pub.facts.scopus_quartile = fromSjr.scopus_quartile;
      sources.scopus_indexed = sources.scopus_quartile = `sjr:${fromSjr.sjr_year || ""}`;
    }
    if (pub.facts.kind === "journal" && st.packs.points) {
      const hit = findInList(st.packs.points, { issn: (pub.issn || []).join(" "), venue: pub.venue });
      if (hit) { pub.facts.international_journal = false; sources.international_journal = "list"; }
    }
    if (pub.facts.kind === "journal" && ctx.app.journalInfo) {
      if (jIndex.src !== ctx.app.journalInfo) jIndex = { src: ctx.app.journalInfo, map: journalIndex(ctx.app.journalInfo) };
      // Only facts no other source has stated: the domestic list and the user win.
      for (const [k, v] of Object.entries(journalFacts(jIndex.map, pub.issn))) {
        if (pub.facts[k] == null) { pub.facts[k] = v; sources[k] = "openalex"; }
      }
    }
    if (pub.facts.kind === "conference") {
      const series = guessSeries(pub, ctx.app.confs);
      if (series) {
        pub.series_acronym = series.acronym;
        if (series.rank?.core) { pub.facts.core_rank = series.rank.core; sources.core_rank = "core"; }
      }
    }
    pub.sources = sources;
    return pub;
  }

  async function lookup(input) {
    const q = input.trim();
    if (!q) return;
    st.lookup = { busy: true, results: null, error: "" };
    ctx.renderView();
    try {
      const doi = parseDoi(q);
      if (doi) {
        const res = await fetch(crossrefUrl(doi));
        if (res.status === 404) throw new Error(t("doiNotFound", { doi }));
        if (!res.ok) throw new Error(`Crossref HTTP ${res.status}`);
        const rec = fromCrossref((await res.json()).message);
        await ctx.journalInfo?.();
        addPub(rec);
        st.lookup = { busy: false, results: null, error: "" };
      } else if (/^https?:\/\//i.test(q)) {
        throw new Error(t("noDoiInLink"));
      } else {
        const res = await fetch(crossrefSearchUrl(q));
        if (!res.ok) throw new Error(`Crossref HTTP ${res.status}`);
        const items = (await res.json()).message.items || [];
        st.lookup = { busy: false, results: items.map((i) => ({ doi: i.DOI, title: (i.title || [])[0] || "", venue: (i["container-title"] || [])[0] || "", year: i.issued?.["date-parts"]?.[0]?.[0] || "", type: i.type })), error: "" };
      }
    } catch (err) {
      st.lookup = { busy: false, results: null, error: err.message || String(err) };
    }
    ctx.renderView();
  }

  function addPub(rec) {
    if (rec.doi && st.pubs.some((p) => p.doi === rec.doi)) { toast(t("pubExists")); return; }
    const pub = autofill({ id: `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, added: new Date().toISOString(), ...rec });
    st.pubs.unshift(pub);
    st.openFacts.add(pub.id);
    save();
    toast(t("pubAdded"));
  }

  // ---- rendering --------------------------------------------------------------------
  const money = (v, unit) => (unit === "VND"
    ? `${new Intl.NumberFormat(ctx.locale()).format(v)} ${t("currencyVnd")}`
    : unit === "hours" ? `${new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: 1 }).format(v)} ${t("hoursUnit")}`
      : `${new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: 2 }).format(v)} ${t("pointsUnit")}`);

  function packPanel(role) {
    const pack = shown(role);
    const label = t(ROLE_LABEL[role]);
    if (st.edit?.role === role) {
      return `<section class="panel pad pack editing"><h3>${icon("clipboard")}${h(t("edHeading", { what: label }))}</h3>
        ${st.edit.problems?.length ? `<div class="warnbox">${icon("warn")}${h(t("packInvalid", { n: st.edit.problems.length }))}: ${h(st.edit.problems.slice(0, 4).join("; "))}</div>` : ""}
        ${renderEditor(st.edit.draft, role, t)}</section>`;
    }
    if (!pack) {
      return `<section class="panel pad pack">
        <h3>${h(label)}</h3>
        <p class="hint">${h(t(ROLE_HINT[role]))}</p>
        <div class="actions left">
          <button type="button" class="btn primary" data-pact="sample-edit" data-role="${role}">${icon("clipboard")}${h(t("packStartSample"))}</button>
          <button type="button" class="btn" data-pact="sample-sheet" data-role="${role}">${icon("download")}${h(t("packSampleSheet"))}</button>
          <button type="button" class="btn" data-pact="import" data-role="${role}">${icon("upload")}${h(t("packImport"))}</button>
        </div>
        <p class="hint">${h(t("packSheetHint"))}</p>
      </section>`;
    }
    const problems = checkPack(st.packs[role]);
    const manual = manualRules(pack);
    const otherLang = pack.language && pack.language !== ctx.app.lang && !pack.inLang;
    return `<section class="panel pad pack">
      <h3>${h(label)}: ${h(pack.title)}</h3>
      ${otherLang ? `<p class="hint">${h(t("packOtherLang", { lang: t(`lang_${pack.language}`, {}, pack.language) }))}</p>` : ""}
      ${isOldSample(role) ? `<p class="hint">${h(t(st.packs[role].translations ? "packNewerSample" : "packOldSample"))} <button type="button" class="btn small" data-pact="sample" data-role="${role}">${h(t("packReloadSample"))}</button></p>` : ""}
      <p class="hint">${h(t("packSource"))}: ${h(pack.source?.document || "")}${pack.source?.checked ? ` · ${h(t("feesChecked", { date: pack.source.checked }))}` : ""}</p>
      ${pack.source?.warning ? `<p class="warnbox">${icon("warn")}${h(pack.source.warning)}</p>` : ""}
      ${problems.length ? `<p class="warnbox">${h(t("packInvalid", { n: problems.length }))}: ${h(problems.slice(0, 3).join("; "))}</p>` : ""}
      ${role === "hours" ? hoursSettings(pack) : ""}
      ${(pack.ambiguities || []).length ? `<details><summary>${h(t("packAmbiguities", { n: pack.ambiguities.length }))}</summary><ul>${pack.ambiguities.map((a) => `<li>${h(a)}</li>`).join("")}</ul></details>` : ""}
      <details><summary>${h(t("packRules", { n: (pack.rules || []).length }))}</summary>
        <table class="rules"><thead><tr><th>#</th><th>${h(t("ruleLabel"))}</th><th>${h(t("ruleValue"))}</th></tr></thead><tbody>
        ${(pack.rules || []).map((r, i) => `<tr><td>${h(r.id)}</td><td>${h(r.label)}${r.note ? `<br><small class="muted">${h(r.note)}</small>` : ""}${r.when ? `<br><small class="muted cond">${h(describeCondition(r.when, t))}</small>` : ""}${r.valid ? `<br><small class="muted">${h(validText(r.valid))}</small>` : ""}</td>
          <td>${r.manual ? `${h(money(r.range.min, pack.unit))} – ${h(money(r.range.max, pack.unit))}`
            : `<input type="number" min="0" step="any" class="num" data-rule-value="${i}" data-role="${role}" value="${h(r.value)}" aria-label="${h(t("ruleValue"))}" />`}</td></tr>`).join("")}
        </tbody></table>
        ${manual.length ? `<p class="hint">${h(t("manualNote"))}</p>` : ""}
      </details>
      ${(pack.list || []).length || role === "points" ? `<details><summary>${h(t("packList", { n: (pack.list || []).length, label: pack.list_label || t("listDefault") }))}</summary>
        <table class="rules"><thead><tr><th>${h(t("listName"))}</th><th>ISSN</th><th>${h(t("listPoints"))}</th></tr></thead><tbody>
        ${(pack.list || []).map((e) => `<tr><td>${h(e.name)}${(e.notes || []).length ? `<br><small class="muted">${h(e.notes.join("; "))}</small>` : ""}</td><td>${h((e.issn || []).join(", ") || "—")}</td><td>${h(e.raw || e.history.map((s) => `${s.max}${s.from ? ` (${s.from}+)` : ""}`).join("; "))}</td></tr>`).join("")}
        </tbody></table>
        <button type="button" class="btn small" data-pact="paste" data-role="${role}">${icon("clipboard")}${h(t("listPaste"))}</button>
        ${st.pasteFor === role ? `<div class="paste"><p class="hint">${h(t("listPasteHint"))}</p>
          <textarea id="list-paste" rows="6" placeholder="TT\t...\tISSN\t...\t..."></textarea>
          <button type="button" class="btn primary small" data-pact="paste-apply" data-role="${role}">${h(t("listPasteApply"))}</button></div>` : ""}
      </details>` : ""}
      <div class="actions left">
        <button type="button" class="btn small primary" data-pact="ed-open" data-role="${role}">${icon("clipboard")}${h(t("packEdit"))}</button>
        <button type="button" class="btn small" data-pact="export-sheet" data-role="${role}">${icon("download")}${h(t("packExportSheet"))}</button>
        <button type="button" class="btn small" data-pact="export" data-role="${role}">${icon("download")}${h(t("packExport"))}</button>
        <button type="button" class="btn small" data-pact="import" data-role="${role}">${icon("upload")}${h(t("packReplace"))}</button>
        <button type="button" class="btn small" data-pact="remove" data-role="${role}">${icon("x")}${h(t("packRemove"))}</button>
      </div>
      <p class="hint">${h(t("packSavedHere"))}</p>
    </section>`;
  }

  // A sample loaded earlier and never edited, whose published version has changed since.
  const sampleTitles = {};
  function isOldSample(role) {
    const pk = st.packs[role];
    if (!pk || pk.source?.edited || !SAMPLES[role].endsWith(`/${pk.id}.json`)) return false;
    if (!(role in sampleTitles)) {
      sampleTitles[role] = null;
      fetch(SAMPLES[role], { cache: "no-cache" }).then((r) => r.json()).then((x) => { sampleTitles[role] = x.title; ctx.renderView(); }).catch(() => {});
    }
    return sampleTitles[role] != null && sampleTitles[role] !== pk.title;
  }
  const fmtMonth = (d) => { const [y, m] = d.split("-"); return `${m}/${y}`; };
  const validText = (v) => (v.from && v.until ? t("validBetween", { from: fmtMonth(v.from), until: fmtMonth(v.until) })
    : v.from ? t("validFrom", { from: fmtMonth(v.from) }) : t("validUntil", { until: fmtMonth(v.until) }));

  function hoursSettings(pack) {
    const sh = pack.share || { scheme: "full" };
    const pct = (x) => new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: 2 }).format(x * 100);
    const quota = (pack.quota || []).map((q) => `${q.from ? t("quotaFrom", { date: q.from.split("-").reverse().join("/") }) : t("quotaAlways")}: ${money(q.hours, "hours")}`);
    return `<ul class="facts-list">
      <li>${h(t("edPeriodMonth"))}: ${h((pack.period_start_month || 1) <= 1 ? t("periodCalendar") : t("periodFrom", { m: pack.period_start_month }))}</li>
      <li>${h(t("edShare"))}: ${h(t(`share_${sh.scheme}`))}${sh.scheme === "main_plus_equal" ? ` (${h(t("shareMainPct", { p: pct(sh.main) }))})` : ""}</li>
      <li>${h(t("edQuota"))}: ${quota.length ? h(quota.join("; ")) : h(t("quotaNone"))}</li>
    </ul>`;
  }

  function sjrPanel() {
    return `<section class="panel pad pack">
      <h3>${h(t("sjrTitle"))}</h3>
      <p class="hint">${h(t("sjrHint"))} <a href="https://www.scimagojr.com/journalrank.php" target="_blank" rel="noopener">scimagojr.com</a></p>
      ${st.sjr ? `<p>${h(t("sjrLoaded", { n: new Intl.NumberFormat(ctx.locale()).format(st.sjr.rows), year: st.sjr.year || "?" }))}</p>` : ""}
      <div class="actions left">
        <button type="button" class="btn" data-pact="sjr-import">${icon("upload")}${h(t("sjrImport"))}</button>
        ${st.sjr ? `<button type="button" class="btn small" data-pact="sjr-remove">${icon("x")}${h(t("packRemove"))}</button>` : ""}
      </div>
    </section>`;
  }

  function sourceLabel(code) {
    if (!code) return "";
    if (code.startsWith("sjr:")) return `Scimago ${code.slice(4)}`.trim();
    return { crossref: "Crossref", openalex: "OpenAlex", list: t("srcDomesticList"), core: t("srcCore"), you: t("srcYou") }[code] || code;
  }

  function factField(p, key) {
    const f = p.facts;
    const src = sourceLabel(p.sources?.[key]);
    const label = `<span>${h(t(`f_${key}`))}${src ? ` <small class="src" title="${h(src)}">●</small>` : ""}</span>`;
    if (ENUMS[key]) {
      return `<label class="field">${label}<select data-fact="${key}" data-pub="${h(p.id)}">
        ${ENUMS[key].map((v) => `<option value="${h(v)}" ${String(f[key] ?? "") === v ? "selected" : ""}>${h(v ? t(`v_${key}_${v}`, {}, v) : "?")}</option>`).join("")}</select></label>`;
    }
    if (BOOL_FACTS.includes(key)) {
      const cur = f[key] === true ? "yes" : f[key] === false ? "no" : "";
      return `<label class="field">${label}<select data-fact="${key}" data-pub="${h(p.id)}">
        ${TRI.map((v) => `<option value="${v}" ${cur === v ? "selected" : ""}>${h(v ? t(`tri_${v}`) : "?")}</option>`).join("")}</select></label>`;
    }
    if (key === "month") {
      const cur = p.facts.month ?? p.month ?? "";
      return `<label class="field">${label}<select data-fact="month" data-pub="${h(p.id)}"><option value="">?</option>${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((m) => `<option value="${m}" ${Number(cur) === m ? "selected" : ""}>${m}</option>`).join("")}</select></label>`;
    }
    const type = key === "impact_factor" || key === "year" ? "number" : "text";
    return `<label class="field">${label}<input type="${type}" step="any" data-fact="${key}" data-pub="${h(p.id)}" value="${h(f[key] ?? "")}" /></label>`;
  }

  /** Where the facts no open source states can be found: Scimago file, Clarivate's journal list. */
  function journalHints(p) {
    if (p.facts.kind !== "journal") return "";
    const out = [];
    if (p.facts.scopus_quartile == null && !st.sjr) out.push(`<p class="hint wide">${h(t("needSjr"))}</p>`);
    const issn = (p.issn || [])[0];
    if (issn && (p.facts.wos_index == null || p.facts.impact_factor == null)) {
      out.push(`<p class="hint wide"><a href="https://mjl.clarivate.com/search-results?issn=${encodeURIComponent(issn)}" target="_blank" rel="noopener">${h(t("checkMjl"))} (${h(issn)})</a></p>`);
    }
    return out.join("");
  }

  function relevantFacts(p) {
    const k = p.facts.kind;
    const common = ["kind", "year", "month"];
    if (k === "journal") return [...common, "international_journal", "wos_index", "impact_factor", "scopus_indexed", "scopus_quartile", "issn_online", "nafosted_list", "institution_journal"];
    if (k === "conference") return [...common, "conference_scope", "held_abroad", "core_rank", "full_paper", "peer_reviewed", "has_isbn", "scopus_indexed", "scopus_quartile", "series"];
    if (k === "book_chapter") return [...common, "wos_index", "scopus_indexed", "reputable_publisher", "has_isbn"];
    return common;
  }

  function resultBlock(label, r, unit) {
    if (!r) return "";
    const missing = r.missing.length ? `<div class="hint">${h(t("couldRaise"))}: ${r.unknown.slice(0, 3).map((u) => `${h(u.label)} → ${h(money(u.value, unit))} (${h(t("needs"))} ${u.needs.map((n) => h(t(`f_${n}`))).join(", ")})`).join("; ")}</div>` : "";
    return `<div class="result"><div class="rlabel">${h(label)}</div>
      <div class="rvalue">${r.value ? h(money(r.value, unit)) : "—"}</div>
      <div class="hint">${r.rule ? `${h(t("byRule"))}: ${h(r.rule.from === "list" ? `${t("listDefault")}: ${r.rule.label}` : `${r.rule.id}. ${r.rule.label}`)}` : h(t("noRuleMatched"))}</div>
      ${missing}</div>`;
  }

  function hoursBlock(p, r) {
    const hr = myHours(p, r);
    if (!hr) return "";
    const n = authorsOf(p);
    const base = resultBlock(t("packHours"), r.hours, "hours");
    const mine = !hr.total ? "" : hr.mine == null
      ? `<div class="hint warn-text">${h(t(hr.missing === "role" ? "shareNeedsRole" : "shareNeedsAuthors"))}</div>`
      : `<div class="mine">${h(t("yourShare"))}: <strong>${h(money(hr.mine, "hours"))}</strong> <span class="muted">(${h(t("shareOf", { p: new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: 1 }).format(hr.share * 100), n: n ?? "?" }))})</span></div>`;
    return base.replace(/<\/div>$/, `${mine}</div>`);
  }

  function pubCard(p) {
    const r = score(p);
    const open = st.openFacts.has(p.id);
    const doiUrl = p.doi ? `https://doi.org/${encodeURIComponent(p.doi).replace(/%2F/g, "/")}` : safeUrl(p.url);
    const listOpts = st.packs.points?.list || [];
    return `<article class="pub" data-pub="${h(p.id)}">
      <div class="pub-head">
        <div>
          <h3>${doiUrl ? `<a href="${h(doiUrl)}" target="_blank" rel="noopener">${h(p.title || t("untitled"))}</a>` : h(p.title || t("untitled"))}</h3>
          <div class="sub">${h((p.authors || []).slice(0, 6).join(", "))}${(p.authors || []).length > 6 ? " …" : ""}</div>
          <div class="sub">${h(p.venue || "")}${p.series_acronym ? ` (${h(p.series_acronym)})` : ""} · ${h(p.facts.year || "?")}${p.doi ? ` · DOI ${h(p.doi)}` : ""}</div>
        </div>
        <div class="results">
          ${st.packs.points ? resultBlock(t("packPoints"), r.points, st.packs.points.unit) : ""}
          ${st.packs.bonus ? resultBlock(t("packBonus"), r.bonus, st.packs.bonus.unit) : ""}
          ${st.packs.hours ? hoursBlock(p, r) : ""}
          ${!st.packs.points && !st.packs.bonus && !st.packs.hours ? `<p class="hint">${h(t("noPacks"))}</p>` : ""}
        </div>
      </div>
      <div class="actions left">
        <button type="button" class="btn small" data-pact="facts" data-pub="${h(p.id)}">${h(open ? t("hideFacts") : t("editFacts"))}</button>
        <button type="button" class="btn small" data-pact="delete" data-pub="${h(p.id)}">${icon("x")}${h(t("planRemove"))}</button>
      </div>
      ${open ? `<div class="facts">
        ${relevantFacts(p).map((k) => factField(p, k)).join("")}
        ${st.packs.hours ? `<label class="field"><span>${h(t("authorCount"))}</span><input type="number" min="1" step="1" data-pubfield="author_count" data-pub="${h(p.id)}" value="${h(authorsOf(p) ?? "")}" /></label>
        <label class="field"><span>${h(t("myRole"))}</span><select data-pubfield="my_role" data-pub="${h(p.id)}">
          ${["", "main", "co"].map((v) => `<option value="${v}" ${(p.my_role || "") === v ? "selected" : ""}>${h(v ? t(`role_${v}`) : "?")}</option>`).join("")}</select></label>` : ""}
        <label class="field"><span>ISSN</span><input data-pubfield="issn" data-pub="${h(p.id)}" value="${h((p.issn || []).join(", "))}" /></label>
        ${listOpts.length && p.facts.kind === "journal" ? `<label class="field"><span>${h(t("listEntry"))}</span><select data-pubfield="list_entry" data-pub="${h(p.id)}">
          <option value="">${h(t("listAuto"))}</option>${listOpts.map((e) => `<option value="${h(e.id)}" ${p.list_entry === e.id ? "selected" : ""}>${h(e.name)}</option>`).join("")}</select></label>` : ""}
        ${journalHints(p)}
        <p class="hint wide">${h(t("factsHint"))}</p>
      </div>` : ""}
    </article>`;
  }

  /** Totals per academic year: publications, points, bonus, this lecturer's hours, quota. */
  function yearRows() {
    const start = startMonth();
    const rows = new Map();
    let undated = [];
    for (const p of st.pubs) {
      const y = periodYear(p.facts.year, p.facts.month ?? p.month, start);
      const r = score(p);
      if (y == null) { undated.push(p); continue; }
      const row = rows.get(y) || { y, n: 0, kinds: {}, points: 0, bonus: 0, hours: 0, unknown: 0, noShare: 0 };
      row.n++;
      row.kinds[p.facts.kind || "?"] = (row.kinds[p.facts.kind || "?"] || 0) + 1;
      row.points += r.points?.value || 0;
      row.bonus += r.bonus?.value || 0;
      const hr = myHours(p, r);
      if (hr?.mine != null) row.hours += hr.mine; else if (hr?.total) row.noShare++;
      if ((r.points?.missing.length || 0) + (r.bonus?.missing.length || 0) + (r.hours?.missing.length || 0)) row.unknown++;
      rows.set(y, row);
    }
    return { rows: [...rows.values()].sort((a, b) => b.y - a.y), undated };
  }

  function dashboard() {
    const { rows, undated } = yearRows();
    const today = new Date();
    const thisYear = periodYear(today.getFullYear(), today.getMonth() + 1, startMonth());
    const years = [...new Set([thisYear, ...rows.map((r) => r.y)])].sort((a, b) => b - a);
    const y = years.includes(st.dashYear) ? st.dashYear : thisYear;
    const row = rows.find((r) => r.y === y) || { y, n: 0, kinds: {}, points: 0, bonus: 0, hours: 0, unknown: 0, noShare: 0 };
    const hp = st.packs.hours;
    const quota = hp ? quotaFor(hp, y) : null;
    const pct = quota ? Math.min(100, Math.round((row.hours / quota) * 100)) : 0;
    const diff = quota != null ? row.hours - quota : null;
    const nf = (v, d = 1) => new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: d }).format(v);
    const kinds = ["journal", "conference", "book_chapter"].filter((k) => row.kinds[k]).map((k) => `${row.kinds[k]} ${t(`dashKind_${k}`)}`).join(" · ");
    const tile = (ic, label, value, sub = "") => `<div class="dash-tile"><div class="dash-label">${icon(ic)}${h(label)}</div><div class="dash-value">${value}</div>${sub ? `<div class="dash-sub">${sub}</div>` : ""}</div>`;
    const hoursTile = hp ? `<div class="dash-tile wide">
        <div class="dash-label">${icon("clock")}${h(t("dashHours"))}</div>
        <div class="dash-value">${h(nf(row.hours))}${quota != null ? ` <span class="muted">/ ${h(nf(quota))} ${h(t("hoursUnit"))}</span>` : ` ${h(t("hoursUnit"))}`}</div>
        ${quota != null ? `<div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><span style="width:${pct}%" class="${diff >= 0 ? "done" : ""}"></span></div>
          <div class="dash-sub">${h(diff >= 0 ? t("dashOver", { h: nf(diff) }) : t("dashShort", { h: nf(-diff) }))}</div>` : `<div class="dash-sub">${h(t("quotaNone"))}</div>`}
        ${row.noShare ? `<div class="dash-sub warn-text">${h(t("dashNoShare", { n: row.noShare }))}</div>` : ""}
      </div>` : `<div class="dash-tile wide"><div class="dash-label">${icon("clock")}${h(t("dashHours"))}</div><div class="dash-sub">${h(t("dashNoHoursPack"))}</div></div>`;
    const manual = st.packs.bonus ? manualRules(shown("bonus")) : [];
    return `<section class="panel pad dash">
      <div class="toolbar"><h3 class="grow">${icon("chart")}${h(t("dashTitle"))}</h3>
        <label class="field inline">${h(t("dashYear"))}
          <select data-pact="dash-year">${years.map((v) => `<option value="${v}" ${v === y ? "selected" : ""}>${h(periodLabel(v))}</option>`).join("")}</select></label>
        ${hp?.period_start_month ? "" : `<label class="field inline">${h(t("periodStart"))}
          <select data-pact="period">${[1, 7, 8, 9, 10].map((m) => `<option value="${m}" ${st.periodStart === m ? "selected" : ""}>${h(m === 1 ? t("periodCalendar") : t("periodFrom", { m }))}</option>`).join("")}</select></label>`}
      </div>
      ${hp?.period_start_month ? `<p class="hint">${h(t("dashPeriodFromPack", { m: hp.period_start_month }))}</p>` : ""}
      <div class="dash-grid">
        ${tile("book", t("pubCount"), h(row.n), h(kinds))}
        ${st.packs.points ? tile("star", t("packPoints"), h(nf(row.points, 2)), "") : ""}
        ${st.packs.bonus ? tile("card", t("dashBonus"), h(money(row.bonus, st.packs.bonus.unit)), "") : ""}
        ${hoursTile}
      </div>
      ${row.unknown ? `<p class="hint warn-text">${icon("warn")}${h(t("dashMissing", { n: row.unknown }))}</p>` : ""}
      ${undated.length ? `<p class="hint warn-text">${icon("warn")}${h(t("dashUndated", { n: undated.length, titles: undated.slice(0, 3).map((p) => p.title || t("untitled")).join("; ") }))}</p>` : ""}
      ${rows.length ? `<details open><summary>${h(t("summaryTitle"))}</summary>
        <div class="table-scroll"><table class="rules"><thead><tr><th>${h(t("period"))}</th><th>${h(t("pubCount"))}</th>
        ${st.packs.points ? `<th>${h(t("packPoints"))}</th>` : ""}${st.packs.bonus ? `<th>${h(t("packBonus"))}</th>` : ""}${hp ? `<th>${h(t("dashHoursShort"))}</th><th>${h(t("edQuota"))}</th>` : ""}<th>${h(t("incomplete"))}</th></tr></thead><tbody>
        ${rows.map((r) => { const q = hp ? quotaFor(hp, r.y) : null; return `<tr><td>${h(periodLabel(r.y))}</td><td>${r.n}</td>${st.packs.points ? `<td>${h(nf(r.points, 2))}</td>` : ""}${st.packs.bonus ? `<td>${h(money(r.bonus, st.packs.bonus.unit))}</td>` : ""}${hp ? `<td>${h(nf(r.hours))}</td><td>${q == null ? "—" : `${h(nf(q))}${r.hours >= q ? " ✓" : ""}`}</td>` : ""}<td>${r.unknown}</td></tr>`; }).join("")}
        </tbody></table></div>
        <p class="hint">${h(t(hp ? "summaryNoteHours" : "summaryNote"))}</p></details>` : `<p class="hint">${h(t("noPubs"))}</p>`}
      ${manual.map((m) => `<p class="hint">ℹ️ ${h(m.label)}: ${h(money(m.range.min, st.packs.bonus.unit))} – ${h(money(m.range.max, st.packs.bonus.unit))}. ${h(m.note || "")}</p>`).join("")}
      <div class="actions left">
        <button type="button" class="btn small" data-pact="export-csv" ${st.pubs.length ? "" : "disabled"}>${icon("download")}CSV</button>
        <button type="button" class="btn small" data-pact="backup">${icon("download")}${h(t("backup"))}</button>
        <button type="button" class="btn small" data-pact="restore">${icon("upload")}${h(t("restore"))}</button>
      </div>
    </section>`;
  }

  function render(el) {
    const L = st.lookup;
    el.innerHTML = `
      <p class="hint">${h(t("pubsIntro"))}</p>
      ${dashboard()}
      <div class="packs">${ROLES.map(packPanel).join("")}${sjrPanel()}</div>
      <section class="panel pad">
        <h3>${h(t("addPub"))}</h3>
        <div class="copy-row">
          <input id="pub-input" placeholder="${h(t("addPubPlaceholder"))}" aria-label="${h(t("addPub"))}" />
          <button type="button" class="btn primary" data-pact="lookup" ${L.busy ? "disabled" : ""}>${h(L.busy ? t("looking") : t("lookup"))}</button>
          <button type="button" class="btn" data-pact="manual">${h(t("addManual"))}</button>
        </div>
        <p class="hint">${h(t("addPubHint"))}</p>
        ${L.error ? `<p class="warnbox">${h(L.error)}</p>` : ""}
        ${L.results ? `<ul class="search-results">${L.results.length ? L.results.map((r) => `<li><button type="button" class="btn small" data-pact="pick" data-doi="${h(r.doi)}">＋</button>
          ${h(r.title)} <span class="muted">· ${h(r.venue)} · ${h(r.year)} · ${h(crType(r.type))}</span></li>`).join("") : `<li>${h(t("noResults"))}</li>`}</ul>` : ""}
      </section>
      <div class="pubs">${st.pubs.map(pubCard).join("")}</div>`;
  }

  // ---- events --------------------------------------------------------------------------
  function pickFile(accept, withName = false) {
    return new Promise((resolve) => {
      const input = Object.assign(document.createElement("input"), { type: "file", accept });
      input.addEventListener("change", async () => {
        const f = input.files?.[0];
        if (!f) return resolve(null);
        const text = await f.text();
        resolve(withName ? { text, name: f.name } : text);
      });
      input.click();
    });
  }
  function downloadSheet(pack) {
    try {
      download(`${pack.id || "rules"}.csv`, packToCsv(localizePack(pack, ctx.app.lang), { ...sheetVocab(STRINGS[ctx.app.lang] || STRINGS.en), help: t("sheetHelp").split("\n") }), "text/csv;charset=utf-8");
    } catch (e) { toast(e.message); }
  }
  /** Read a picked rule file: a sheet (.csv, .txt, .tsv) or JSON. Returns a pack or null (after a toast). */
  function readPackFile(file, role) {
    if (/\.(csv|tsv|txt)$/i.test(file.name) || !file.text.trim().startsWith("{")) {
      const { pack, errors } = packFromCsv(file.text, st.packs[role] || { kind: role === "points" ? "points" : role, unit: role === "hours" ? "hours" : role === "bonus" ? "VND" : "points" },
        sheetAliases(Object.values(STRINGS).map(sheetVocab)));
      if (!pack) { toast(t("sheetErrors", { n: errors.length, first: errors.slice(0, 2).join("; ") })); return null; }
      return pack;
    }
    try { return JSON.parse(file.text); } catch { toast(t("packNotJson")); return null; }
  }
  function setPack(role, pack) {
    const problems = checkPack(pack);
    if (problems.length) { toast(t("packInvalid", { n: problems.length }) + `: ${problems[0]}`); return false; }
    st.packs[role] = pack;
    save();
    return true;
  }

  async function onClick(ev) {
    const b = ev.target.closest("[data-pact]");
    if (!b || b.tagName === "SELECT") return false;
    const role = b.dataset.role, id = b.dataset.pub;
    switch (b.dataset.pact) {
      case "sample": {
        const pack = await (await fetch(SAMPLES[role], { cache: "no-cache" })).json();
        if (setPack(role, pack)) toast(t("packLoaded"));
        break;
      }
      case "sample-edit": {
        const pack = await (await fetch(SAMPLES[role], { cache: "no-cache" })).json();
        if (setPack(role, pack)) st.edit = { role, draft: toDraft(localizeForEdit(pack)), problems: [] };
        break;
      }
      case "sample-sheet": downloadSheet(await (await fetch(SAMPLES[role], { cache: "no-cache" })).json()); return true;
      case "export-sheet": downloadSheet(st.packs[role]); return true;
      case "import": {
        const file = await pickFile(".csv,.tsv,.txt,text/csv,application/json,.json", true);
        if (!file) return true;
        const pack = readPackFile(file, role);
        if (pack && setPack(role, pack)) toast(t("packLoaded"));
        break;
      }
      case "ed-open": st.edit = { role, draft: toDraft(localizeForEdit(st.packs[role])), problems: [] }; break;
      case "ed-cancel": st.edit = null; break;
      case "ed-save": {
        const problems = draftProblems(st.edit.draft);
        if (problems.length) { st.edit.problems = problems; break; }
        const r = st.edit.role;
        const pack = fromDraft(st.edit.draft, localizeForEdit(st.packs[r]));
        pack.source = { ...pack.source, edited: new Date().toISOString().slice(0, 10) };
        if (setPack(r, pack)) { st.edit = null; toast(t("packSaved")); }
        break;
      }
      case "export":
        download(`${st.packs[role].id || role}.json`, JSON.stringify(st.packs[role], null, 1), "application/json");
        return true;
      case "remove":
        if (!confirm(t("confirmRemovePack"))) return true;
        st.packs[role] = null; if (st.edit?.role === role) st.edit = null; save(); break;
      case "paste": st.pasteFor = st.pasteFor === role ? null : role; break;
      case "paste-apply": {
        const { entries, errors } = parseListTable(document.getElementById("list-paste").value);
        if (!entries.length) { toast(t("listPasteFailed", { why: errors.join("; ") })); return true; }
        st.packs[role] = { ...st.packs[role], list: entries };
        st.pasteFor = null;
        save();
        toast(t("listPasted", { n: entries.length, bad: errors.length }));
        break;
      }
      case "sjr-import": {
        const text = await pickFile(".csv,text/csv");
        if (!text) return true;
        const year = Number((prompt(t("sjrYearPrompt"), String(new Date().getFullYear() - 1)) || "").trim()) || null;
        const parsed = parseSjrCsv(text, year);
        if (parsed.errors.length) { toast(parsed.errors[0]); return true; }
        st.sjr = parsed;
        if (!store.set(KEYS.sjr, parsed)) toast(t("storageFull"));
        st.pubs.forEach(autofill);
        save();
        toast(t("sjrLoaded", { n: parsed.rows, year: year || "?" }));
        break;
      }
      case "sjr-remove": st.sjr = null; store.remove(KEYS.sjr); break;
      case "lookup": lookup(document.getElementById("pub-input").value); return true;
      case "pick": {
        const res = await fetch(crossrefUrl(b.dataset.doi));
        if (res.ok) { const rec = fromCrossref((await res.json()).message); await ctx.journalInfo?.(); addPub(rec); }
        st.lookup = { busy: false, results: null, error: "" };
        break;
      }
      case "manual": addPub({ title: "", authors: [], venue: "", issn: [], facts: {}, doi: "" }); break;
      case "facts": st.openFacts.has(id) ? st.openFacts.delete(id) : st.openFacts.add(id); break;
      case "delete":
        if (!confirm(t("confirmDelete"))) return true;
        st.pubs = st.pubs.filter((p) => p.id !== id);
        save();
        break;
      case "export-csv": download("publications_points.csv", String.fromCharCode(0xfeff) + toCsv(), "text/csv;charset=utf-8"); return true;
      case "backup":
        download(`conf_tracker_research_${new Date().toISOString().slice(0, 10)}.json`,
          JSON.stringify({ app: "conf-tracker", kind: "research-backup", version: 1, exported: new Date().toISOString(), pubs: st.pubs, packs: st.packs }, null, 1), "application/json");
        return true;
      case "restore": {
        const text = await pickFile("application/json,.json");
        if (!text) return true;
        try {
          const d = JSON.parse(text);
          if (!Array.isArray(d.pubs)) throw new Error("no pubs");
          st.pubs = d.pubs.filter((p) => p && p.id && p.facts);
          if (d.packs) for (const r of ROLES) if (d.packs[r] && !checkPack(d.packs[r]).length) st.packs[r] = d.packs[r];
          save();
          toast(t("planImported", { n: st.pubs.length }));
        } catch { toast(t("packNotJson")); }
        break;
      }
      default:
        if (st.edit && b.dataset.pact.startsWith("ed-") && editorClick(st.edit.draft, b)) break;
        return false;
    }
    ctx.renderView();
    return true;
  }

  /**
   * The text to edit: in the page language when the pack has a translation for it. The edited text
   * then becomes the pack's own text, in that language.
   */
  function localizeForEdit(pack) {
    const lang = ctx.app.lang;
    if (!pack.translations?.[lang] || pack.language === lang) return pack;
    const { inLang, ...loc } = localizePack(pack, lang);
    const { [lang]: _, ...rest } = pack.translations;
    return { ...loc, language: lang, translations: Object.keys(rest).length ? rest : undefined };
  }

  function onChange(ev) {
    const el = ev.target;
    if (el.dataset.pact === "period") { st.periodStart = Number(el.value); store.setRaw(KEYS.period, String(st.periodStart)); ctx.renderView(); return true; }
    if (el.dataset.pact === "dash-year") { st.dashYear = Number(el.value); ctx.renderView(); return true; }
    if (el.dataset.ed && st.edit) { if (editorChange(st.edit.draft, el)) ctx.renderView(); return true; }
    if (el.dataset.ruleValue !== undefined) {
      const pack = st.packs[el.dataset.role];
      const v = Number(el.value);
      if (Number.isFinite(v) && v >= 0) { pack.rules[Number(el.dataset.ruleValue)].value = v; save(); ctx.renderView(); }
      return true;
    }
    const p = st.pubs.find((x) => x.id === el.dataset.pub);
    if (!p) return false;
    if (el.dataset.fact) {
      const k = el.dataset.fact;
      let v = el.value;
      if (BOOL_FACTS.includes(k)) v = v === "yes" ? true : v === "no" ? false : undefined;
      else if (k === "impact_factor" || k === "year" || k === "month") v = v === "" ? undefined : Number(v);
      else if (v === "") v = undefined;
      if (v === undefined) delete p.facts[k]; else p.facts[k] = v;
      p.sources = { ...(p.sources || {}), [k]: "you" };
      save();
      ctx.renderView();
      return true;
    }
    if (el.dataset.pubfield === "issn") {
      p.issn = el.value.split(/[\s,;]+/).filter(Boolean);
      autofill(p); save(); ctx.renderView(); return true;
    }
    if (el.dataset.pubfield === "list_entry") { p.list_entry = el.value || undefined; save(); ctx.renderView(); return true; }
    if (el.dataset.pubfield === "author_count") {
      const n = Number(el.value);
      p.author_count = el.value === "" || !Number.isInteger(n) || n < 1 ? undefined : n;
      save(); ctx.renderView(); return true;
    }
    if (el.dataset.pubfield === "my_role") { p.my_role = el.value || undefined; save(); ctx.renderView(); return true; }
    return false;
  }

  function toCsv() {
    const head = ["title", "authors", "venue", "year", "month", "doi", "kind", "points", "points_rule", "bonus", "bonus_rule",
      "hours_paper", "hours_rule", "author_count", "my_role", "hours_mine", "missing_facts"];
    const rows = st.pubs.map((p) => {
      const r = score(p);
      const hr = myHours(p, r);
      return [p.title, (p.authors || []).join("; "), p.venue, p.facts.year || "", p.facts.month ?? p.month ?? "", p.doi, p.facts.kind || "",
        r.points?.value ?? "", r.points?.rule?.label || "", r.bonus?.value ?? "", r.bonus?.rule?.label || "",
        r.hours?.value ?? "", r.hours?.rule?.label || "", authorsOf(p) ?? "", p.my_role || "", hr?.mine ?? "",
        [...new Set([...(r.points?.missing || []), ...(r.bonus?.missing || []), ...(r.hours?.missing || [])])].join(" ")];
    });
    return [head, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
  }

  return { render, onClick, onChange, onKey: (ev) => {
    if (ev.target.id === "pub-input" && ev.key === "Enter") { lookup(ev.target.value); return true; }
    return false;
  }, state: st, valueForYear };
}
