/* assets/signal/signal_ui.js — 株式タブのチャート判定・検証・詳細チャート（DATA_CONTRACT §21）。
 *
 * - 判定の列（chart_signal）と、その横に必ず検証結果（verify.json: 20営業日後の中央値・上昇割合・件数 vs 基準）
 * - 売り系には「空売りの根拠なし。新しく買わない・利益を確定する目安」
 * - 日経225 の 理論株価・割安度・総合判定 は「Mac mini のローカル版のみ」（公開版では値を持たない）
 * - Nasdaq 100 タブの上に「米国の買い判定一覧」（Dow/NDX/S&P の和集合）
 * - 「検証」タブ（verify.json）、「根拠が弱まっています」バナー、上部の「データが○時間前のまま」
 * - 詳細チャートの描画関数は drawPriceCciChart の 1 つだけ（FX・株・指数・評価系列すべて）。
 *   上段: 終値・BB48/BB288 ±2σ/±3σ・▲買い/▼売り・価格の y 軸・日付の x 軸
 *   下段: 「CCI (48 / 288)」・±100・±200・0 の線・日付の x 軸
 * 文言はすべて assets/i18n/dict.js（T / I18.code）。data.json の判定はコード（buy_strong 等）。
 * 計算はしない（値は data.json / charts/{tab}.json / verify.json を読むだけ。FX 等の系列が無い
 * ときだけ、同じ OHLC から BB/CCI を描画用に組む）。
 */
(function () {
  "use strict";
  const BUY = ["buy_strong", "buy", "buy_long_oversold"];
  const SELL = ["sell", "sell_strong"];
  const US_TABS = ["dow30", "nasdaq100", "sp500"];
  const EQ_TABS = ["nikkei225"].concat(US_TABS);
  const C_BLUE = "#3b82f6", C_ORANGE = "#f97316";
  const S = { verify: null, state: "loading" };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const pct = (v, d = 1) => (num(v) == null ? "—" : I18.fmtSigned(v, d) + "%");
  const sig = (v) => I18.norm("chart_signal", v);                  // 旧形式（和文）→ コード
  const sigText = (c) => I18.code("chart_signal", c);
  // verify.json のキーがコードでも旧形式（和文）でも引けるように
  function byCode(obj, code, prefix) {
    if (!obj) return undefined;
    const p = prefix || "";
    if (Object.prototype.hasOwnProperty.call(obj, p + code)) return obj[p + code];
    for (const k of Object.keys(obj)) if (k.startsWith(p) && sig(k.slice(p.length)) === code) return obj[k];
    return undefined;
  }

  // ── CSS（index.html を太らせないためここで注入） ──
  const css = `
  #stale-banner{display:none;padding:8px 16px;background:rgba(229,72,77,.14);color:#e5484d;border-bottom:1px solid #e5484d;font-size:13px;font-weight:700;text-align:center;position:relative;z-index:5}
  #weak-banner{display:none;padding:6px 16px 0}
  #weak-banner .wb{display:inline-block;padding:5px 12px;border-radius:4px;font-size:12px;background:rgba(229,162,61,.14);color:#e5a23d;border:1px solid #e5a23d}
  .js-cell{display:flex;flex-direction:column;gap:2px;align-items:flex-start;line-height:1.25}
  .js-lab{font-weight:700;font-size:12px;padding:1px 6px;border-radius:3px;white-space:nowrap}
  .js-buy{color:#16a34a;background:rgba(22,163,74,.12)} .js-sbuy{color:#fff;background:#16a34a}
  .js-lo{color:#0d9488;background:rgba(13,148,136,.13)} .js-sell{color:#dc2626;background:rgba(220,38,38,.10)}
  .js-ssell{color:#fff;background:#dc2626} .js-wait{color:var(--text-dim);background:transparent;border:1px solid var(--border)}
  .js-vs{font-size:10px;color:var(--text-dim);white-space:normal}
  .js-vs b{color:var(--text)} .js-note{font-size:10px;color:#dc2626}
  .login-only{font-size:10px;color:var(--text-faint);border:1px dashed var(--border);padding:1px 5px;border-radius:3px;white-space:nowrap}
  #us-buy-list{display:none;padding:8px 16px 4px;overflow-x:auto}
  #us-buy-list h3{font-size:13px;margin:4px 0 6px;color:var(--text)}
  #us-buy-list table{width:100%;border-collapse:collapse;font-size:12px}
  #us-buy-list th,#us-buy-list td{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
  #us-buy-list .ub-empty{color:var(--text-faint);font-size:12px;padding:6px 0}
  #verify-pane{display:none;padding:12px 16px;overflow-x:auto}
  #verify-pane h2{font-size:15px;margin:4px 0 8px} #verify-pane h3{font-size:13px;margin:14px 0 6px}
  #verify-pane table{border-collapse:collapse;font-size:12px;min-width:560px}
  #verify-pane th,#verify-pane td{padding:4px 8px;border-bottom:1px solid var(--border);text-align:right}
  #verify-pane th:first-child,#verify-pane td:first-child{text-align:left}
  #verify-pane .vf-meta{font-size:12px;color:var(--text-dim);line-height:1.6}
  #verify-pane .vf-weak{color:#e5a23d;font-weight:700}
  .dt-chart:has(.sg-chart){max-width:min(1100px,100%)}
  .sg-chart{background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:4px;width:min(1100px,calc(100vw - 48px));box-sizing:border-box}
  tr.detail-row > td{white-space:normal}
  .sg-chart .dt-cap{white-space:normal}
  .sg-chart svg{width:100%;height:auto;display:block}
  .sg-chart svg text{font-family:inherit}
  .sg-leg{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:var(--text-dim);margin:4px 2px}
  .sg-leg i{display:inline-block;width:18px;height:0;border-top:2px solid;vertical-align:middle;margin-right:4px}
  .sg-leg i.dot{border-top-style:dotted}
  `;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  // ── verify.json ──
  async function loadVerify() {
    try {
      const r = await fetch("verify.json?t=" + Date.now(), { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      S.verify = await r.json(); S.state = "ok";
    } catch (e) { S.verify = null; S.state = "error"; }
    if (typeof window.__sigRerender === "function") window.__sigRerender();   // index.html が今のタブを再描画
  }
  function mkt(tab) { return tab === "nikkei225" ? "nikkei225" : "us"; }
  function statsFor(tab, code, kind = "chart") {
    const m = S.verify && S.verify.markets && S.verify.markets[mkt(tab)];
    if (!m || !m.full) return null;
    return { sig: byCode(m.full[kind], code) || null, base: m.full.base || null };
  }
  function vsText(tab, code) {
    if (S.state === "loading") return T("vf.vs_loading");
    if (S.state !== "ok") return T("vf.vs_unreadable");
    const st = statsFor(tab, code);
    if (!st || !st.base) return T("vf.vs_none");
    const b = st.base;
    const baseT = T("vf.vs_base", { median: pct(b.median), up: b.up_pct == null ? "—" : I18.fmtNum(b.up_pct, 0) + "%" });
    if (!code || code === "neutral" || !st.sig) return T("vf.vs_base_only", { base: baseT });
    const s = st.sig;
    if (!s.n) return T("vf.vs_zero", { base: baseT });
    return T("vf.vs_stats", { median: pct(s.median), up: I18.fmtNum(s.up_pct, 0), n: I18.fmtNum(s.n, 0), base: baseT });
  }
  function labCls(c) {
    return ({ buy_strong: "js-sbuy", buy: "js-buy", buy_long_oversold: "js-lo", sell_strong: "js-ssell", sell: "js-sell" })[c] || "js-wait";
  }
  function judgeCell(r, tab) {
    const c = sig(r.chart_signal);
    if (!c) return `<div class="js-cell"><span class="js-lab js-wait">${T("sig.none")}</span><span class="js-vs">${esc(r.chart_signal_note ? I18.code("chart_signal_note", r.chart_signal_note) : T("sig.short_bars"))}</span></div>`;
    const note = SELL.includes(c) ? `<span class="js-note">${T("code.sell_note.sell_note")}</span>` : "";
    return `<div class="js-cell"><span class="js-lab ${labCls(c)}">${esc(sigText(c))}</span><span class="js-vs">${vsText(tab, c)}</span>${note}</div>`;
  }

  // ── 列（l は辞書キー） ──
  const C_SIG = [
    { k: "chart_signal_code", l: "col.judge_verify", a: "left", w: 300 },
  ];
  const C_IND = [
    { k: "cci288", l: "col.cci288", a: "right", w: 66 },
    { k: "cci48", l: "col.cci48", a: "right", w: 62 },
    { k: "bb48_z", l: "col.bb48_z", a: "right", w: 62 },
    { k: "bb288_z", l: "col.bb288_z", a: "right", w: 66 },
  ];
  const C_US = [
    { k: "magic_rank", l: "col.magic_rank", a: "right", w: 90 },
    { k: "f_score", l: "col.f_score", a: "center", w: 52 },
  ];
  const C_JP = [
    { k: "__theory_price", l: "col.theory_price", a: "center", w: 92 },
    { k: "__value_gap", l: "col.value_gap", a: "center", w: 92 },
    { k: "__overall", l: "col.overall", a: "center", w: 92 },
  ];
  function cols(tab, base) {
    if (!EQ_TABS.includes(tab)) return base;
    const head = base.slice(0, 2), rest = base.slice(2);   // Signal / Score はそのまま先頭
    return head.concat(C_SIG, rest, C_IND, tab === "nikkei225" ? C_JP : C_US);
  }
  const DASH = `<span style="color:var(--text-faint)">—</span>`;
  function cell(c, r, tab) {
    switch (c.k) {
      case "chart_signal_code": return judgeCell(r, tab);
      case "cci288": case "cci48": {
        const v = num(r[c.k]); if (v == null) return DASH;
        const co = v >= 100 ? "var(--green)" : v <= -100 ? "var(--red)" : "var(--text-dim)";
        return `<span style="color:${co}">${I18.fmtSigned(v, 0)}</span>`;
      }
      case "bb48_z": case "bb288_z": {
        const v = num(r[c.k]); if (v == null) return DASH;
        const co = v <= -2 ? "var(--green)" : v >= 2 ? "var(--red)" : "var(--text-dim)";
        return `<span style="color:${co}">${I18.fmtSigned(v, 2)}σ</span>`;
      }
      case "magic_rank": return num(r.magic_rank) == null ? DASH : T("col.rank_n", { n: I18.fmtNum(r.magic_rank, 0) });
      case "f_score": return num(r.f_score) == null ? DASH : `${r.f_score}/${r.f_max}`;
      case "__theory_price": case "__value_gap": case "__overall": return `<span class="login-only">${T("col.login_only")}</span>`;
    }
    return null;
  }

  // ── 米国の買い判定一覧（Nasdaq 100 タブの上） ──
  function renderUsBuyList(tab, DATA) {
    const el = document.getElementById("us-buy-list"); if (!el) return;
    if (tab !== "nasdaq100") { el.style.display = "none"; return; }
    const seen = {}, rows = [];
    US_TABS.forEach((t) => ((DATA.markets || {})[t] || []).forEach((r) => {
      if (!r || String(r.symbol || "").startsWith("^") || !BUY.includes(sig(r.chart_signal))) return;
      if (!seen[r.symbol]) { seen[r.symbol] = { r, idx: [] }; rows.push(seen[r.symbol]); }
      seen[r.symbol].idx.push(T("ub.idx_" + t));
    }));
    const order = { buy_strong: 0, buy: 1, buy_long_oversold: 2 };
    rows.sort((a, b) => (order[sig(a.r.chart_signal)] - order[sig(b.r.chart_signal)]) || ((a.r.bb48_z ?? 0) - (b.r.bb48_z ?? 0)));
    el.style.display = "block";
    const body = rows.map(({ r, idx }) => `<tr><td>${judgeCell(r, "us")}</td><td><b>${esc(r.symbol)}</b></td><td>${esc(r.name || "")}</td>`
      + `<td>${esc(idx.join(T("common.sep_list")))}</td><td style="text-align:right">${num(r.price) == null ? "—" : I18.fmtNum(r.price, 2)}</td>`
      + `<td style="text-align:right">${cell({ k: "cci288" }, r)}</td><td style="text-align:right">${cell({ k: "bb48_z" }, r)}</td>`
      + `<td style="text-align:right">${cell({ k: "magic_rank" }, r)}</td><td style="text-align:center">${cell({ k: "f_score" }, r)}</td></tr>`).join("");
    const th = ["ub.th_judge", "col.symbol", "col.name", "ub.th_index", "col.price", "col.cci288", "col.bb48_z", "ub.th_magic", "col.f_score"]
      .map((k) => `<th>${T(k)}</th>`).join("");
    el.innerHTML = `<h3>${T("ub.title", { n: I18.fmtNum(rows.length, 0) })}</h3>`
      + (rows.length ? `<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`
        : `<div class="ub-empty">${T("ub.empty")}</div>`);
  }

  // ── バナー ──
  function renderStaleBanner(DATA) {
    const el = document.getElementById("stale-banner"); if (!el || !DATA || !DATA.meta) return;
    const t = Date.parse(DATA.meta.updated_at || "");
    const lim = num(DATA.meta.stale_hours) || 48;          // tools/gate_thresholds.STALE_HOURS と同じ値
    if (!isFinite(t)) { el.style.display = "block"; el.textContent = T("banner.stale_unreadable"); return; }
    const h = (Date.now() - t) / 36e5;
    if (h <= lim) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.textContent = T("banner.stale", { h: I18.fmtNum(Math.floor(h), 0), lim: I18.fmtNum(lim, 0),
      at: DATA.meta.updated_at ? I18.fmtDate(DATA.meta.updated_at, "ymdhm") : (DATA.meta.updated_at_str || "—") });
  }
  function weakItem(x) {
    // "<market>:<chart|composite>:<code>"（旧形式 "<market>: <label>" も読む）
    const p = String(x || "").split(":").map((v) => v.trim());
    if (p.length < 2) return String(x || "");
    const kind = p.length >= 3 ? p[1] : "chart", c = p[p.length - 1];
    const label = kind === "composite" ? I18.code("signal", c) : sigText(sig(c));
    return T("vf.weak_item", { market: I18.code("verify_market", I18.norm("verify_market", p[0])), signal: label });
  }
  function renderWeakBanner(t) {
    const el = document.getElementById("weak-banner"); if (!el) return;
    const v = S.verify;
    if (!v || v.weakened !== true || !(EQ_TABS.includes(t) || t === "verify")) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.innerHTML = `<span class="wb">${T("banner.weak", { items: esc((v.weakened_items || []).map(weakItem).join(T("common.sep_list"))) })}</span>`;
  }

  // ── 検証タブ ──
  function vrow(name, s, base, mark) {
    const nm = esc(name) + (mark || "");
    if (!s) return `<tr><td>${nm}</td><td colspan="5" style="text-align:left;color:var(--text-faint)">—</td></tr>`;
    const diff = num(s.median) != null && base && num(base.median) != null ? s.median - base.median : null;
    return `<tr><td>${nm}</td><td>${I18.fmtNum(s.n, 0)}</td><td>${pct(s.median, 2)}</td><td>${pct(s.mean, 2)}</td><td>${s.up_pct == null ? "—" : I18.fmtNum(s.up_pct, 0) + "%"}</td>`
      + `<td>${diff == null ? "—" : T("vf.pt", { v: I18.fmtSigned(diff, 2) })}</td></tr>`;
  }
  function vtable(part, weak) {
    if (!part) return "<p>—</p>";
    const b = part.base;
    const head = "<tr>" + ["vf.th_judge", "vf.th_n", "vf.th_median", "vf.th_mean", "vf.th_up", "vf.th_diff"].map((k) => `<th>${T(k)}</th>`).join("") + "</tr>";
    const w = (code, prefix) => (weak && byCode(weak, code, prefix) === true ? ` <span class="vf-weak">${T("vf.weak_mark")}</span>` : "");
    const chart = BUY.concat(SELL).map((c) => vrow(sigText(c) + (SELL.includes(c) ? T("vf.sell_mark") : ""), byCode(part.chart || {}, c), b, w(c, "chart:"))).join("");
    const comp = ["strong_buy", "buy", "hold", "watch", "avoid"].map((c) => {
      const legacy = c.toUpperCase().replace(/_/g, " ");
      const comp = part.composite || {};
      const s = comp[c] || comp[legacy];
      if (!s) return "";
      const wk = weak && (weak["composite:" + c] === true || weak["composite:" + legacy] === true) ? ` <span class="vf-weak">${T("vf.weak_mark")}</span>` : "";
      return vrow(T("vf.existing", { s: I18.code("signal", c) }), s, b, wk);
    }).join("");
    return `<table><thead>${head}</thead><tbody>${vrow(T("vf.base_row"), b, b)}${chart}${comp}</tbody></table>`;
  }
  function renderVerify() {
    const p = document.getElementById("verify-pane"); if (!p) return;
    const v = S.verify;
    if (S.state === "loading") { p.innerHTML = `<p>${T("vf.loading")}</p>`; return; }
    if (!v) { p.innerHTML = `<h2>${T("tab.verify")}</h2><p>${T("vf.unreadable")}</p>`; return; }
    const m = v.method || {};
    const gen = String(v.generated_at || "");
    let h = `<h2>${T("vf.title", { h: I18.fmtNum(m.horizon_days || 20, 0) })}</h2>
      <div class="vf-meta">${T("vf.meta", {
        asof: esc(v.as_of ? I18.fmtDate(v.as_of, "ymd") : "—"), gen: esc(gen ? I18.fmtDate(gen, "ymdhm") : "—"),
        h: I18.fmtNum(m.horizon_days || 20, 0), gap: I18.fmtNum(m.gap_days || 20, 0), base: esc(m.base ? I18.code("verify_method", m.base) : ""),
        warm: I18.fmtNum(m.warmup_bars || 288, 0), src: esc(m.price_source ? I18.code("verify_method", m.price_source) : ""),
        sell: T("code.sell_note.sell_note"), note: esc(m.note ? I18.code("verify_method", m.note) : "") })}</div>`;
    Object.entries(v.markets || {}).forEach(([k, mk]) => {
      h += `<h3>${T("vf.market_h", { label: esc(I18.code("verify_market", mk.label || k)), n: I18.fmtNum(mk.symbols, 0), last: esc(mk.last_date ? I18.fmtDate(mk.last_date, "ymd") : "—") })}</h3>`;
      h += `<div class="vf-meta">${T("vf.full")}</div>` + vtable(mk.full, null);
      h += `<div class="vf-meta" style="margin-top:6px">${T("vf.recent", { since: esc((mk.recent6m || {}).since ? I18.fmtDate(mk.recent6m.since, "ymd") : "") })}</div>` + vtable(mk.recent6m, mk.weakened);
    });
    p.innerHTML = h;
  }
  function showVerify() {
    const p = document.getElementById("verify-pane"); if (p) p.style.display = "block";
    const tw = document.querySelector(".tbl-wrap"); if (tw) tw.style.display = "none";
    const tb = document.getElementById("toolbar"); if (tb) tb.style.display = "none";
    renderVerify(); renderWeakBanner("verify");
  }
  function hideVerify() {
    const p = document.getElementById("verify-pane"); if (p) p.style.display = "none";
    const tw = document.querySelector(".tbl-wrap"); if (tw) tw.style.display = "";
    const tb = document.getElementById("toolbar"); if (tb) tb.style.display = "";
  }

  // ── 詳細チャート（1 つの描画関数） ─────────────────────────────────────
  // 系列の正規化: charts.1d.series（株・指数: marketcalc.ind.chart_series）があればそれを使い、
  // 無ければ（FX・金利・評価系列）同じ OHLC から BB48/288・CCI48/288 を描画用に組む。
  function rollBB(close, period, dev) {
    const out = { p2: [], m2: [], p3: [], m3: [] };
    for (let i = 0; i < close.length; i++) {
      const w = close.slice(i - period + 1, i + 1);
      if (i < period - 1 || w.some((x) => x == null)) { ["p2", "m2", "p3", "m3"].forEach((k) => out[k].push(null)); continue; }
      const m = w.reduce((a, b) => a + b, 0) / period;
      const sd = Math.sqrt(w.reduce((a, b) => a + (b - m) * (b - m), 0) / period);   // population (ddof=0)
      out.p2.push(m + 2 * sd); out.m2.push(m - 2 * sd); out.p3.push(m + 3 * sd); out.m3.push(m - 3 * sd);
    }
    return out;
  }
  function rollCCI(ohlc, period) {
    const tp = ohlc.map((o) => { const h = num(o && o.high), l = num(o && o.low), c = num(o && o.close); return (h != null && l != null && c != null) ? (h + l + c) / 3 : null; });
    const out = [];
    for (let i = 0; i < tp.length; i++) {
      const w = tp.slice(i - period + 1, i + 1);
      if (i < period - 1 || w.some((x) => x == null)) { out.push(null); continue; }
      const m = w.reduce((a, b) => a + b, 0) / period;
      const mad = w.reduce((a, b) => a + Math.abs(b - m), 0) / period;
      out.push(mad === 0 ? 0 : (tp[i] - m) / (0.015 * mad));
    }
    return out;
  }
  const allNull = (a) => !(a || []).some((v) => num(v) != null);
  // 系列が組めない（本数不足）ときは最新値だけを右端の短い線で示す（過去を捏造しない）
  function tailOnly(n, v) { const a = new Array(n).fill(null); if (num(v) == null) return a; const k = Math.max(2, Math.round(n * 0.06)); for (let i = n - k; i < n; i++) a[i] = v; return a; }
  function normalize(c) {
    const ohlc = (c && c.ohlc) || [];
    const ind = (c && c.indicators) || {};
    const bbI = ind.bollinger_bands || {}, cciI = ind.cci || {};
    const dates0 = ohlc.map((o) => (o && o.time ? String(o.time).slice(0, 10) : null));
    const s = c && c.series;
    if (s && s.close && s.close.length >= 2) {
      const n = s.close.length;
      const dates = dates0.length >= n ? dates0.slice(dates0.length - n) : new Array(n).fill(null);
      return { n, dates, close: s.close, bb48: s.bb48 || {}, bb288: s.bb288 || {}, cci48: s.cci48 || [], cci288: s.cci288 || [], marks: s.marks || [] };
    }
    const close = ohlc.map((o) => num(o && o.close));
    const n = close.length;
    const band = (period, blk) => {
      const r = rollBB(close, period);
      if (!allNull(r.p2)) return r;
      const b2 = (blk && blk.std_2) || {}, b3 = (blk && blk.std_3) || {};
      return { p2: tailOnly(n, num(b2.upper)), m2: tailOnly(n, num(b2.lower)), p3: tailOnly(n, num(b3.upper)), m3: tailOnly(n, num(b3.lower)) };
    };
    const cci = (period) => { const r = rollCCI(ohlc, period); return allNull(r) ? tailOnly(n, num((cciI[String(period)] || {}).value)) : r; };
    return { n, dates: dates0, close, bb48: band(48, bbI["48"]), bb288: band(288, bbI["288"]), cci48: cci(48), cci288: cci(288), marks: [] };
  }
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  // 文字幅の目安（全角 = 1em、半角 = 0.6em）
  const textW = (s, fs) => Array.from(String(s)).reduce((a, ch) => a + (/[^\u0000-ÿ]/.test(ch) ? fs : fs * 0.6), 0);
  function monthTicks(dates, X, x0, x1, fs) {
    const months = [];   // {i, y, m}
    let prev = null;
    dates.forEach((d, i) => {
      if (!d) return;
      const y = +d.slice(0, 4), m = +d.slice(5, 7), key = y * 12 + (m - 1);
      if (key !== prev) { months.push({ i, y, m, key, d: d.slice(0, 7) }); prev = key; }
    });
    if (months.length < 2) return [];
    const span = Math.max(1, months[months.length - 1].key - months[0].key);
    const pxPerMonth = (x1 - x0) / span;
    const wMax = textW(I18.fmtDate("2026-12", "ym"), fs) + 10;
    const step = [1, 2, 3, 4, 6, 12].find((k) => k * pxPerMonth >= wMax) || 12;
    const picked = months.filter((t, j) => j > 0 && (t.m - 1) % step === 0);
    const out = []; let lastYear = null, lastRight = -1e9;
    picked.forEach((t) => {
      const x = X(t.i);
      const label = (lastYear === null || t.y !== lastYear) ? I18.fmtDate(t.d, "ym") : I18.fmtDate(t.d, "m");
      const half = textW(label, fs) / 2;
      if (x - half < x0 + 1 || x + half > x1 - 1 || x - half < lastRight + 6) return;   // 枠・隣のラベルと重ねない
      out.push({ x, label }); lastYear = t.y; lastRight = x + half;
    });
    return out;
  }
  function drawPriceCciChart(c, opts) {
    const o = opts || {};
    const d = normalize(c);
    const n = d.n;
    if (n < 2 || allNull(d.close)) return "";
    const vw = (typeof window !== "undefined" && window.innerWidth) || 1000;
    const W = Math.round(o.width || Math.max(300, Math.min(1100, vw - 48) - 10));
    const FS = 10, L = Math.max(44, Math.round(textW("000,000", FS) + 10)), R = 8;
    const TOP = 6, PH = Math.round(Math.max(170, Math.min(240, W * 0.3))), XA = 18, TT = 16, CH = 120;
    const pTop = TOP, pBot = TOP + PH;                                  // 上段の枠
    const cTop = pBot + XA + TT, cBot = cTop + CH;                       // 下段の枠
    const H = cBot + XA + 2;
    const x0 = L, x1 = W - R;
    const X = (i) => x0 + (i / (n - 1)) * (x1 - x0);
    // 上段の範囲: 終値と BB48 ±3σ だけ（BB288 は範囲に入れず、はみ出す分は切り取る）。0 未満は描かない。
    const ys = [];
    [d.close, d.bb48.p3, d.bb48.m3].forEach((a) => (a || []).forEach((v) => { if (num(v) != null && v >= 0) ys.push(v); }));
    let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo -= Math.abs(lo) * 0.01 || 1; hi += Math.abs(hi) * 0.01 || 1; }
    const pad = (hi - lo) * 0.05; lo = Math.max(0, lo - pad); hi += pad;
    const Y = (v) => pTop + (1 - (v - lo) / (hi - lo)) * PH;
    // 下段の範囲: ±200 の線が枠から離れるよう最小 ±250、ラベル同士が重ならないよう最大 ±400 で打ち切る
    const cv = []; [d.cci48, d.cci288].forEach((a) => (a || []).forEach((v) => { if (num(v) != null) cv.push(Math.abs(v)); }));
    const cap = Math.min(400, Math.max(250, Math.ceil(Math.max(0, ...cv) / 50) * 50));
    const YC = (v) => cTop + (1 - (Math.max(-cap, Math.min(cap, v)) + cap) / (2 * cap)) * CH;
    const uid = "sg" + Math.random().toString(36).slice(2, 8);
    const poly = (a, Yf, nonNeg) => { const segs = []; let seg = []; (a || []).forEach((v, i) => { if (num(v) == null || (nonNeg && v < 0)) { if (seg.length > 1) segs.push(seg.join(" ")); seg = []; } else seg.push(X(i).toFixed(1) + "," + Yf(v).toFixed(1)); }); if (seg.length > 1) segs.push(seg.join(" ")); return segs; };
    const line = (a, Yf, col, w, dash, clip, nonNeg) => poly(a, Yf, nonNeg).map((pts) => `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="${w}"${dash ? ` stroke-dasharray="${dash}"` : ""} clip-path="url(#${clip})"/>`).join("");
    const txt = (x, y, s, anchor, extra) => `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle" font-size="${FS}" fill="var(--text-faint)"${extra || ""}>${esc(s)}</text>`;
    let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(T("chart.aria"))}">`
      + `<defs><clipPath id="${uid}p"><rect x="${x0}" y="${pTop}" width="${x1 - x0}" height="${PH}"/></clipPath>`
      + `<clipPath id="${uid}c"><rect x="${x0}" y="${cTop}" width="${x1 - x0}" height="${CH}"/></clipPath></defs>`;
    // 価格の y 軸（左の余白・枠の内側に細い目盛り線）
    const step = niceStep((hi - lo) / 5);
    const dec = Math.min(5, ((+step.toPrecision(6)).toString().split(".")[1] || "").length);
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      const y = Y(v); if (y < pTop + FS * 0.7 || y > pBot - FS * 0.7) continue;    // 枠と重ねない
      svg += `<line x1="${x0}" x2="${x1}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--border)" stroke-width="0.6"/>`
        + txt(x0 - 6, y, I18.fmtNum(v, dec), "end");
    }
    // 日付の x 軸（上段・下段とも）
    const ticks = monthTicks(d.dates, X, x0, x1, FS);
    ticks.forEach((t) => {
      [[pTop, pBot], [cTop, cBot]].forEach(([a, b]) => {
        svg += `<line x1="${t.x.toFixed(1)}" x2="${t.x.toFixed(1)}" y1="${a}" y2="${b}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2 3"/>`
          + txt(t.x, b + XA / 2 + 1, t.label, "middle");
      });
    });
    svg += `<rect x="${x0}" y="${pTop}" width="${x1 - x0}" height="${PH}" fill="none" stroke="var(--border)"/>`;
    const cp = uid + "p", cc = uid + "c";
    svg += line(d.bb288.p3, Y, C_ORANGE, 1, "1.5 2.5", cp, true) + line(d.bb288.m3, Y, C_ORANGE, 1, "1.5 2.5", cp, true);
    svg += line(d.bb288.p2, Y, C_ORANGE, 1.2, "", cp, true) + line(d.bb288.m2, Y, C_ORANGE, 1.2, "", cp, true);
    svg += line(d.bb48.p3, Y, C_BLUE, 1, "1.5 2.5", cp, true) + line(d.bb48.m3, Y, C_BLUE, 1, "1.5 2.5", cp, true);
    svg += line(d.bb48.p2, Y, C_BLUE, 1.2, "", cp, true) + line(d.bb48.m2, Y, C_BLUE, 1.2, "", cp, true);
    svg += line(d.close, Y, "var(--text)", 1.6, "", cp, true);
    (d.marks || []).forEach((m) => {
      const v = num(d.close[m.i]); if (v == null || v < 0) return;
      const x = X(m.i).toFixed(1);
      if (m.type === "sell") svg += `<text x="${x}" y="${(Y(v) - 6).toFixed(1)}" text-anchor="middle" font-size="11" fill="#dc2626" clip-path="url(#${cp})">▼</text>`;
      else svg += `<text x="${x}" y="${(Y(v) + 14).toFixed(1)}" text-anchor="middle" font-size="11" fill="${m.type === "long_oversold" ? "#0d9488" : "#16a34a"}" clip-path="url(#${cp})">▲</text>`;
    });
    // 下段 CCI: 見出し・±100・±200・0 の線（ラベルは左の余白＝線にも枠にも重ねない）
    svg += `<text x="${x0}" y="${(cTop - TT / 2).toFixed(1)}" dominant-baseline="middle" font-size="11" font-weight="700" fill="var(--text-dim)">${esc(T("chart.cci_title"))}</text>`;
    svg += `<rect x="${x0}" y="${cTop}" width="${x1 - x0}" height="${CH}" fill="none" stroke="var(--border)"/>`;
    [[200, "1.5 3"], [100, "3 3"], [0, ""], [-100, "3 3"], [-200, "1.5 3"]].forEach(([g, ds]) => {
      const y = YC(g);
      svg += `<line x1="${x0}" x2="${x1}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--text-faint)" stroke-width="${g === 0 ? 0.9 : 0.7}"${ds ? ` stroke-dasharray="${ds}"` : ""}/>`
        + txt(x0 - 6, y, g > 0 ? "+" + g : String(g), "end");
    });
    svg += line(d.cci288, YC, C_ORANGE, 1.3, "", cc) + line(d.cci48, YC, C_BLUE, 1.3, "", cc);
    svg += `</svg>`;
    const marks = (d.marks || []).length > 0;
    const leg = `<div class="sg-leg"><span><i style="border-color:var(--text)"></i>${T("chart.leg_close")}</span>`
      + `<span><i style="border-color:${C_BLUE}"></i>BB48 ±2σ</span><span><i class="dot" style="border-color:${C_BLUE}"></i>BB48 ±3σ</span>`
      + `<span><i style="border-color:${C_ORANGE}"></i>BB288 ±2σ</span><span><i class="dot" style="border-color:${C_ORANGE}"></i>BB288 ±3σ</span>`
      + (marks ? `<span style="color:#16a34a">▲ ${sigText("buy")}</span><span style="color:#0d9488">▲ ${sigText("buy_long_oversold")}</span><span style="color:#dc2626">▼ ${sigText("sell")}</span>` : "")
      + `<span>${T("chart.leg_lower")} <i style="border-color:${C_BLUE}"></i>CCI48 <i style="border-color:${C_ORANGE}"></i>CCI288 ${T("chart.leg_lines")}</span></div>`;
    const capTxt = T("chart.range_note") + " " + (marks ? T("chart.rule_cap", { sell: T("code.sell_note.sell_note") }) : T("chart.context_cap"));
    return `<div class="sg-chart">${svg}${leg}<div class="dt-cap">${capTxt}</div></div>`;
  }

  window.SIG = { loadVerify, cols, cell, judgeCell, renderUsBuyList, renderStaleBanner, renderWeakBanner,
    showVerify, hideVerify, drawPriceCciChart, EQ_TABS, BUY, SELL, state: S };
})();
