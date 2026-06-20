/* notify_panel.js — SURVIVAL 内 通知ログパネル (SPEC_NOTIFY §7).
 *
 * 公開安全な抜粋 (docs/data/notifications_public.jsonl) を取得して描画。
 * - チェーン断裂 (sha256(prev+payload) != curr_hash) を赤バナーで警告。
 * - 行は append-only。表示順は古→新 (タイムライン)。
 * - ファイルが無い場合は静かに非表示 (config 不在環境を壊さない)。
 */
(function () {
  "use strict";

  const URL = "data/notifications_public.jsonl";
  const GENESIS = "0".repeat(64);

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      "\"": "&quot;", "'": "&#39;",
    }[c]));
  }

  // ── sha256 (Web Crypto) ─────────────────────────────
  async function sha256Hex(text) {
    const buf = new TextEncoder().encode(text);
    const out = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(out))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  function canonicalJson(obj) {
    const keys = Object.keys(obj).filter((k) => k !== "prev_hash" && k !== "curr_hash").sort();
    const o = {};
    for (const k of keys) o[k] = obj[k];
    return JSON.stringify(o);
  }

  async function verifyRows(rows) {
    let prev = GENESIS;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.prev_hash !== prev) return { ok: false, brokenAt: i, reason: "prev_hash" };
      const expected = await sha256Hex(prev + canonicalJson(r));
      if (expected !== r.curr_hash) return { ok: false, brokenAt: i, reason: "curr_hash" };
      prev = r.curr_hash;
    }
    return { ok: true };
  }

  function fmtDt(s) {
    if (!s) return "—";
    return String(s).replace("T", " ").replace("Z", "");
  }

  function renderRows(rows, integrity) {
    const root = $("sv-notify");
    if (!root) return;
    let html = '<div class="sv-card-hd">通知ログ (改竄不能チェーン)</div>';
    if (!integrity.ok) {
      html +=
        '<div class="sv-notify-warn">⚠ chain integrity failed at index ' +
        esc(integrity.brokenAt) + ' (' + esc(integrity.reason) + '). ' +
        '<b>後出し改竄の疑い</b>: 通知の信頼性が損なわれています。</div>';
    }
    if (!rows.length) {
      html += '<div class="sv-empty">notifications not published yet.</div>';
      root.innerHTML = html;
      return;
    }
    // pair ENTRY → EXIT by event_id
    const exitByRef = {};
    rows.forEach((r) => {
      if (/^EXIT_/.test(r.kind || "")) exitByRef[r.entry_ref] = r;
    });

    html += '<table class="sv-table"><thead><tr>' +
      '<th>ts</th><th>kind</th><th>sym</th><th>side</th><th>edge</th>' +
      '<th>pattern</th><th>realized%</th>' +
      '</tr></thead><tbody>';
    rows.forEach((r) => {
      const isExit = /^EXIT_/.test(r.kind || "");
      const cls = isExit ? "sv-exit" : "sv-entry";
      const realized = r.realized_pct;
      let rp = "—";
      if (typeof realized === "number" && Number.isFinite(realized)) {
        rp = (realized >= 0 ? "+" : "") + realized.toFixed(2) + "%";
      }
      html +=
        '<tr class="' + cls + '">' +
          '<td>' + esc(fmtDt(r.ts_utc || r.bar_ts)) + '</td>' +
          '<td>' + esc(r.kind) + '</td>' +
          '<td>' + esc(r.symbol) + '</td>' +
          '<td>' + esc(r.side) + '</td>' +
          '<td class="sv-num">' + esc(r.edge_score == null ? "—" : r.edge_score) + '</td>' +
          '<td>' + esc((r.pattern && r.pattern.regime) || "—") + '/' +
                   esc((r.pattern && r.pattern.distortion) || "—") + '</td>' +
          '<td class="sv-num ' + (realized > 0 ? "sv-pos" : realized < 0 ? "sv-neg" : "") + '">' +
            esc(rp) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';

    // Unmatched ENTRY (no EXIT_*) summary
    const open = rows.filter((r) => r.kind === "ENTRY" && !exitByRef[r.event_id]);
    if (open.length) {
      html += '<div class="sv-notify-info">⚐ open positions (no EXIT recorded): ' +
              esc(open.length) + ' — ' +
              open.slice(0, 5).map((o) => esc(o.symbol)).join(", ") + '</div>';
    }
    // Fingerprint (最終 curr_hash の先頭 12 文字)
    const last = rows[rows.length - 1];
    if (last && last.curr_hash) {
      html += '<div class="sv-card-src">chain fingerprint: ' +
              esc(String(last.curr_hash).slice(0, 12)) + '… · n=' + rows.length +
              '</div>';
    }
    root.innerHTML = html;
  }

  async function loadAndRender() {
    const root = $("sv-notify");
    if (!root) return;
    let body;
    try {
      const res = await fetch(URL, { cache: "no-store" });
      if (!res.ok) {
        // file is optional; render an empty card
        renderRows([], { ok: true });
        return;
      }
      body = await res.text();
    } catch (e) {
      renderRows([], { ok: true });
      return;
    }
    const rows = body.split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => { try { return JSON.parse(l); } catch (e) { return null; } })
      .filter(Boolean);

    let integrity;
    try {
      integrity = await verifyRows(rows);
    } catch (e) {
      integrity = { ok: false, brokenAt: -1, reason: "crypto_unavailable" };
    }
    renderRows(rows, integrity);
  }

  window.__survivalNotifyRefresh = loadAndRender;
})();
