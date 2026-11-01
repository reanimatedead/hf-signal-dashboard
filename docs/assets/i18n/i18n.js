/* assets/i18n/i18n.js — the one place that turns dictionary keys / data codes into text.
 * The dictionary itself is assets/i18n/dict.js (window.I18N = {ja:{...}, en:{...}}).
 *   T(key, vars)            dictionary lookup with {name} placeholders
 *   I18.code(field, value)  data.json code -> text (unknown legacy text is shown as-is)
 *   I18.fmtDate(iso, style) Intl date: "ym" (2026年11月 / Nov 2026), "m", "y", "ymd", "ymdhm"
 *   I18.fmtNum(n, d|opts)   Intl number with thousands separators (d = fixed decimals)
 *   I18.apply(root)         fills data-i18n / data-i18n-title / -aria / -placeholder / -html
 * Initial language: saved localStorage "hf_lang" -> navigator.language(s) ja* -> ja, else en.
 */
(function () {
  "use strict";
  const D = window.I18N || { ja: {}, en: {} };
  const LEG = window.I18N_LEGACY || {};
  const KEY = "hf_lang";
  const LOCALE = { ja: "ja-JP", en: "en-US" };

  function pick() {
    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { saved = null; }
    if (saved && D[saved]) return saved;
    const langs = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language || ""];
    return langs.some((l) => /^ja\b/i.test(String(l || ""))) ? "ja" : "en";
  }
  let lang = pick();
  const listeners = [];

  function has(key) { return Object.prototype.hasOwnProperty.call(D[lang] || {}, key); }
  function T(key, vars) {
    let s = has(key) ? D[lang][key] : (Object.prototype.hasOwnProperty.call(D.ja, key) ? D.ja[key] : key);
    if (vars) s = String(s).replace(/\{(\w+)\}/g, (m, k) => (vars[k] == null ? "" : String(vars[k])));
    return s;
  }
  function legacyCode(field, value) {
    const m = LEG[field] || LEG["*"];
    return (m && Object.prototype.hasOwnProperty.call(m, value)) ? m[value] : null;
  }
  // field: data.json field path as listed in codes.json (e.g. "markets[].chart_signal").
  function code(field, value, dflt) {
    if (value == null || value === "") return dflt == null ? "—" : dflt;
    const v = String(value);
    const k = "code." + field + "." + v;
    if (has(k)) return D[lang][k];
    const lc = legacyCode(field, v);
    if (lc != null && has("code." + field + "." + lc)) return D[lang]["code." + field + "." + lc];
    return v;   // unknown value: show the raw value (never hide data)
  }
  // normalise a value to its code (legacy text -> code) so logic can compare codes.
  function norm(field, value) {
    if (value == null) return value;
    const lc = legacyCode(field, String(value));
    return lc != null ? lc : value;
  }
  function locale() { return LOCALE[lang] || "en-US"; }

  function toDate(v) {
    if (v instanceof Date) return v;
    const s = String(v || "");
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(s + "T00:00:00Z");
    if (/^\d{4}-\d{2}$/.test(s)) return new Date(s + "-01T00:00:00Z");
    return new Date(s);
  }
  const DATE_OPTS = {
    ym: { year: "numeric", month: "short" },
    m: { month: "short" },
    y: { year: "numeric" },
    ymd: { year: "numeric", month: "short", day: "numeric" },
    ymdhm: { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false },
  };
  function fmtDate(v, style) {
    const d = toDate(v);
    if (!isFinite(d.getTime())) return v == null || v === "" ? "—" : String(v);
    const dateOnly = /^\d{4}-\d{2}(-\d{2})?$/.test(String(v || ""));
    const o = Object.assign({}, DATE_OPTS[style || "ymd"] || DATE_OPTS.ymd,
      { timeZone: dateOnly ? "UTC" : "Asia/Tokyo" });
    if (lang === "ja" && (style === "ym" || style === "m")) o.month = "long";   // 2026年11月 / 11月
    return new Intl.DateTimeFormat(locale(), o).format(d);
  }
  function fmtNum(n, opts) {
    if (n == null || n === "" || !isFinite(+n)) return "—";
    let o = opts;
    if (typeof opts === "number") o = { minimumFractionDigits: opts, maximumFractionDigits: opts };
    else if (!opts) o = { maximumFractionDigits: 2 };
    try { return new Intl.NumberFormat(locale(), o).format(+n); } catch (e) { return String(n); }
  }
  // signed fixed number: +1,234.50 / −0.20
  function fmtSigned(n, d) {
    if (n == null || !isFinite(+n)) return "—";
    return (+n > 0 ? "+" : "") + fmtNum(n, d);
  }

  function apply(root) {
    const r = root || document;
    document.documentElement.lang = lang;
    r.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = T(el.getAttribute("data-i18n")); });
    r.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = T(el.getAttribute("data-i18n-html")); });
    [["data-i18n-title", "title"], ["data-i18n-aria", "aria-label"], ["data-i18n-placeholder", "placeholder"]]
      .forEach(([a, target]) => r.querySelectorAll("[" + a + "]").forEach((el) => el.setAttribute(target, T(el.getAttribute(a)))));
    if (has("app.title")) document.title = T("app.title");
  }
  function setLang(l) {
    if (!D[l] || l === lang) return;
    lang = l;
    try { localStorage.setItem(KEY, l); } catch (e) { /* private mode */ }
    apply(document);
    listeners.forEach((f) => { try { f(lang); } catch (e) { console.error(e); } });
  }
  function onChange(f) { listeners.push(f); }

  window.T = T;
  window.I18 = { T, code, norm, has: (k) => has(k), fmtDate, fmtNum, fmtSigned, locale, apply, setLang, onChange,
    lang: () => lang, toggle: () => setLang(lang === "ja" ? "en" : "ja") };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => apply(document));
  else apply(document);
})();
