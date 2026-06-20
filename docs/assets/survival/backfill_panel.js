/* backfill_panel.js — SURVIVAL 内 収集進捗パネル (SPEC_BACKTEST §5.4).
 *
 * docs/data/backfill_progress_public.json (公開抜粋) を fetch.
 * 表示: 銘柄数 / 累計バー数 / カバー期間 (min..max) / 残容量 GB / store backend.
 * 公開ファイル不在 → 「履歴蓄積中」を表示.
 */
(function () {
  "use strict";

  const URL = "data/backfill_progress_public.json";

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      "\"": "&quot;", "'": "&#39;",
    }[c]));
  }
  function fmtNum(v) {
    if (v == null) return "—";
    return Number(v).toLocaleString();
  }

  function renderEmpty(reason) {
    const root = $("sv-backfill");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">データ厚盛り 収集進捗</div>' +
      '<div class="sv-empty">履歴蓄積中… (' + esc(reason || "no data") + ')</div>';
  }

  function renderProgress(body) {
    const root = $("sv-backfill");
    if (!root) return;
    const cov = body.coverage || {};
    const free = body.free_gb;
    const lowDisk = (typeof free === "number" && Number.isFinite(free) && free < 20);
    let html = '<div class="sv-card-hd">データ厚盛り 収集進捗</div>' +
      '<div class="sv-card-grid">' +
        '<div><b>symbols</b><span>' + esc(fmtNum(body.symbol_count)) + '</span></div>' +
        '<div><b>total bars</b><span>' + esc(fmtNum(body.total_bars)) + '</span></div>' +
        '<div><b>coverage from</b><span>' + esc(cov.first_ts || "—") + '</span></div>' +
        '<div><b>coverage to</b><span>' + esc(cov.last_ts || "—") + '</span></div>' +
        '<div><b>store</b><span>' + esc(body.store_backend || "—") + '</span></div>' +
        '<div><b>free disk</b><span>' + esc(free == null ? "—" : free + " GB") + '</span></div>' +
      '</div>';
    if (lowDisk) {
      html += '<div class="sv-notify-warn">⚠ 残容量 ' + esc(free) +
              ' GB &lt; 20 GB. 古い history を退避してください.</div>';
    }
    html += '<div class="sv-card-src">' + esc(body.note || "") + '</div>';
    root.innerHTML = html;
  }

  async function loadAndRender() {
    try {
      const r = await fetch(URL, { cache: "no-store" });
      if (!r.ok) { renderEmpty("HTTP " + r.status); return; }
      const body = await r.json();
      renderProgress(body);
    } catch (e) {
      renderEmpty(String(e));
    }
  }

  window.__survivalBackfillRefresh = loadAndRender;
})();
