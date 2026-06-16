/* flow.js — お金の流れ Canvasアニメ (data/macro.json.flow 駆動)
 * BUILD_SPEC v4: 既存 docs/index.html に非破壊で増築。Canvas IDは独自 (#hf-macro-cv)。
 */
window.HFMacroFlow = (function () {
  let ctx, W, H, cb, basins, P = [], flow = null, raf = null;

  const LABELS = { stocks: "株", gold: "金", oil: "原油", cash: "現金" };
  const COLORS = { stocks: "#5ad07a", gold: "#e6c84a", oil: "#e0a93b", cash: "#8fa0b3" };
  const BW = 124, BH = 72;

  function init(canvas) {
    ctx = canvas.getContext("2d"); W = canvas.width; H = canvas.height;
    cb = { x: W / 2, y: 64, r: 26 };
    basins = [
      { key: "stocks", x: W * 0.74, y: H * 0.40 },
      { key: "oil",    x: W * 0.74, y: H * 0.74 },
      { key: "cash",   x: W * 0.26, y: H * 0.74 },
      { key: "gold",   x: W * 0.26, y: H * 0.40 },
    ].map(b => ({ ...b, name: LABELS[b.key], col: COLORS[b.key], level: 0.25 }));
    if (!flow) setFlow(null);
    spawn(70);
    if (!raf) loop();
  }

  function setFlow(f) {
    flow = Object.assign({
      net_liquidity: { value_usd_tn: 6.0, wow_change_tn: 0.0, trend: "expand", status: "missing" },
      clock_phase: "recovery", policy_rate_friction: 0.33,
      basin_tilt: { stocks: 0.4, gold: 0.25, oil: 0.2, cash: 0.15 },
      currents: { foreign_jp_flow_z: 0, cot_jpy_z: 0, risk_off: 0 }
    }, f || {});
  }

  function weights() {
    const w = Object.assign({}, flow.basin_tilt);
    const fr = Math.max(0, Math.min(1, flow.policy_rate_friction || 0));
    w.cash += fr * 0.5; w.stocks -= fr * 0.25; w.oil -= fr * 0.15;
    const c = flow.currents || {};
    w.stocks += (c.foreign_jp_flow_z || 0) * 0.15 + (c.cot_jpy_z || 0) * 0.05;
    Object.keys(w).forEach(k => w[k] = Math.max(0.02, w[k]));
    return w;
  }

  function pick() {
    const w = weights(); let s = 0; for (const k in w) s += w[k];
    let r = Math.random() * s, a = 0;
    for (const k in w) { a += w[k]; if (r <= a) return k; }
    return "cash";
  }
  const basinOf = k => basins.find(b => b.key === k);

  function spawn(n) {
    for (let i = 0; i < n; i++)
      P.push({ x: cb.x + (Math.random() - .5) * 20, y: cb.y + 10, vx: 0, vy: 0, target: pick(), alive: true });
  }

  function step() {
    if (!flow) setFlow(null);
    const expand = (flow.net_liquidity.trend === "expand");
    const mag = Math.min(1, Math.abs(flow.net_liquidity.wow_change_tn || 0) * 2 + 0.4);
    if (expand && P.length < 520) { if (Math.random() < mag) spawn(2); }
    else if (!expand) {
      if (Math.random() < mag) {
        const full = basins.slice().sort((a, b) => b.level - a.level)[0];
        if (full.level > .05) P.push({ x: full.x, y: full.y - BH / 2, vx: 0, vy: 0, target: "_cb", alive: true });
      }
    }
    const ro = Math.max(0, flow.currents.risk_off || 0);
    if (ro > 0 && Math.random() < ro) {
      const f = basins.find(b => b.key !== "cash" && b.level > .05);
      if (f) P.push({ x: f.x, y: f.y - BH / 2, vx: 0, vy: 0, target: "cash", alive: true });
    }
    for (const p of P) {
      let tx, ty;
      if (p.target === "_cb") { tx = cb.x; ty = cb.y; }
      else { const b = basinOf(p.target); tx = b.x + (Math.random() - .5) * BW * .7; ty = b.y + BH / 2 - 2; }
      const dx = tx - p.x, dy = ty - p.y, d = Math.hypot(dx, dy) + .01;
      p.vx = (p.vx + dx / d * .18) * .93; p.vy = (p.vy + dy / d * .18 + .05) * .93;
      p.x += p.vx; p.y += p.vy;
      if (d < 10) {
        if (p.target === "_cb") p.alive = false;
        else { const b = basinOf(p.target); p.alive = false; b.level = Math.min(1, b.level + .004); }
      }
    }
    basins.forEach(b => b.level = Math.max(0, b.level - .0016));
    for (let i = P.length - 1; i >= 0; i--) if (!P[i].alive) P.splice(i, 1);
  }

  function rr(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "rgba(90,143,224,0.10)"; ctx.lineWidth = 1;
    basins.forEach(b => { ctx.beginPath(); ctx.moveTo(cb.x, cb.y); ctx.lineTo(b.x, b.y); ctx.stroke(); });
    basins.forEach(b => {
      const x = b.x - BW / 2, y = b.y - BH / 2, wh = BH * b.level;
      ctx.fillStyle = "#0b131c"; rr(x, y, BW, BH, 8); ctx.fill();
      ctx.strokeStyle = "#21303f"; ctx.lineWidth = 1.2; ctx.stroke();
      ctx.save(); rr(x, y, BW, BH, 8); ctx.clip();
      const g = ctx.createLinearGradient(0, y + BH - wh, 0, y + BH);
      g.addColorStop(0, b.col + "55"); g.addColorStop(1, b.col + "cc");
      ctx.fillStyle = g; ctx.fillRect(x, y + BH - wh, BW, wh);
      ctx.strokeStyle = b.col + "aa"; ctx.beginPath();
      for (let i = 0; i <= BW; i += 6) {
        const yy = y + BH - wh + Math.sin(i * .12 + Date.now() * .004) * 1.6;
        i ? ctx.lineTo(x + i, yy) : ctx.moveTo(x + i, yy);
      }
      ctx.stroke(); ctx.restore();
      ctx.fillStyle = b.col; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(b.name, b.x, b.y - BH / 2 - 8);
      ctx.fillStyle = "#9fb0c2"; ctx.font = "10px sans-serif";
      ctx.fillText(Math.round(b.level * 100) + "%", b.x, b.y + BH / 2 + 13);
    });
    for (const p of P) {
      ctx.fillStyle = p.target === "_cb" ? "#39d0d8" : "rgba(120,170,235,.85)";
      ctx.beginPath(); ctx.arc(p.x, p.y, 1.8, 0, 7); ctx.fill();
    }
    const exp = flow.net_liquidity.trend === "expand";
    ctx.beginPath(); ctx.arc(cb.x, cb.y, cb.r, 0, 7);
    ctx.fillStyle = exp ? "#0c2a2c" : "#2a1010"; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = exp ? "#39d0d8" : "#e05a5a"; ctx.stroke();
    ctx.fillStyle = "#cfe7e9"; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("中央銀行", cb.x, cb.y - cb.r - 6);
    ctx.fillText(exp ? "供給↑" : "吸収↓", cb.x, cb.y + 4);
  }

  function loop() { step(); draw(); raf = requestAnimationFrame(loop); }

  return { init, setFlow };
})();
