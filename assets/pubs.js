// SPDX-License-Identifier: MIT
// "Publications & points" view: the user's own rule documents, their publications
// (added by DOI, link or title through Crossref), facts per publication with their
// source, points and bonus per publication, and totals per academic period.
import { checkPack, findInList, localizePack, manualRules, parseListTable, scoreWithPacks, valueForYear } from "./rules.js";
import { crossrefSearchUrl, crossrefUrl, fromCrossref, guessSeries, parseDoi, parseSjrCsv, periodOf, sjrFacts } from "./scholar.js";
import { csvCell, escapeHtml as h, safeUrl } from "./core.js";
import { icon } from "./icons.js";

const KEYS = { pubs: "conf_tracker_pubs_v1", packs: "conf_tracker_packs_v1", sjr: "conf_tracker_sjr_v1", period: "conf_tracker_period_start" };
const SAMPLES = { points: "data/rules/hdgsnn-cntt-2025.json", bonus: "data/rules/sample-university-bonus.json" };
const TRI = ["", "yes", "no"];
const BOOL_FACTS = ["international_journal", "issn_online", "scopus_indexed", "has_isbn", "peer_reviewed", "full_paper", "nafosted_list", "reputable_publisher", "institution_journal"];
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
    packs: store.get(KEYS.packs, { points: null, bonus: null }) || { points: null, bonus: null },
    sjr: store.get(KEYS.sjr, null),
    periodStart: Number(store.raw(KEYS.period)) || 1,
    lookup: { busy: false, results: null, error: "" },
    openFacts: new Set(),
    pasteFor: null,
  };
  // Crossref work types in the page language; an unlisted type is shown as Crossref names it.
  const CR_TYPES = { "journal-article": "v_kind_journal", "proceedings-article": "v_kind_conference", "book-chapter": "v_kind_book_chapter",
    "book-part": "v_kind_book_chapter", "book-section": "v_kind_book_chapter", book: "crBook", "posted-content": "crPreprint",
    dissertation: "crThesis", report: "crReport", dataset: "crDataset", "edited-book": "crBook", monograph: "crBook" };
  const crType = (type) => (CR_TYPES[type] ? t(CR_TYPES[type]) : t("crOther", { type: type || "?" }));
  // Packs as shown: their text in the page language where the pack gives it (scoring is unchanged).
  const shown = (role) => localizePack(st.packs[role], ctx.app.lang);
  const view = () => ({ points: shown("points"), bonus: shown("bonus") });
  const save = () => {
    if (!store.set(KEYS.pubs, st.pubs) || !store.set(KEYS.packs, st.packs)) toast(t("storageFull"));
  };

  // ---- scoring -------------------------------------------------------------------
  function factsOf(p) {
    const f = { ...p.facts, issn: (p.issn || []).join(" "), venue: p.venue };
    if (p.list_entry && st.packs.points) {
      // A manual choice of list entry (for grouped journals without one ISSN).
      const e = (st.packs.points.list || []).find((x) => x.id === p.list_entry);
      if (e) { f.issn = (e.issn || []).join(" ") || f.issn; f.venue = e.name; }
    }
    return f;
  }
  const score = (p) => scoreWithPacks(view(), factsOf(p));

  // ---- auto-fill -------------------------------------------------------------------
  function autofill(pub) {
    const sources = { ...(pub.sources || {}) };
    // Sources are stored as codes and translated when shown.
    for (const k of Object.keys(pub.facts)) sources[k] = sources[k] || "crossref";
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
        addPub(fromCrossref((await res.json()).message));
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
    : `${new Intl.NumberFormat(ctx.locale(), { maximumFractionDigits: 2 }).format(v)} ${t("pointsUnit")}`);

  function packPanel(role) {
    const pack = shown(role);
    const label = t(role === "points" ? "packPoints" : "packBonus");
    if (!pack) {
      return `<section class="panel pad pack">
        <h3>${h(label)}</h3>
        <p class="hint">${h(t(role === "points" ? "packPointsHint" : "packBonusHint"))}</p>
        <div class="actions left">
          <button type="button" class="btn primary" data-pact="import" data-role="${role}">${icon("upload")}${h(t("packImport"))}</button>
          <button type="button" class="btn" data-pact="sample" data-role="${role}">${h(t("packUseSample"))}</button>
        </div>
      </section>`;
    }
    const problems = checkPack(st.packs[role]);
    const manual = manualRules(pack);
    const otherLang = pack.language && pack.language !== ctx.app.lang && !pack.inLang;
    return `<section class="panel pad pack">
      <h3>${h(label)}: ${h(pack.title)}</h3>
      ${otherLang ? `<p class="hint">${h(t("packOtherLang", { lang: t(`lang_${pack.language}`, {}, pack.language) }))}</p>` : ""}
      ${!st.packs[role].translations && SAMPLES[role].endsWith(`/${st.packs[role].id}.json`) ? `<p class="hint">${h(t("packOldSample"))} <button type="button" class="btn small" data-pact="sample" data-role="${role}">${h(t("packReloadSample"))}</button></p>` : ""}
      <p class="hint">${h(t("packSource"))}: ${h(pack.source?.document || "")}${pack.source?.checked ? ` · ${h(t("feesChecked", { date: pack.source.checked }))}` : ""}</p>
      ${pack.source?.warning ? `<p class="warnbox">${icon("warn")}${h(pack.source.warning)}</p>` : ""}
      ${problems.length ? `<p class="warnbox">${h(t("packInvalid", { n: problems.length }))}: ${h(problems.slice(0, 3).join("; "))}</p>` : ""}
      ${(pack.ambiguities || []).length ? `<details><summary>${h(t("packAmbiguities", { n: pack.ambiguities.length }))}</summary><ul>${pack.ambiguities.map((a) => `<li>${h(a)}</li>`).join("")}</ul></details>` : ""}
      <details><summary>${h(t("packRules", { n: (pack.rules || []).length }))}</summary>
        <table class="rules"><thead><tr><th>#</th><th>${h(t("ruleLabel"))}</th><th>${h(t("ruleValue"))}</th></tr></thead><tbody>
        ${(pack.rules || []).map((r, i) => `<tr><td>${h(r.id)}</td><td>${h(r.label)}${r.note ? `<br><small class="muted">${h(r.note)}</small>` : ""}</td>
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
        <button type="button" class="btn small" data-pact="export" data-role="${role}">${icon("download")}${h(t("packExport"))}</button>
        <button type="button" class="btn small" data-pact="import" data-role="${role}">${icon("upload")}${h(t("packReplace"))}</button>
        <button type="button" class="btn small" data-pact="remove" data-role="${role}">${icon("x")}${h(t("packRemove"))}</button>
      </div>
    </section>`;
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
    return { crossref: "Crossref", list: t("srcDomesticList"), core: t("srcCore"), you: t("srcYou") }[code] || code;
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
    const type = key === "impact_factor" || key === "year" ? "number" : "text";
    return `<label class="field">${label}<input type="${type}" step="any" data-fact="${key}" data-pub="${h(p.id)}" value="${h(f[key] ?? "")}" /></label>`;
  }

  function relevantFacts(p) {
    const k = p.facts.kind;
    const common = ["kind", "year"];
    if (k === "journal") return [...common, "international_journal", "wos_index", "impact_factor", "scopus_indexed", "scopus_quartile", "issn_online", "nafosted_list", "institution_journal"];
    if (k === "conference") return [...common, "conference_scope", "core_rank", "full_paper", "peer_reviewed", "has_isbn", "scopus_indexed", "scopus_quartile", "series"];
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
          ${!st.packs.points && !st.packs.bonus ? `<p class="hint">${h(t("noPacks"))}</p>` : ""}
        </div>
      </div>
      <div class="actions left">
        <button type="button" class="btn small" data-pact="facts" data-pub="${h(p.id)}">${h(open ? t("hideFacts") : t("editFacts"))}</button>
        <button type="button" class="btn small" data-pact="delete" data-pub="${h(p.id)}">${icon("x")}${h(t("planRemove"))}</button>
      </div>
      ${open ? `<div class="facts">
        ${relevantFacts(p).map((k) => factField(p, k)).join("")}
        <label class="field"><span>ISSN</span><input data-pubfield="issn" data-pub="${h(p.id)}" value="${h((p.issn || []).join(", "))}" /></label>
        ${listOpts.length && p.facts.kind === "journal" ? `<label class="field"><span>${h(t("listEntry"))}</span><select data-pubfield="list_entry" data-pub="${h(p.id)}">
          <option value="">${h(t("listAuto"))}</option>${listOpts.map((e) => `<option value="${h(e.id)}" ${p.list_entry === e.id ? "selected" : ""}>${h(e.name)}</option>`).join("")}</select></label>` : ""}
        <p class="hint wide">${h(t("factsHint"))}</p>
      </div>` : ""}
    </article>`;
  }

  function summary() {
    const rows = new Map();
    for (const p of st.pubs) {
      const per = periodOf(p.facts.year, p.month, st.periodStart) || "?";
      const r = score(p);
      const row = rows.get(per) || { n: 0, points: 0, bonus: 0, unknown: 0 };
      row.n++;
      row.points += r.points?.value || 0;
      row.bonus += r.bonus?.value || 0;
      if ((r.points?.missing.length || 0) + (r.bonus?.missing.length || 0)) row.unknown++;
      rows.set(per, row);
    }
    const sorted = [...rows].sort((a, b) => b[0].localeCompare(a[0]));
    const manual = st.packs.bonus ? manualRules(shown("bonus")) : [];
    return `<section class="panel pad">
      <div class="toolbar"><h3 class="grow">${h(t("summaryTitle"))}</h3>
        <label class="field inline">${h(t("periodStart"))}
          <select data-pact="period">${[1, 7, 8, 9, 10].map((m) => `<option value="${m}" ${st.periodStart === m ? "selected" : ""}>${h(m === 1 ? t("periodCalendar") : t("periodFrom", { m }))}</option>`).join("")}</select></label>
        <button type="button" class="btn small" data-pact="export-csv" ${st.pubs.length ? "" : "disabled"}>${icon("download")}CSV</button>
        <button type="button" class="btn small" data-pact="backup">${icon("download")}${h(t("backup"))}</button>
        <button type="button" class="btn small" data-pact="restore">${icon("upload")}${h(t("restore"))}</button>
      </div>
      ${sorted.length ? `<table class="rules"><thead><tr><th>${h(t("period"))}</th><th>${h(t("pubCount"))}</th>
        ${st.packs.points ? `<th>${h(t("packPoints"))}</th>` : ""}${st.packs.bonus ? `<th>${h(t("packBonus"))}</th>` : ""}<th>${h(t("incomplete"))}</th></tr></thead><tbody>
        ${sorted.map(([per, r]) => `<tr><td>${h(per)}</td><td>${r.n}</td>${st.packs.points ? `<td>${h(money(r.points, st.packs.points.unit))}</td>` : ""}${st.packs.bonus ? `<td>${h(money(r.bonus, st.packs.bonus.unit))}</td>` : ""}<td>${r.unknown}</td></tr>`).join("")}
      </tbody></table>
      <p class="hint">${h(t("summaryNote"))}</p>` : `<p class="hint">${h(t("noPubs"))}</p>`}
      ${manual.map((m) => `<p class="hint">ℹ️ ${h(m.label)}: ${h(money(m.range.min, st.packs.bonus.unit))} – ${h(money(m.range.max, st.packs.bonus.unit))}. ${h(m.note || "")}</p>`).join("")}
    </section>`;
  }

  function render(el) {
    const L = st.lookup;
    el.innerHTML = `
      <p class="hint">${h(t("pubsIntro"))}</p>
      <div class="packs">${packPanel("points")}${packPanel("bonus")}${sjrPanel()}</div>
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
      ${summary()}
      <div class="pubs">${st.pubs.map(pubCard).join("")}</div>`;
  }

  // ---- events --------------------------------------------------------------------------
  function pickFile(accept) {
    return new Promise((resolve) => {
      const input = Object.assign(document.createElement("input"), { type: "file", accept });
      input.addEventListener("change", async () => resolve(input.files?.[0] ? await input.files[0].text() : null));
      input.click();
    });
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
      case "import": {
        const text = await pickFile("application/json,.json");
        if (!text) return true;
        try { if (setPack(role, JSON.parse(text))) toast(t("packLoaded")); } catch { toast(t("packNotJson")); }
        break;
      }
      case "export":
        download(`${st.packs[role].id || role}.json`, JSON.stringify(st.packs[role], null, 1), "application/json");
        return true;
      case "remove": st.packs[role] = null; save(); break;
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
        if (res.ok) addPub(fromCrossref((await res.json()).message));
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
          if (d.packs) for (const r of ["points", "bonus"]) if (d.packs[r] && !checkPack(d.packs[r]).length) st.packs[r] = d.packs[r];
          save();
          toast(t("planImported", { n: st.pubs.length }));
        } catch { toast(t("packNotJson")); }
        break;
      }
      default: return false;
    }
    ctx.renderView();
    return true;
  }

  function onChange(ev) {
    const el = ev.target;
    if (el.dataset.pact === "period") { st.periodStart = Number(el.value); store.setRaw(KEYS.period, String(st.periodStart)); ctx.renderView(); return true; }
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
      else if (k === "impact_factor" || k === "year") v = v === "" ? undefined : Number(v);
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
    return false;
  }

  function toCsv() {
    const head = ["title", "authors", "venue", "year", "doi", "kind", "points", "points_rule", "bonus", "bonus_rule", "missing_facts"];
    const rows = st.pubs.map((p) => {
      const r = score(p);
      return [p.title, (p.authors || []).join("; "), p.venue, p.facts.year || "", p.doi, p.facts.kind || "",
        r.points?.value ?? "", r.points?.rule?.label || "", r.bonus?.value ?? "", r.bonus?.rule?.label || "",
        [...new Set([...(r.points?.missing || []), ...(r.bonus?.missing || [])])].join(" ")];
    });
    return [head, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
  }

  return { render, onClick, onChange, onKey: (ev) => {
    if (ev.target.id === "pub-input" && ev.key === "Enter") { lookup(ev.target.value); return true; }
    return false;
  }, state: st, valueForYear };
}
