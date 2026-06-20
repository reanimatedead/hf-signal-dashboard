/* backtest_panel.js — SURVIVAL 内 IS/OOS バックテストサマリ (SPEC_BACKTEST §6).
 *
 * docs/data/backtest_summary_public.json を fetch → 描画.
 * - 過学習を炙る: IS と OOS を並列表示し overfit_gap を出す.
 * - judge が undetermined / ev_ambiguous なら黄バッジ.
 * - 公開ファイル不在 → 「履歴蓄積中」表示で配線を落とさない.
 */
(function () {
  "use strict";

  const URL = "data/backtest_summary_public.json";

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
  function fmtPct(v, d) {
    if (v == null || !Number.isFinite(+v)) return "—";
    return Number(v).toFixed(d == null ? 2 : d) + "%";
  }

  function renderEmpty(reason) {
    const root = $("sv-backtest");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">バックテスト (IS vs OOS)</div>' +
      '<div class="sv-empty">履歴蓄積中… (' + esc(reason || "no data") + ')</div>';
  }

  function renderSummary(body) {
    const root = $("sv-backtest");
    if (!root) return;
    const s = body.summary || {};
    const isM = s.in_sample || {};
    const oos = s.out_of_sample || {};
    const gap = s.overfit_gap || {};

    function judgeBadge(m) {
      const j = m.judge || "—";
      const cls = j === "ok" ? "sv-rg-green" : "sv-rg-yellow";
      return '<span class="sv-rg-tag ' + cls + '" style="font-size:10px;padding:1px 6px">' +
             esc(j.toUpperCase()) + '</span>';
    }
    function ciStr(arr) {
      if (!Array.isArray(arr)) return "—";
      return "[" + fmt(arr[0], 3) + ", " + fmt(arr[1], 3) + "]";
    }

    let html = '<div class="sv-card-hd">バックテスト (IS vs OOS) ' + (body.mode === "smoke" ? "[smoke]" : "") + '</div>';
    html += '<table class="sv-table"><thead><tr>' +
      '<th>—</th><th>IS</th><th>OOS</th><th>gap</th>' +
      '</tr></thead><tbody>';
    function row(label, isVal, oosVal, gapVal, isPct) {
      const f = isPct ? fmtPct : fmt;
      return '<tr><td>' + esc(label) + '</td>' +
             '<td class="sv-num">' + esc(f(isVal, 3)) + '</td>' +
             '<td class="sv-num">' + esc(f(oosVal, 3)) + '</td>' +
             '<td class="sv-num">' + esc(f(gapVal, 3)) + '</td></tr>';
    }
    html += row("N (trades)", isM.n, oos.n, null);
    html += row("hit rate", isM.hit_rate, oos.hit_rate, gap.hit_rate);
    html += row("Brier", isM.brier, oos.brier, gap.brier);
    html += row("avg net %", isM.avg_net_pct, oos.avg_net_pct, gap.avg_net, true);
    html += row("max DD %", isM.max_dd_pct, oos.max_dd_pct, null, true);
    html += '<tr><td>judge</td><td>' + judgeBadge(isM) + '</td><td>' +
            judgeBadge(oos) + '</td><td>' +
            (oos.ev_ambiguous ? '<span class="sv-rg-tag sv-rg-yellow" style="font-size:10px">CI 0またぎ</span>' : '—') +
            '</td></tr>';
    html += '<tr><td>EV 95% CI</td><td class="sv-num">' + esc(ciStr(isM.avg_net_pct_ci)) + '</td>' +
            '<td class="sv-num">' + esc(ciStr(oos.avg_net_pct_ci)) + '</td><td>—</td></tr>';
    html += '</tbody></table>';
    if ((oos.judge || "") === "undetermined" || gap.hit_rate > 0.05) {
      html += '<div class="sv-notify-info">⚐ overfit risk: IS と OOS の差が無視できません。'+
              'OOS judge=' + esc(oos.judge || "—") + '</div>';
    }
    html += '<div class="sv-card-src">' + esc(body.note || "") + '</div>';
    root.innerHTML = html;
  }

  async function loadAndRender() {
    try {
      const r = await fetch(URL, { cache: "no-store" });
      if (!r.ok) { renderEmpty("HTTP " + r.status); return; }
      const body = await r.json();
      renderSummary(body);
    } catch (e) {
      renderEmpty(String(e));
    }
  }

  window.__survivalBacktestRefresh = loadAndRender;
})();
