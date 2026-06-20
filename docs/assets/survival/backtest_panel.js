/* backtest_panel.js — SURVIVAL 内 IS/OOS バックテストサマリ
 *
 * Phase 1.7 = smoke (random walk) を読む.
 * Phase 1.8 = live (data/local 実レート) も読む. body.mode が "live" のとき per_symbol
 *             銘柄別テーブル + 較正曲線 SVG + excluded リストを描画する.
 *
 * 「これは想定精度であり実トレード結果ではない / not investment advice」を最上部に明示。
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
  function ciStr(arr) {
    if (!Array.isArray(arr) || arr.length !== 2) return "—";
    return "[" + fmt(arr[0], 3) + ", " + fmt(arr[1], 3) + "]";
  }

  function renderEmpty(reason) {
    const root = $("sv-backtest");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">バックテスト (IS vs OOS)</div>' +
      '<div class="sv-empty">履歴蓄積中… (' + esc(reason || "no data") + ')</div>';
  }

  function badgeFor(judge) {
    const j = (judge || "").toLowerCase();
    let cls = "sv-rg-yellow", label = j || "—";
    if (j === "edge")          { cls = "sv-rg-green"; }
    else if (j === "no-edge")  { cls = "sv-rg-red"; }
    else if (j === "ok")       { cls = "sv-rg-green"; label = "ok"; }
    else if (j === "insufficient" || j === "undetermined") { cls = "sv-rg-yellow"; }
    else if (j === "inconclusive") { cls = "sv-rg-yellow"; }
    return '<span class="sv-rg-tag ' + cls +
           '" style="font-size:10px;padding:1px 6px">' + esc(label.toUpperCase()) + '</span>';
  }

  function renderTopTable(label, isM, oos, gap) {
    let html = '<table class="sv-table"><thead><tr>' +
      '<th>' + esc(label) + '</th><th>IS</th><th>OOS</th><th>gap</th>' +
      '</tr></thead><tbody>';
    function row(name, isV, oosV, gapV, isPct) {
      const f = isPct ? fmtPct : fmt;
      return '<tr><td>' + esc(name) + '</td>' +
             '<td class="sv-num">' + esc(f(isV, 3)) + '</td>' +
             '<td class="sv-num">' + esc(f(oosV, 3)) + '</td>' +
             '<td class="sv-num">' + esc(f(gapV, 3)) + '</td></tr>';
    }
    html += row("N (trades)", isM.n, oos.n, null);
    html += row("hit rate", isM.hit_rate, oos.hit_rate, gap.hit_rate);
    html += row("Brier", isM.brier, oos.brier, gap.brier);
    html += row("avg net %", isM.avg_net_pct, oos.avg_net_pct, gap.avg_net, true);
    html += row("max DD %", isM.max_dd_pct, oos.max_dd_pct, null, true);
    html += '<tr><td>judge</td><td>' + badgeFor(isM.judge) + '</td><td>' +
            badgeFor(oos.judge) + '</td><td>' +
            (oos.ev_ambiguous ? '<span class="sv-rg-tag sv-rg-yellow" style="font-size:10px">CI 0またぎ</span>' : '—') +
            '</td></tr>';
    html += '<tr><td>EV 95% CI</td><td class="sv-num">' + esc(ciStr(isM.avg_net_pct_ci)) + '</td>' +
            '<td class="sv-num">' + esc(ciStr(oos.avg_net_pct_ci)) + '</td><td>—</td></tr>';
    html += '</tbody></table>';
    return html;
  }

  function renderPerSymbol(perSymbol) {
    if (!Array.isArray(perSymbol) || !perSymbol.length) return "";
    let html = '<div class="sv-card-hd" style="margin-top:14px">銘柄別 (OOS)</div>' +
      '<table class="sv-table"><thead><tr>' +
      '<th>symbol</th><th>n_bars</th><th>folds</th><th>n_oos</th>' +
      '<th>OOS hit</th><th>OOS Brier</th><th>EV 95% CI</th><th>judge</th>' +
      '</tr></thead><tbody>';
    const sorted = [...perSymbol].sort((a, b) => {
      const ord = { edge: 0, inconclusive: 1, "no-edge": 2, insufficient: 3 };
      return (ord[a.judge] ?? 9) - (ord[b.judge] ?? 9);
    });
    sorted.forEach(s => {
      const oos = s.out_of_sample || {};
      html += '<tr>' +
        '<td>' + esc(s.symbol) + '</td>' +
        '<td class="sv-num">' + esc(s.n_bars) + '</td>' +
        '<td class="sv-num">' + esc(s.folds) + '</td>' +
        '<td class="sv-num">' + esc(s.n_oos_trades) + '</td>' +
        '<td class="sv-num">' + esc(fmt(oos.hit_rate, 3)) + '</td>' +
        '<td class="sv-num">' + esc(fmt(oos.brier, 3)) + '</td>' +
        '<td class="sv-num">' + esc(ciStr(oos.avg_net_pct_ci)) + '</td>' +
        '<td>' + badgeFor(s.judge) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  function renderExcluded(excluded) {
    if (!Array.isArray(excluded) || !excluded.length) return "";
    let html = '<div class="sv-card-src" style="margin-top:6px">' +
               '除外 (insufficient_data, 捏造禁止): ';
    html += excluded.map(e =>
      esc(e.symbol) + ' (n=' + esc(e.n_bars) + '/' + esc(e.min_required) + ')'
    ).join(", ");
    html += '</div>';
    return html;
  }

  function renderCalibrationSvg(calibration) {
    if (!Array.isArray(calibration) || !calibration.length) return "";
    // SVG: 200x140 polyline of (pred_mean, obs_rate) per bin with n weight as marker size.
    const W = 220, H = 140, P = 18;
    const xs = (p) => P + p * (W - 2 * P);
    const ys = (p) => H - P - p * (H - 2 * P);
    let pts = [];
    let markers = [];
    let totalN = calibration.reduce((s, b) => s + (b.n || 0), 0);
    calibration.forEach(b => {
      if (b.pred_mean == null || b.obs_rate == null) return;
      const x = xs(Math.max(0, Math.min(1, b.pred_mean)));
      const y = ys(Math.max(0, Math.min(1, b.obs_rate)));
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
      const r = Math.max(1.5, 3 + Math.sqrt((b.n || 0) / Math.max(1, totalN)) * 8);
      markers.push('<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) +
                   '" r="' + r.toFixed(1) + '" fill="rgba(0,232,162,0.65)"/>');
    });
    const diag =
      '<line x1="' + xs(0) + '" y1="' + ys(0) + '" x2="' + xs(1) + '" y2="' + ys(1) +
      '" stroke="rgba(120,120,120,0.5)" stroke-dasharray="3 3"/>';
    const line = pts.length >= 2
      ? '<polyline points="' + pts.join(" ") +
        '" fill="none" stroke="#00cc88" stroke-width="1.5"/>'
      : "";
    return '<div class="sv-card-hd" style="margin-top:14px">較正曲線 (OOS 全体)</div>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" ' +
      'style="width:100%;max-width:340px;background:var(--bg3);border:1px solid var(--border);' +
      'border-radius:4px">' +
      '<rect x="' + P + '" y="' + P + '" width="' + (W - 2 * P) + '" height="' + (H - 2 * P) +
      '" fill="none" stroke="rgba(120,120,120,0.3)"/>' +
      diag + line + markers.join("") +
      '<text x="' + xs(0) + '" y="' + (H - 4) + '" font-size="8" fill="#777">0</text>' +
      '<text x="' + xs(1) + '" y="' + (H - 4) + '" font-size="8" fill="#777" text-anchor="end">1</text>' +
      '<text x="3" y="' + ys(0) + '" font-size="8" fill="#777">0</text>' +
      '<text x="3" y="' + (ys(1) + 8) + '" font-size="8" fill="#777">1</text>' +
      '<text x="' + (W / 2) + '" y="' + (H - 3) + '" font-size="9" fill="#888" text-anchor="middle">predicted</text>' +
      '</svg>';
  }

  function renderLive(body) {
    const root = $("sv-backtest");
    if (!root) return;
    const ov = body.overall || {};
    const isM = ov.in_sample || {};
    const oos = ov.out_of_sample || {};
    const gap = ov.overfit_gap || {};

    let html = '<div class="sv-card-hd">バックテスト (実レート想定精度 / IS vs OOS)</div>' +
      '<div class="sv-notify-info" style="margin-bottom:6px">' +
      '⚠ これは <b>想定精度</b>であり実トレード結果ではありません. ' +
      'not investment advice / Phase 2 (学習) 未実装.' +
      '</div>';

    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">' +
      'n_symbols=' + esc(ov.n_symbols) + ' / n_excluded=' + esc(ov.n_excluded) +
      ' / fold mode=' + esc((body.fold_config && body.fold_config.mode) || "—") +
      ' / source=' + esc(body.source_used || "—") +
      '</div>';

    html += renderTopTable("全体", isM, oos, gap);
    html += renderCalibrationSvg(ov.calibration);
    html += renderPerSymbol(body.per_symbol);
    html += renderExcluded(body.excluded);
    html += '<div class="sv-card-src">' + esc(body.note || "") + '</div>';
    root.innerHTML = html;
  }

  function renderSmoke(body) {
    const root = $("sv-backtest");
    if (!root) return;
    const s = body.summary || {};
    const isM = s.in_sample || {};
    const oos = s.out_of_sample || {};
    const gap = s.overfit_gap || {};

    let html = '<div class="sv-card-hd">バックテスト (IS vs OOS) [smoke]</div>';
    html += renderTopTable("smoke", isM, oos, gap);
    if ((oos.judge || "") === "undetermined" || (gap.hit_rate || 0) > 0.05) {
      html += '<div class="sv-notify-info">⚐ overfit risk: IS と OOS の差が無視できません。' +
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
      if (body.mode === "live") renderLive(body);
      else renderSmoke(body);
    } catch (e) {
      renderEmpty(String(e));
    }
  }

  window.__survivalBacktestRefresh = loadAndRender;
})();
