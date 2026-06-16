/* macro.js — Macro タブ初期化 (data/macro.json 駆動)
 * 既存ダッシュボードに非破壊で増築。Window.HFMacro.activate() で起動。
 */
(function () {
  function fmtVal(v, unit) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object")
      return Object.entries(v).map(([k, x]) => `${k}:${x}`).join(" / ");
    return (unit ? `${v} ${unit}` : `${v}`);
  }

  let started = false;

  function start() {
    if (started) return;
    started = true;
    const cv = document.getElementById("hf-macro-cv");
    if (cv && window.HFMacroFlow) window.HFMacroFlow.init(cv);

    fetch("data/macro.json", { cache: "no-store" })
      .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(data => {
        const up = document.getElementById("hf-macro-updated");
        if (up) up.textContent =
          "macro updated: " + (data.meta && data.meta.generated_at || "") +
          "  /  pipeline:" + (data.meta && data.meta.pipeline_version || "") +
          "  /  fred_key:" + (data.meta && data.meta.inputs && data.meta.inputs.fred_key_set ? "set" : "unset");

        if (window.HFMacroFlow) window.HFMacroFlow.setFlow(data.flow || null);
        const fm = document.getElementById("hf-macro-flowmeta");
        if (fm && data.flow) {
          const nl = data.flow.net_liquidity || {};
          fm.textContent =
            "局面:" + (data.flow.clock_phase || "—") +
            " / 流動性:" + (nl.trend || "—") + "(" + (nl.status || "ok") + ")" +
            " / risk_off:" + ((data.flow.currents || {}).risk_off ?? 0);
        }

        const root = document.getElementById("hf-macro-tiles");
        if (!root) return;
        root.innerHTML = "";
        const tiles = data.tiles || {};
        Object.keys(tiles).forEach(id => {
          const t = tiles[id];
          const el = document.createElement("div");
          el.className = "hf-macro-tile " + (t.color || "neutral");
          el.setAttribute("data-tile", id);
          const ztxt = (t.status === "ok" || t.status === "stale")
            ? " z=" + (t.z ?? 0) : "";
          el.innerHTML =
            '<div class="hf-macro-top">' +
              '<span class="hf-macro-label">' + (t.label || id) +
                '<span class="hf-macro-st ' + (t.status || "missing") + '">' + (t.status || "missing") + '</span>' +
                '<span class="hf-macro-src">' + escapeHtml(t.source || "") + '</span>' +
              '</span>' +
              '<span class="hf-macro-val">' + escapeHtml(fmtVal(t.value, t.unit)) + '</span>' +
            '</div>' +
            '<div class="hf-macro-meta">as_of:' + (t.as_of || "—") + ' / lag:' +
              (t.lag_days ?? "—") + '日' + ztxt + '</div>' +
            '<div class="hf-macro-explain">' + escapeHtml(t.explain || "") + '</div>' +
            '<div class="hf-macro-caveat">注意: ' + escapeHtml(t.caveat || "") + '</div>';
          root.appendChild(el);
        });
      })
      .catch(err => {
        const root = document.getElementById("hf-macro-tiles");
        if (root) {
          root.innerHTML =
            '<div class="hf-macro-tile red"><div class="hf-macro-label">macro.json 読込失敗' +
            '<span class="hf-macro-st missing">missing</span></div>' +
            '<div class="hf-macro-caveat">' + escapeHtml(String(err)) +
            ' — ローカルは <code>cd docs &amp;&amp; python3 -m http.server</code> で配信してください。</div></div>';
        }
      });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
  }

  window.HFMacro = { start: start, activate: start };
})();
