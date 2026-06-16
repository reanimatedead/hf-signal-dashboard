/* app.js — data.json を読み、タイル描画 + お金の流れアニメ初期化 */
(function () {
  const cv = document.getElementById("cv");
  if (cv && window.HFFlow) window.HFFlow.init(cv);

  function fmtVal(v, unit) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}:${x}`).join(" / ");
    return (unit ? `${v} ${unit}` : `${v}`);
  }

  fetch("data.json", { cache: "no-store" })
    .then(r => r.json())
    .then(data => {
      // SEEDタグ / 更新時刻
      const tag = document.getElementById("seedtag");
      if (tag) tag.textContent = data.meta && data.meta.reference_seed ? "SEED" : "LIVE";
      const up = document.getElementById("updated");
      if (up) up.textContent = "更新: " + (data.meta && data.meta.generated_at || "");

      // flow → アニメ
      if (window.HFFlow) window.HFFlow.setFlow(data.flow || null);
      const fm = document.getElementById("flowmeta");
      if (fm && data.flow) {
        const nl = data.flow.net_liquidity || {};
        fm.textContent = `局面:${data.flow.clock_phase} / 流動性:${nl.trend}(${nl.status || "ok"})`;
      }

      // タイル描画
      const root = document.getElementById("tiles");
      const tiles = data.tiles || {};
      Object.keys(tiles).forEach(id => {
        const t = tiles[id];
        const el = document.createElement("div");
        el.className = "tile " + (t.color || "neutral");
        el.setAttribute("data-tile", id);
        const ztxt = (t.status === "ok" || t.status === "stale") ? ` z=${(t.z ?? 0)}` : "";
        el.innerHTML =
          `<div class="top"><span class="label">${t.label || id}` +
          `<span class="st ${t.status}">${t.status}</span>` +
          `<span class="src">${t.source || ""}</span></span>` +
          `<span class="val">${fmtVal(t.value, t.unit)}</span></div>` +
          `<div class="meta">as_of:${t.as_of || "—"} / lag:${t.lag_days ?? "—"}日${ztxt}</div>` +
          `<div class="explain">${t.explain || ""}</div>` +
          `<div class="caveat">注意: ${t.caveat || ""}</div>`;
        root.appendChild(el);
      });
    })
    .catch(e => {
      const root = document.getElementById("tiles");
      if (root) root.innerHTML = `<div class="tile red"><div class="label">data.json 読込失敗</div>` +
        `<div class="caveat">${String(e)} — ローカルは <code>python3 -m http.server</code> で配信して開いてください。</div></div>`;
    });
})();
