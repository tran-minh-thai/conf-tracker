// SPDX-License-Identifier: MIT
// In-page editor for a rule pack: the user starts from a sample (or their own file), changes labels,
// values, conditions, dates, the author share and the yearly quota, and saves it in this browser.
//
// A rule's condition is edited as alternatives of conjunctions, the same shape as the spreadsheet:
// the rule holds when every condition of at least one alternative holds. Any condition the engine
// accepts can be written this way except a "not" around a group; such a rule keeps its condition
// and only its text and value can be changed here.
import { FACTS, OPS_FOR, SHARE_SCHEMES, checkPack } from "./rules.js";
import { dnf } from "./packcsv.js";
import { escapeHtml as h } from "./core.js";
import { icon } from "./icons.js";

const OP_SYM = { eq: "=", ne: "≠", in: "∈", gte: "≥", gt: ">", lte: "≤", lt: "<", known: "?" };

const leafOf = (l) => {
  const op = Object.keys(l).find((k) => k !== "fact");
  return { fact: l.fact, op, value: l[op] };
};
const leafBack = (l) => ({ fact: l.fact, [l.op]: l.value });

/** A pack as an editable draft (a deep copy; the stored pack is untouched until save). */
export function toDraft(pack) {
  const p = JSON.parse(JSON.stringify(pack));
  p.rules = (p.rules || []).map((r) => {
    if (r.manual) return { ...r, _manual: true };
    try { return { ...r, _alts: dnf(r.when).map((conj) => conj.map(leafOf)) }; } catch { return { ...r, _fixed: true }; }
  });
  return p;
}

/**
 * The draft as a pack. Texts that changed lose their translations (a stale translation would show
 * the old text in the other language); conditions are rebuilt from the alternatives.
 */
export function fromDraft(draft, original) {
  const p = JSON.parse(JSON.stringify(draft));
  p.rules = p.rules.map((r) => {
    const { _alts, _manual, _fixed, ...rest } = r;
    if (_manual || _fixed) return rest;
    const alls = _alts.map((conj) => ({ all: conj.map(leafBack) }));
    return { ...rest, when: alls.length === 1 ? alls[0] : { any: alls } };
  });
  if (p.translations && original) {
    const origRules = new Map((original.rules || []).map((r) => [r.id, r]));
    for (const t of Object.values(p.translations)) {
      for (const k of ["title", "unit_label", "value_note"]) if (p[k] !== original[k]) delete t[k];
      if (t.source) for (const k of ["document", "warning"]) if (p.source?.[k] !== original.source?.[k]) delete t.source[k];
      if (t.rules) for (const r of p.rules) {
        const o = origRules.get(r.id);
        if (!o || o.label !== r.label) delete t.rules[r.id]?.label;
        if (!o || o.note !== r.note) delete t.rules[r.id]?.note;
        if (t.rules[r.id] && !Object.keys(t.rules[r.id]).length) delete t.rules[r.id];
      }
      if (t.rules) for (const id of Object.keys(t.rules)) if (!p.rules.some((r) => r.id === id)) delete t.rules[id];
    }
  }
  return p;
}

const defaultValue = (fact, op) => {
  const f = FACTS[fact];
  if (op === "known") return true;
  if (f.type === "bool") return true;
  if (f.type === "enum") return op === "in" ? [f.values[0]] : f.values[0];
  if (f.type === "number") return 0;
  return "";
};

/** Short human-readable text of a condition, with fact and value names in the page language. */
export function describeCondition(cond, t) {
  if (!cond) return "";
  const v = (fact, x) => (typeof x === "boolean" ? t(x ? "tri_yes" : "tri_no") : FACTS[fact]?.type === "enum" ? t(`v_${fact}_${x}`, {}, x) : String(x));
  const one = (c) => {
    if ("all" in c) return c.all.map(one).join(" · ");
    if ("any" in c) return `(${c.any.map(one).join(` ${t("edOr")} `)})`;
    if ("not" in c) return `${t("edNot")} (${one(c.not)})`;
    const l = leafOf(c);
    if (l.op === "known") return `${t(`f_${l.fact}`)} ${l.value ? t("edKnown") : t("edUnknown")}`;
    const val = Array.isArray(l.value) ? `{${l.value.map((x) => v(l.fact, x)).join(", ")}}` : v(l.fact, l.value);
    return `${t(`f_${l.fact}`)} ${OP_SYM[l.op]} ${val}`;
  };
  return one(cond);
}

/** Editor UI for one draft. `t` is the page translator. */
export function renderEditor(draft, role, t) {
  const facts = Object.keys(FACTS);
  const factSelect = (path, cur) => `<select data-ed="${path}.fact" aria-label="${h(t("edFact"))}">${facts.map((f) => `<option value="${f}" ${f === cur ? "selected" : ""}>${h(t(`f_${f}`))}</option>`).join("")}</select>`;
  const opSelect = (path, fact, cur) => {
    const ops = [...OPS_FOR[FACTS[fact].type], "known"];
    return `<select data-ed="${path}.op" aria-label="${h(t("edOp"))}">${ops.map((o) => `<option value="${o}" ${o === cur ? "selected" : ""}>${h(t(`edOp_${o}`))}</option>`).join("")}</select>`;
  };
  const valueInput = (path, l) => {
    const f = FACTS[l.fact];
    if (l.op === "known") return `<select data-ed="${path}.value" data-type="bool"><option value="yes" ${l.value ? "selected" : ""}>${h(t("edKnown"))}</option><option value="no" ${!l.value ? "selected" : ""}>${h(t("edUnknown"))}</option></select>`;
    if (f.type === "bool") return `<select data-ed="${path}.value" data-type="bool"><option value="yes" ${l.value ? "selected" : ""}>${h(t("tri_yes"))}</option><option value="no" ${!l.value ? "selected" : ""}>${h(t("tri_no"))}</option></select>`;
    if (f.type === "enum") {
      const sel = Array.isArray(l.value) ? l.value : [l.value];
      return `<select data-ed="${path}.value" data-type="${l.op === "in" ? "list" : "text"}" ${l.op === "in" ? `multiple size="${Math.min(f.values.length, 4)}"` : ""}>${f.values.map((x) => `<option value="${h(x)}" ${sel.includes(x) ? "selected" : ""}>${h(t(`v_${l.fact}_${x}`, {}, x))}</option>`).join("")}</select>`;
    }
    if (f.type === "number") return `<input type="number" step="any" class="num" data-ed="${path}.value" data-type="number" value="${h(l.value)}" />`;
    return `<input data-ed="${path}.value" data-type="text" value="${h(l.value)}" />`;
  };
  const ruleCond = (r, i) => {
    if (r._manual) return `<p class="hint">${h(t("edManual"))}</p>`;
    if (r._fixed) return `<p class="hint">${h(describeCondition(r.when, t))}<br>${h(t("edFixed"))}</p>`;
    return r._alts.map((conj, a) => `<div class="ed-alt">
        <div class="ed-alt-head">${a ? `<strong>${h(t("edOr"))}</strong> ` : ""}${h(t(r._alts.length > 1 ? "edAltN" : "edAlt", { n: a + 1 }))}
          ${r._alts.length > 1 ? `<button type="button" class="btn small" data-pact="ed-alt-del" data-rule="${i}" data-alt="${a}">${icon("x")}</button>` : ""}</div>
        ${conj.map((l, k) => {
          const path = `rules.${i}._alts.${a}.${k}`;
          return `<div class="ed-leaf">${factSelect(path, l.fact)}${opSelect(path, l.fact, l.op)}${valueInput(path, l)}
            <button type="button" class="btn small" data-pact="ed-leaf-del" data-rule="${i}" data-alt="${a}" data-leaf="${k}" aria-label="${h(t("packRemove"))}">${icon("x")}</button></div>`;
        }).join("")}
        <button type="button" class="btn small" data-pact="ed-leaf-add" data-rule="${i}" data-alt="${a}">${icon("plus")}${h(t("edAddCond"))}</button>
      </div>`).join("") + `<button type="button" class="btn small" data-pact="ed-alt-add" data-rule="${i}">${icon("plus")}${h(t("edAddAlt"))}</button>`;
  };
  const month = (d) => (d ? d.slice(0, 7) : "");
  const hoursPart = draft.kind === "hours" ? `<fieldset class="ed-box"><legend>${h(t("edHoursSettings"))}</legend>
      <label class="field inline">${h(t("edPeriodMonth"))}
        <select data-ed="period_start_month" data-type="number">${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((m) => `<option value="${m}" ${(draft.period_start_month || 1) === m ? "selected" : ""}>${h(m === 1 ? t("periodCalendar") : t("periodFrom", { m }))}</option>`).join("")}</select></label>
      <label class="field inline">${h(t("edShare"))}
        <select data-ed="share.scheme" data-type="text">${SHARE_SCHEMES.map((s) => `<option value="${s}" ${(draft.share?.scheme || "full") === s ? "selected" : ""}>${h(t(`share_${s}`))}</option>`).join("")}</select></label>
      ${draft.share?.scheme === "main_plus_equal" ? `<label class="field inline">${h(t("edShareMain"))}
        <input type="number" min="1" max="99" step="any" class="num" data-ed="share.main" data-type="percent" value="${h(Math.round((draft.share.main ?? 0.3) * 10000) / 100)}" /> %</label>` : ""}
      <div class="ed-quota"><strong>${h(t("edQuota"))}</strong>
        ${(draft.quota || []).map((q, i) => `<div class="ed-leaf">
          <label class="field inline">${h(t("edFrom"))}<input type="date" data-ed="quota.${i}.from" data-type="date" value="${h(q.from || "")}" /></label>
          <label class="field inline">${h(t("edHoursYear"))}<input type="number" min="0" step="any" class="num" data-ed="quota.${i}.hours" data-type="number" value="${h(q.hours)}" /></label>
          <button type="button" class="btn small" data-pact="ed-quota-del" data-i="${i}">${icon("x")}</button></div>`).join("")}
        <button type="button" class="btn small" data-pact="ed-quota-add">${icon("plus")}${h(t("edQuotaAdd"))}</button>
      </div></fieldset>` : "";
  return `<div class="editor">
    <p class="hint">${h(t("edIntro"))}</p>
    <label class="field wide"><span>${h(t("edTitle"))}</span><input data-ed="title" data-type="text" value="${h(draft.title)}" /></label>
    <label class="field wide"><span>${h(t("packSource"))}</span><input data-ed="source.document" data-type="text" value="${h(draft.source?.document || "")}" /></label>
    <label class="field wide"><span>${h(t("edWarning"))}</span><input data-ed="source.warning" data-type="text" value="${h(draft.source?.warning || "")}" /></label>
    ${hoursPart}
    ${draft.rules.map((r, i) => `<fieldset class="ed-box ed-rule"><legend>${h(t("edRule"))} ${h(r.id)}</legend>
      <div class="ed-row">
        <label class="field"><span>${h(t("edId"))}</span><input data-ed="rules.${i}.id" data-type="text" value="${h(r.id)}" class="num" /></label>
        <label class="field grow"><span>${h(t("ruleLabel"))}</span><input data-ed="rules.${i}.label" data-type="text" value="${h(r.label)}" /></label>
        ${r._manual ? `<label class="field"><span>${h(t("edMin"))}</span><input type="number" min="0" step="any" class="num" data-ed="rules.${i}.range.min" data-type="number" value="${h(r.range.min)}" /></label>
          <label class="field"><span>${h(t("edMax"))}</span><input type="number" min="0" step="any" class="num" data-ed="rules.${i}.range.max" data-type="number" value="${h(r.range.max)}" /></label>`
          : `<label class="field"><span>${h(t("ruleValue"))}</span><input type="number" min="0" step="any" class="num" data-ed="rules.${i}.value" data-type="number" value="${h(r.value)}" /></label>`}
      </div>
      <div class="ed-row">
        <label class="field"><span>${h(t("edValidFrom"))}</span><input type="month" data-ed="rules.${i}.valid.from" data-type="month" value="${h(month(r.valid?.from))}" /></label>
        <label class="field"><span>${h(t("edValidUntil"))}</span><input type="month" data-ed="rules.${i}.valid.until" data-type="month" value="${h(month(r.valid?.until))}" /></label>
        <label class="field grow"><span>${h(t("edNote"))}</span><input data-ed="rules.${i}.note" data-type="text" value="${h(r.note || "")}" /></label>
      </div>
      <div class="ed-cond"><span class="muted">${h(t("edWhen"))}</span>${ruleCond(r, i)}</div>
      <div class="actions left"><button type="button" class="btn small" data-pact="ed-rule-del" data-rule="${i}">${icon("x")}${h(t("edRuleDel"))}</button></div>
    </fieldset>`).join("")}
    <div class="actions left">
      <button type="button" class="btn small" data-pact="ed-rule-add">${icon("plus")}${h(t("edRuleAdd"))}</button>
    </div>
    <div class="actions left ed-save">
      <button type="button" class="btn primary" data-pact="ed-save" data-role="${role}">${h(t("edSave"))}</button>
      <button type="button" class="btn" data-pact="ed-cancel">${h(t("edCancel"))}</button>
    </div>
  </div>`;
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    const k = keys[i];
    if (o[k] == null) o[k] = {};
    o = o[k];
  }
  const last = keys.at(-1);
  if (value === undefined) delete o[last]; else o[last] = value;
}

/** Apply one changed input to the draft; returns true when the editor must be drawn again. */
export function editorChange(draft, el) {
  const path = el.dataset.ed;
  const type = el.dataset.type;
  let v = el.value;
  if (type === "number") v = v === "" ? undefined : Number(v);
  else if (type === "percent") v = v === "" ? undefined : Number(v) / 100;
  else if (type === "bool") v = v === "yes";
  else if (type === "list") v = [...el.selectedOptions].map((o) => o.value);
  else if (type === "month") v = v ? `${v}-01` : undefined;
  else if (type === "date") v = v || undefined;
  else if (type === "text") v = v.trim() === "" && /\.(note|warning)$/.test(path) ? undefined : v;
  // Changing a fact or operator resets the value to one that fits.
  const m = path.match(/^(rules\.\d+\._alts\.\d+\.\d+)\.(fact|op)$/);
  if (m) {
    const leaf = m[1].split(".").reduce((o, k) => o[k], draft);
    if (m[2] === "fact") { leaf.fact = v; leaf.op = OPS_FOR[FACTS[v].type][0]; } else leaf.op = v;
    leaf.value = defaultValue(leaf.fact, leaf.op);
    return true;
  }
  setPath(draft, path, v);
  const r = path.match(/^rules\.(\d+)\.valid\./);
  if (r) { const rule = draft.rules[Number(r[1])]; if (rule.valid && !rule.valid.from && !rule.valid.until) delete rule.valid; }
  if (path === "share.scheme") { if (v === "main_plus_equal" && draft.share.main == null) draft.share.main = 0.3; if (v !== "main_plus_equal") delete draft.share.main; return true; }
  return false;
}

/** Apply one editor button; returns true when handled. */
export function editorClick(draft, b) {
  const i = Number(b.dataset.rule), a = Number(b.dataset.alt);
  const rule = draft.rules[i];
  switch (b.dataset.pact) {
    case "ed-leaf-add": rule._alts[a].push({ fact: "kind", op: "eq", value: "journal" }); return true;
    case "ed-leaf-del": rule._alts[a].splice(Number(b.dataset.leaf), 1); return true;
    case "ed-alt-add": rule._alts.push([{ fact: "kind", op: "eq", value: "journal" }]); return true;
    case "ed-alt-del": rule._alts.splice(a, 1); return true;
    case "ed-rule-del": draft.rules.splice(i, 1); return true;
    case "ed-rule-add": {
      const ids = new Set(draft.rules.map((r) => r.id));
      let n = draft.rules.length + 1;
      while (ids.has(String(n))) n++;
      draft.rules.push({ id: String(n), label: "", value: 0, _alts: [[{ fact: "kind", op: "eq", value: "journal" }]] });
      return true;
    }
    case "ed-quota-add": (draft.quota ||= []).push({ hours: 0 }); return true;
    case "ed-quota-del": draft.quota.splice(Number(b.dataset.i), 1); return true;
    default: return false;
  }
}

/** Problems of the draft as a pack, plus editor-only checks (an alternative with no condition). */
export function draftProblems(draft) {
  const p = [];
  draft.rules.forEach((r) => {
    if (r._alts && (!r._alts.length || r._alts.some((c) => !c.length))) p.push(`rule ${r.id}: every alternative needs at least one condition`);
    if (r._alts?.some((c) => c.some((l) => Array.isArray(l.value) && !l.value.length))) p.push(`rule ${r.id}: a "one of" condition has no value chosen`);
  });
  if (p.length) return p;
  return checkPack(fromDraft(draft, null));
}
