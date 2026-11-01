/* h1_panel.js — SURVIVAL 内 H1 (US→日本オーバーナイト) 単独検証パネル.
 * SPEC_H1 §5. 公開抜粋 docs/data/h1_summary_public.json を fetch.
 * 3 ラベル × 2 セグメントの hit/Brier/EV CI 表 + judge 色分け + サニティチェック.
 */
(function () {
  "use strict";

  const URL = "data/h1_summary_public.json";

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      "\"": "&quot;", "'": "&#39;",
    }[c]));
  }
  function fmt(v, d) {
    if (v == null || !Number.isFinite(+v)) return "—";
    return I18.fmtNum(v, d == null ? 3 : d);
  }
  function ciStr(arr) {
    if (!Array.isArray(arr) || arr.length !== 2) return "—";
    return "[" + fmt(arr[0], 3) + ", " + fmt(arr[1], 3) + "]";
  }
  function judgeBadge(j) {
    const k = (j || "").toLowerCase();
    let cls = "sv-rg-yellow";
    if (k === "edge") cls = "sv-rg-green";
    else if (k === "no-edge") cls = "sv-rg-red";
    return '<span class="sv-rg-tag ' + cls +
           '" style="font-size:10px;padding:1px 6px">' + esc(I18.code("judge", k)) + '</span>';
  }
  function sanityBadge(pass) {
    if (pass === true)  return '<span class="sv-rg-tag sv-rg-green"  style="font-size:10px;padding:1px 6px">' + T("h1.pass") + '</span>';
    if (pass === false) return '<span class="sv-rg-tag sv-rg-red"    style="font-size:10px;padding:1px 6px">' + T("h1.fail") + '</span>';
    return                  '<span class="sv-rg-tag sv-rg-yellow" style="font-size:10px;padding:1px 6px">' + T("h1.na") + '</span>';
  }

  function renderEmpty(reason) {
    const root = $("sv-h1");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">' + T("h1.title_short") + '</div>' +
      '<div class="sv-empty">' + T("h1.not_run", { reason: esc(reason || T("common.no_data")) }) + '</div>';
  }

  function renderH1(body) {
    const root = $("sv-h1");
    if (!root) return;
    let html = '<div class="sv-card-hd">' + T("h1.title") + '</div>';
    html += '<div class="sv-notify-info" style="margin-bottom:6px">' + T("h1.disc") + '</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">' +
      T("h1.meta", { jp: esc(body.jp_symbol), us: esc(body.us_symbol), src: esc(body.source_used ? I18.code("source", body.source_used) : "—") }) +
      '</div>';

    (body.segments || []).forEach(function (seg) {
      html += '<div class="sv-card-hd" style="margin-top:10px;font-size:11px">' +
              esc(I18.code("h1_segment", seg.name)) + ' (' +
              T("h1.seg_meta", { from: seg.from ? esc(I18.fmtDate(seg.from, "ymd")) : T("h1.earliest"), to: seg.to ? esc(I18.fmtDate(seg.to, "ymd")) : T("h1.now"),
                bars: I18.fmtNum(seg.n_jp_bars, 0), feat: I18.fmtNum(seg.n_with_feature, 0) }) +
              ')</div>';
      // sanity row
      html += '<table class="sv-table"><thead><tr>' + ["sanity", "r", "t", "n", "pass"].map((k) => '<th>' + T("h1.th_" + k) + '</th>').join("") + '</tr></thead><tbody>';
      ["overnight","open_to_close","next_week"].forEach(function(k) {
        const s = seg.sanity && seg.sanity[k] || {};
        html += '<tr><td>' + esc(T("h1.label_" + k)) + '</td>' +
                '<td class="sv-num">' + esc(fmt(s.r, 3)) + '</td>' +
                '<td class="sv-num">' + esc(fmt(s.t, 2)) + '</td>' +
                '<td class="sv-num">' + esc(s.n) + '</td>' +
                '<td>' + sanityBadge(s.pass) + '</td></tr>';
      });
      html += '</tbody></table>';
      // labels metrics
      html += '<table class="sv-table" style="margin-top:6px"><thead><tr>' + ["label", "n", "hit", "brier", "ev_ci", "judge"].map((k) => '<th>' + T("h1.th_" + k) + '</th>').join("") + '</tr></thead><tbody>';
      ["overnight","open_to_close","next_week"].forEach(function(k) {
        const m = seg.labels && seg.labels[k] || {};
        html += '<tr><td>' + esc(T("h1.label_" + k)) + '</td>' +
                '<td class="sv-num">' + esc(m.n) + '</td>' +
                '<td class="sv-num">' + esc(fmt(m.hit_rate, 3)) + '</td>' +
                '<td class="sv-num">' + esc(fmt(m.brier, 3)) + '</td>' +
                '<td class="sv-num">' + esc(ciStr(m.avg_net_pct_ci)) + '</td>' +
                '<td>' + judgeBadge(m.judge) + '</td></tr>';
      });
      html += '</tbody></table>';
    });
    html += '<div class="sv-card-src">' + esc(body.note ? I18.code("h1_note", body.note) : "") + '</div>';
    root.innerHTML = html;
  }

  async function loadAndRender() {
    try {
      const r = await fetch(URL, { cache: "no-store" });
      if (!r.ok) { renderEmpty("HTTP " + r.status); return; }
      const body = await r.json();
      renderH1(body);
    } catch (e) { renderEmpty(String(e)); }
  }
  window.__survivalH1Refresh = loadAndRender;
})();
