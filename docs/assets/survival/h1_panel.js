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
    return Number(v).toFixed(d == null ? 3 : d);
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
           '" style="font-size:10px;padding:1px 6px">' + esc(k.toUpperCase()) + '</span>';
  }
  function sanityBadge(pass) {
    if (pass === true)  return '<span class="sv-rg-tag sv-rg-green"  style="font-size:10px;padding:1px 6px">PASS</span>';
    if (pass === false) return '<span class="sv-rg-tag sv-rg-red"    style="font-size:10px;padding:1px 6px">FAIL</span>';
    return                  '<span class="sv-rg-tag sv-rg-yellow" style="font-size:10px;padding:1px 6px">N/A</span>';
  }

  function renderEmpty(reason) {
    const root = $("sv-h1");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">H1: US 前日 → 日本オーバーナイト</div>' +
      '<div class="sv-empty">H1 未実行 (' + esc(reason || "no data") + ')</div>';
  }

  function renderH1(body) {
    const root = $("sv-h1");
    if (!root) return;
    let html = '<div class="sv-card-hd">H1 単独検証: US 前日リターン → 日本 オーバーナイト</div>';
    html += '<div class="sv-notify-info" style="margin-bottom:6px">' +
      '⚠ <b>単一仮説の素の予測力測定</b>. 想定トレード戦略のEVではない. ' +
      'not investment advice. Phase 2 (学習) 未実装.' +
      '</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">' +
      'jp=' + esc(body.jp_symbol) + ' / us=' + esc(body.us_symbol) +
      ' / source=' + esc(body.source_used || "—") +
      '</div>';

    (body.segments || []).forEach(function (seg) {
      html += '<div class="sv-card-hd" style="margin-top:10px;font-size:11px">' +
              esc(seg.name) + ' (' +
              (seg.from || "earliest") + ' .. ' + (seg.to || "now") +
              ', JP bars=' + seg.n_jp_bars + ', with feature=' + seg.n_with_feature +
              ')</div>';
      // sanity row
      html += '<table class="sv-table"><thead><tr><th>sanity</th><th>r</th><th>t</th><th>n</th><th>PASS?</th></tr></thead><tbody>';
      ["overnight","open_to_close","next_week"].forEach(function(k) {
        const s = seg.sanity && seg.sanity[k] || {};
        html += '<tr><td>' + esc(k) + '</td>' +
                '<td class="sv-num">' + esc(fmt(s.r, 3)) + '</td>' +
                '<td class="sv-num">' + esc(fmt(s.t, 2)) + '</td>' +
                '<td class="sv-num">' + esc(s.n) + '</td>' +
                '<td>' + sanityBadge(s.pass) + '</td></tr>';
      });
      html += '</tbody></table>';
      // labels metrics
      html += '<table class="sv-table" style="margin-top:6px"><thead><tr><th>label</th><th>n</th><th>hit</th><th>Brier</th><th>EV 95% CI</th><th>judge</th></tr></thead><tbody>';
      ["overnight","open_to_close","next_week"].forEach(function(k) {
        const m = seg.labels && seg.labels[k] || {};
        html += '<tr><td>' + esc(k) + '</td>' +
                '<td class="sv-num">' + esc(m.n) + '</td>' +
                '<td class="sv-num">' + esc(fmt(m.hit_rate, 3)) + '</td>' +
                '<td class="sv-num">' + esc(fmt(m.brier, 3)) + '</td>' +
                '<td class="sv-num">' + esc(ciStr(m.avg_net_pct_ci)) + '</td>' +
                '<td>' + judgeBadge(m.judge) + '</td></tr>';
      });
      html += '</tbody></table>';
    });
    html += '<div class="sv-card-src">' + esc(body.note || "") + '</div>';
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
