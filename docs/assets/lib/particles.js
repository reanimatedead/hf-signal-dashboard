/* particles.js — Agent A/C 共有粒子エンジン (SPEC_MONEYFLOW §4.5)
 *
 * - 依存ゼロ。素 Canvas2D + rAF。three.js 等は使わない。
 * - 背景アニメ (`#bg-fx`) と お金の流れ (`#mf-cv-{region}`) の **両方** がこのモジュールを通る。
 * - 30fps 上限、prefers-reduced-motion、Page Visibility、devicePixelRatio<=2 をここで一括管理。
 *
 * 公開 API:
 *   HFParticles.createBackground(canvas, { mode })
 *     -> { setMode(mode), destroy() }
 *   HFParticles.createFlowField(canvas, { source, sinks, dynamics })
 *     -> { setDynamics(d), getArrivalPct(), destroy() }
 */
(function (global) {
  "use strict";

  // -----------------------------------------------------------
  // Common runtime: rAF throttler, reduced-motion, visibility.
  // -----------------------------------------------------------
  const FRAME_MS = 33; // ~30fps cap
  const DPR = Math.min(2, global.devicePixelRatio || 1);

  function prefersReducedMotion() {
    try {
      return global.matchMedia &&
        global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) { return false; }
  }

  function debounce(fn, ms) {
    let t = null;
    return function () {
      const a = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, a); }, ms);
    };
  }

  // Resize a canvas to its CSS box, capping DPR.
  function fitCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, rect.width | 0);
    const h = Math.max(1, rect.height | 0);
    canvas.width = w * DPR;
    canvas.height = h * DPR;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }

  // -----------------------------------------------------------
  // Background engine: clean / starfield / constellation.
  // -----------------------------------------------------------
  function createBackground(canvas, opts) {
    opts = opts || {};
    let mode = opts.mode || "clean";
    let geom = fitCanvas(canvas);
    let pts = [];
    let raf = null;
    let last = 0;
    let running = false;
    const reduced = prefersReducedMotion();

    function densityFor(mode) {
      if (mode === "clean") return 0;
      const area = geom.w * geom.h;
      const base = Math.floor(area / 25000);
      // Mobile (<768px) halve the density.
      const m = geom.w < 768 ? 0.45 : 1.0;
      if (mode === "starfield") return Math.max(0, Math.floor(base * m));
      if (mode === "constellation") return Math.max(0, Math.floor(base * 0.6 * m));
      return 0;
    }

    function colorFromCss(varName, fallback) {
      try {
        const v = getComputedStyle(document.body).getPropertyValue(varName).trim();
        return v || fallback;
      } catch (e) { return fallback; }
    }

    function rebuild() {
      const n = densityFor(mode);
      pts = new Array(n);
      for (let i = 0; i < n; i++) {
        pts[i] = {
          x: Math.random() * geom.w,
          y: Math.random() * geom.h,
          vx: (Math.random() - 0.5) * (mode === "starfield" ? 0.18 : 0.10),
          vy: (Math.random() - 0.5) * (mode === "starfield" ? 0.18 : 0.10),
          z: 0.5 + Math.random() * 1.0,
        };
      }
    }

    function step() {
      // Star drift (and constellation node drift).
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x += geom.w; else if (p.x > geom.w) p.x -= geom.w;
        if (p.y < 0) p.y += geom.h; else if (p.y > geom.h) p.y -= geom.h;
      }
    }

    function drawClean() {
      const ctx = geom.ctx;
      ctx.clearRect(0, 0, geom.w, geom.h);
      // single subtle wash; nothing animated.
      const accent = colorFromCss("--accent", "#00ffcc");
      ctx.globalAlpha = 0.03;
      ctx.fillStyle = accent;
      ctx.fillRect(0, 0, geom.w, geom.h);
      ctx.globalAlpha = 1.0;
    }

    function drawStarfield() {
      const ctx = geom.ctx;
      ctx.clearRect(0, 0, geom.w, geom.h);
      const accent = colorFromCss("--accent", "#00ffcc");
      const dim = colorFromCss("--text-dim", "#5a6a7e");
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        const r = 0.6 * p.z;
        ctx.fillStyle = i % 7 === 0 ? accent : dim;
        ctx.globalAlpha = 0.35 * p.z;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalAlpha = 1.0;
    }

    function drawConstellation() {
      const ctx = geom.ctx;
      ctx.clearRect(0, 0, geom.w, geom.h);
      const accent = colorFromCss("--accent", "#00ffcc");
      const dim = colorFromCss("--text-dim", "#5a6a7e");
      const D2 = 100 * 100;     // px^2 link threshold
      ctx.strokeStyle = accent;
      ctx.lineWidth = 0.5;
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < D2) {
            const alpha = 0.18 * (1 - d2 / D2);
            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 0.55;
      ctx.fillStyle = dim;
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.0, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalAlpha = 1.0;
    }

    function draw() {
      if (mode === "clean") return drawClean();
      if (mode === "starfield") return drawStarfield();
      if (mode === "constellation") return drawConstellation();
    }

    function tick(now) {
      raf = null;
      if (!running) return;
      if (now - last < FRAME_MS) {
        raf = requestAnimationFrame(tick);
        return;
      }
      last = now;
      step();
      draw();
      raf = requestAnimationFrame(tick);
    }

    function start() {
      if (mode === "clean" || reduced) {
        // Static one-frame paint; no loop.
        draw();
        running = false;
        return;
      }
      if (running) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(tick);
    }

    function stop() {
      running = false;
      if (raf) { cancelAnimationFrame(raf); raf = null; }
    }

    const onResize = debounce(function () {
      geom = fitCanvas(canvas);
      rebuild();
      draw();
    }, 150);

    function onVis() {
      if (document.hidden) stop();
      else start();
    }

    function setMode(m) {
      mode = m;
      rebuild();
      stop();
      start();
    }

    function destroy() {
      stop();
      global.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVis);
    }

    global.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVis);
    rebuild();
    start();

    return { setMode: setMode, destroy: destroy };
  }

  // -----------------------------------------------------------
  // Flow field engine: money-flow particles (3 regions).
  // source -> sinks[] with weight, fed by dynamics.{mag, expand, riskOff}.
  // -----------------------------------------------------------
  function createFlowField(canvas, opts) {
    opts = opts || {};
    let geom = fitCanvas(canvas);
    const reduced = prefersReducedMotion();
    let raf = null;
    let last = 0;
    let running = false;

    let dynamics = Object.assign({
      mag: 0.4,         // spawn rate magnitude (0..1)
      expand: true,     // true=expansion (CB->assets), false=contraction (assets->CB)
      riskOff: 0.0,     // 0..1; bias particles toward cash on >0
    }, opts.dynamics || {});

    const srcSpec = opts.source || { rx: 0.5, ry: 0.18 };
    const sinkSpec = (opts.sinks || []).map(function (s) { return Object.assign({}, s); });

    let cb, sinks, particles = [];
    let arrivals = {};

    function recompute() {
      cb = { x: geom.w * srcSpec.rx, y: geom.h * srcSpec.ry, r: Math.min(22, geom.w * 0.04) };
      sinks = sinkSpec.map(function (s) {
        return {
          key: s.key, label: s.label, color: s.color,
          x: geom.w * s.rx, y: geom.h * s.ry,
          w: Math.min(120, geom.w * 0.20),
          h: Math.min(56, geom.h * 0.18),
          weight: s.weight || 1,
        };
      });
      for (let i = 0; i < sinks.length; i++) {
        if (!(sinks[i].key in arrivals)) arrivals[sinks[i].key] = 0;
      }
    }

    function pick() {
      let s = 0;
      for (let i = 0; i < sinks.length; i++) {
        let w = sinks[i].weight;
        if (sinks[i].key === "cash") w += dynamics.riskOff * 1.2;
        s += Math.max(0.05, w);
      }
      let r = Math.random() * s;
      for (let i = 0; i < sinks.length; i++) {
        let w = sinks[i].weight;
        if (sinks[i].key === "cash") w += dynamics.riskOff * 1.2;
        r -= Math.max(0.05, w);
        if (r <= 0) return sinks[i];
      }
      return sinks[sinks.length - 1];
    }

    function spawn(n) {
      const cap = Math.floor((geom.w * geom.h) / 14000);
      for (let i = 0; i < n; i++) {
        if (particles.length >= cap) break;
        const target = pick();
        particles.push({
          x: cb.x + (Math.random() - 0.5) * 14,
          y: cb.y + 4,
          vx: 0, vy: 0,
          target: target,
          retreat: !dynamics.expand,
          alive: true,
        });
      }
    }

    function step() {
      const mag = Math.max(0.05, Math.min(1, dynamics.mag));
      if (Math.random() < mag) spawn(dynamics.expand ? 2 : 1);
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        let tx, ty;
        if (p.retreat) { tx = cb.x; ty = cb.y; }
        else {
          tx = p.target.x + (Math.random() - 0.5) * p.target.w * 0.6;
          ty = p.target.y + p.target.h * 0.4;
        }
        const dx = tx - p.x, dy = ty - p.y;
        const d = Math.hypot(dx, dy) + 0.001;
        p.vx = (p.vx + (dx / d) * 0.18) * 0.93;
        p.vy = (p.vy + (dy / d) * 0.18 + 0.04) * 0.93;
        p.x += p.vx; p.y += p.vy;
        if (d < 8) {
          p.alive = false;
          if (!p.retreat) arrivals[p.target.key] = (arrivals[p.target.key] || 0) + 1;
        }
      }
      for (let i = particles.length - 1; i >= 0; i--) {
        if (!particles[i].alive) particles.splice(i, 1);
      }
    }

    function rr(ctx, x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    function totalArrivals() {
      let t = 0;
      for (let i = 0; i < sinks.length; i++) t += arrivals[sinks[i].key] || 0;
      return t || 1;
    }

    function draw() {
      const ctx = geom.ctx;
      ctx.clearRect(0, 0, geom.w, geom.h);

      // Faint links from CB to sinks.
      ctx.strokeStyle = "rgba(120,170,235,0.10)";
      ctx.lineWidth = 1;
      for (let i = 0; i < sinks.length; i++) {
        ctx.beginPath();
        ctx.moveTo(cb.x, cb.y);
        ctx.lineTo(sinks[i].x, sinks[i].y);
        ctx.stroke();
      }

      // Sinks
      const tot = totalArrivals();
      for (let i = 0; i < sinks.length; i++) {
        const s = sinks[i];
        const x = s.x - s.w / 2, y = s.y - s.h / 2;
        rr(ctx, x, y, s.w, s.h, 6);
        ctx.fillStyle = "#0b131c";
        ctx.fill();
        ctx.strokeStyle = "#21303f";
        ctx.lineWidth = 1.2;
        ctx.stroke();
        // fill-level proportional to arrival share
        const share = (arrivals[s.key] || 0) / tot;
        ctx.save();
        rr(ctx, x, y, s.w, s.h, 6);
        ctx.clip();
        ctx.fillStyle = s.color + "aa";
        const hh = s.h * Math.min(1, share + 0.05);
        ctx.fillRect(x, y + s.h - hh, s.w, hh);
        ctx.restore();
        // label + arrival %
        ctx.fillStyle = s.color;
        ctx.font = "12px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(s.label, s.x, s.y - s.h / 2 - 6);
        ctx.fillStyle = "#cfe7e9";
        ctx.font = "10px system-ui, sans-serif";
        ctx.fillText(Math.round(share * 100) + "%", s.x, s.y + s.h / 2 + 12);
      }

      // Particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        ctx.fillStyle = p.retreat ? "#e05a5a" : "rgba(140,190,240,0.85)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.8, 0, 6.2832);
        ctx.fill();
      }

      // CB node
      ctx.beginPath();
      ctx.arc(cb.x, cb.y, cb.r, 0, 6.2832);
      ctx.fillStyle = dynamics.expand ? "#0c2a2c" : "#2a1010";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = dynamics.expand ? "#39d0d8" : "#e05a5a";
      ctx.stroke();
      ctx.fillStyle = "#cfe7e9";
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(opts.cbLabel || "CB", cb.x, cb.y - cb.r - 6);
      ctx.fillText(dynamics.expand ? (opts.expandLabel || "supply ↑")
                                   : (opts.contractLabel || "absorb ↓"),
                   cb.x, cb.y + 4);
    }

    function tick(now) {
      raf = null;
      if (!running) return;
      if (now - last < FRAME_MS) {
        raf = requestAnimationFrame(tick);
        return;
      }
      last = now;
      step();
      draw();
      raf = requestAnimationFrame(tick);
    }

    function start() {
      if (reduced) { draw(); running = false; return; }
      if (running) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(tick);
    }

    function stop() {
      running = false;
      if (raf) { cancelAnimationFrame(raf); raf = null; }
    }

    const onResize = debounce(function () {
      geom = fitCanvas(canvas);
      recompute();
      draw();
    }, 150);
    function onVis() { if (document.hidden) stop(); else start(); }
    global.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVis);

    recompute();
    start();

    function setDynamics(d) {
      dynamics = Object.assign(dynamics, d || {});
    }
    function getArrivalPct() {
      const tot = totalArrivals();
      const out = {};
      for (let i = 0; i < sinks.length; i++) {
        out[sinks[i].key] = Math.round(((arrivals[sinks[i].key] || 0) / tot) * 100);
      }
      return out;
    }
    function destroy() {
      stop();
      global.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVis);
    }

    return { setDynamics: setDynamics, getArrivalPct: getArrivalPct, destroy: destroy };
  }

  global.HFParticles = {
    createBackground: createBackground,
    createFlowField: createFlowField,
    fitCanvas: fitCanvas,
    DPR: DPR,
  };
})(window);
