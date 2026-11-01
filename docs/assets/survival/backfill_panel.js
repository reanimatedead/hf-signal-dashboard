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
    return I18.fmtNum(v, 0);
  }

  function renderEmpty(reason) {
    const root = $("sv-backfill");
    if (!root) return;
    root.innerHTML =
      '<div class="sv-card-hd">' + T("bf.title") + '</div>' +
      '<div class="sv-empty">' + T("bt.accumulating", { reason: esc(reason || T("common.no_data")) }) + '</div>';
  }

  function renderProgress(body) {
    const root = $("sv-backfill");
    if (!root) return;
    const cov = body.coverage || {};
    const free = body.free_gb;
    const lowDisk = (typeof free === "number" && Number.isFinite(free) && free < 20);
    const kv = (k, v) => '<div><b>' + T("bf." + k) + '</b><span>' + esc(v) + '</span></div>';
    let html = '<div class="sv-card-hd">' + T("bf.title") + '</div>' +
      '<div class="sv-card-grid">' +
        kv("symbols", fmtNum(body.symbol_count)) +
        kv("total_bars", fmtNum(body.total_bars)) +
        kv("from", cov.first_ts ? I18.fmtDate(cov.first_ts, "ymd") : "—") +
        kv("to", cov.last_ts ? I18.fmtDate(cov.last_ts, "ymd") : "—") +
        kv("store", body.store_backend || "—") +
        kv("free", free == null ? "—" : T("bf.gb", { v: I18.fmtNum(free, 1) })) +
      '</div>';
    if (lowDisk) {
      html += '<div class="sv-notify-warn">' + T("bf.low_disk", { v: esc(I18.fmtNum(free, 1)) }) + '</div>';
    }
    html += '<div class="sv-card-src">' + esc(body.note ? I18.code("backfill_note", body.note) : "") + '</div>';
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
