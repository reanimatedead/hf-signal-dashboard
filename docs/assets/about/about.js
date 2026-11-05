/* assets/about/about.js — 「仕組み / About」タブ。docs/about.json を読んで描くだけ（計算しない・数字を書かない）。
 *
 * about.json は src/screener/about.py が コード（ind.P・判定の規則・総合スコアの表・deploy.yml の cron）と
 * 生成物（data.json の meta・verify.json）から毎回作る。ここに期間・しきい値・時刻を直書きしない。
 * 文言はすべて assets/i18n/dict.js（T / I18.code）。説明文の {n} などの穴は about.json の値で埋める。
 * render(a) は文字列を返すだけ（DOM に触らない）ので、tests/test_about.py が node で直接呼んで確かめる。
 */
(function () {
  "use strict";
  const S = { data: null, state: "idle" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const n0 = (v) => (num(v) == null ? "—" : I18.fmtNum(v, 0));
  const nn = (v) => (num(v) == null ? "—" : I18.fmtNum(v));
  const pct = (v) => (num(v) == null ? "—" : I18.fmtSigned(v, 2) + "%");
  const OPS = { ">": "&gt;", "<": "&lt;", ">=": "≥", "<=": "≤" };   // HTML に入れるので実体参照
  const sig = (c) => I18.code("chart_signal", c);
  const sep = () => T("common.sep_list");
  const REPO = "https://github.com/reanimatedead/hf-signal-dashboard";

  if (typeof document !== "undefined" && document.head && document.createElement) {
    const st = document.createElement("style");
    st.textContent = `
  #about-pane{display:none;padding:12px 16px 24px;max-width:960px;line-height:1.6;font-size:13px;overflow-wrap:anywhere}
  #about-pane h2{font-size:16px;margin:4px 0 8px} #about-pane h3{font-size:14px;margin:18px 0 6px;border-bottom:1px solid var(--border);padding-bottom:3px}
  #about-pane h4{font-size:13px;margin:10px 0 4px}
  #about-pane p,#about-pane li{color:var(--text-dim)} #about-pane b{color:var(--text)}
  #about-pane ul{margin:4px 0 4px 18px;padding:0}
  #about-pane .ab-disc{padding:6px 10px;border:1px solid #e5a23d;border-radius:4px;color:#e5a23d;background:rgba(229,162,61,.10);font-weight:700}
  #about-pane .ab-tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:4px 0}
  #about-pane table{border-collapse:collapse;font-size:12px;min-width:100%}
  #about-pane th,#about-pane td{padding:3px 8px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
  #about-pane table.ab-wide{min-width:640px}
  #about-pane td{white-space:normal} #about-pane th{white-space:nowrap}
  #about-pane td.r,#about-pane th.r{text-align:right;white-space:nowrap}
  #about-pane dl{margin:4px 0} #about-pane dt{font-weight:700;color:var(--text);margin-top:6px} #about-pane dd{margin:0 0 0 12px;color:var(--text-dim)}
  #about-pane .ab-ok{color:var(--green)} #about-pane .ab-bad{color:#e5a23d;font-weight:700}
  #about-pane code{font-size:12px}
  @media (max-width:600px){#about-pane{padding:10px 10px 20px;font-size:12px}#about-pane table{font-size:11px}}
  `;
    document.head.appendChild(st);
  }

  // ── 部品 ──
  const sec = (titleKey, body) => `<h3>${T(titleKey)}</h3>${body}`;
  const table = (heads, rows, cls) => `<div class="ab-tw"><table${cls ? ` class="${cls}"` : ""}><thead><tr>${heads.map((h) => `<th${h.r ? ' class="r"' : ""}>${h.t}</th>`).join("")}</tr></thead>`
    + `<tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${heads[i] && heads[i].r ? ' class="r"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const sigma = (k) => (k > 0 ? "+" : k < 0 ? "−" : "") + I18.fmtNum(Math.abs(k)) + "σ";
  function cond(c) {
    if (c.ind === "cci") return T("ab.cond_cci", { n: n0(c.n), op: OPS[c.op] || esc(c.op), v: I18.fmtSigned(c.v, 0) });
    if (c.ind === "close_vs_bb") return T("ab.cond_bb", { n: n0(c.n), op: OPS[c.op] || esc(c.op), k: sigma(c.k) });
    return esc(JSON.stringify(c));
  }
  const fmtT = (iso) => (iso ? I18.fmtDate(iso, "ymdhm") : "—");

  // ── 各節 ──
  function status(a) {
    const m = a.meta || {}, sc = a.schedule || {}, cm = a.commit || {};
    let h = "";
    if (m.available) {
      const t = Date.parse(m.updated_at || "");
      const age = isFinite(t) ? (Date.now() - t) / 36e5 : null;
      const lim = num(m.stale_hours);
      const ok = age != null && lim != null && age <= lim;
      h += `<li>${T("ab.st_updated", { t: fmtT(m.updated_at), h: age == null ? "—" : I18.fmtNum(age, 1) })} `
        + (ok ? `<span class="ab-ok">${T("ab.st_ok", { lim: n0(lim) })}</span>` : `<span class="ab-bad">${T("ab.st_stale", { lim: n0(lim) })}</span>`) + `</li>`;
    } else h += `<li class="ab-bad">${T("ab.st_no_meta")}</li>`;
    Object.keys(sc.crons || {}).forEach((job) => {
      h += `<li>${T("ab.st_next", { job: T("ab.job." + job), t: fmtT((sc.next || {})[job]), cron: esc((sc.crons[job] || []).join(sep())) })}</li>`;
    });
    const sha = cm.sha ? `<a href="${REPO}/commit/${esc(cm.sha)}" target="_blank" rel="noopener"><code>${esc(String(cm.sha).slice(0, 7))}</code></a>` : "—";
    h += `<li>${T("ab.st_build", { sha, t: fmtT(a.generated_at) })}</li>`;
    return sec("ab.h_status", `<ul>${h}</ul>`);
  }
  function sources(a) {
    const m = a.meta || {};
    let h = `<p>${T("ab.src_text")}</p>`;
    if (!m.available) return sec("ab.h_sources", h + `<p class="ab-bad">${T("ab.st_no_meta")}</p>`);
    const nan = m.nan_report || {};
    const rows = Object.entries(m.universe || {}).map(([tab, u]) => {
      const f = u.fetch_failures || [];
      const nr = nan[tab] || {};
      return [T("tab." + tab), `${n0(u.count)} / ${n0(u.target)}`, T("ab.src." + u.universe_source), T("ab.mode." + u.source_mode),
        f.length ? `<span class="ab-bad">${n0(f.length)}</span>: ${esc(f.join(sep()))}` : "0",
        `${n0(nr.price_null)} / ${n0(nr.chart_unavailable)}`];
    });
    h += table([{ t: T("ab.th_tab") }, { t: T("ab.th_count"), r: 1 }, { t: T("ab.th_source") }, { t: T("ab.th_mode") },
      { t: T("ab.th_fail") }, { t: T("ab.th_nan"), r: 1 }], rows, "ab-wide");
    const other = Object.entries(m.counts || {}).filter(([k]) => !(k in (m.universe || {})));
    if (other.length) h += `<p>${T("ab.src_other", { items: other.map(([k, v]) => `${T("ab.cnt." + k)} ${n0(v)}`).join(sep()) })}</p>`;
    const fb = m.fallbacks || [];
    h += `<p>${fb.length ? `<span class="ab-bad">${T("ab.src_fallbacks", { items: fb.map((f) => esc(f.source) + " (" + esc(I18.code("fallback_reason", f.reason)) + ")").join(sep()) })}</span>` : T("ab.src_no_fallbacks")}</p>`;
    return sec("ab.h_sources", h);
  }
  function tabs(a) {
    return sec("ab.h_tabs", `<dl>${(a.tabs || []).map((t) => `<dt>${T("tab." + t)}</dt><dd>${T("ab.tab." + t)}</dd>`).join("")}</dl>`);
  }
  function chartRules(a) {
    const r = a.rules || {};
    const items = (r.chart || []).map((x) => `<li><b>${esc(sig(x.code))}</b>: ${(x.all || []).map(cond).join(T("ab.and"))}`
      + (x.only_if_no_signal ? T("ab.only_if_no_signal") : "") + (x.note ? `<br><span>${T("code.sell_note.sell_note")}</span>` : "") + `</li>`).join("");
    const p = (a.params || {}).P || {};
    return sec("ab.h_chart", `<p>${T("ab.chart_intro", { min: n0((a.params || {}).min_bars) })}</p><ul>${items}</ul>`
      + `<p>${T("ab.chart_order", { buy: (r.buy_type || []).map(sig).join(sep()) })}</p>`
      + `<p>${T("ab.chart_th_note", { th: n0(p.cci_th), lv: n0((a.params || {}).cci_alert_level) })}</p>`);
  }
  function cci200(a) {
    const c2 = (a.rules || {}).cci200;
    if (!c2) return "";
    const per = c2.periods || [], v = { level: n0(c2.level), s: n0(per[0]), l: n0(per[1]) };
    return sec("ab.h_c2", `<ul><li><b style="color:#22d3ee">◆ ${esc(sig("buy_cci200"))}</b>: ${T("ab.c2_buy", v)}</li>`
      + `<li><b style="color:#e879f9">◆ ${esc(sig("sell_cci200"))}</b>: ${T("ab.c2_sell", v)}</li></ul>`
      + `<p>${T("code.sell_note.sell_note")}</p><p>${T("ab.c2_points")}</p>`);
  }
  function cciEvents(a) {
    const e = (a.rules || {}).cci_events || {};
    const per = e.periods || [], lv = n0(e.level), sp = e.spike || {};
    const v = { level: lv, s: n0(per[0]), l: n0(per[1]) };
    const li = (e.events || []).map((k) => `<li>${T("ab.ev." + k, v)}</li>`).join("");
    const q = num(sp.quantile), fr = num(sp.min_frac_of_universe);
    return sec("ab.h_cci", `<p>${T("ab.cci_intro", v)}</p><ul>${li}</ul>`
      + `<p>${T("ab.cci_notify", { items: (e.notify_events || []).map((k) => T("ab.evn." + k, v)).join(sep()) })}</p>`
      + `<p>${T("ab.cci_spike", { top: q == null ? "—" : I18.fmtNum((1 - q) * 100), days: n0(sp.lookback_days), min: n0(sp.min_days), frac: fr == null ? "—" : I18.fmtNum(fr * 100), ev: T("ab.evn.both_down", v) })}</p>`);
  }
  function composite(a) {
    const c = (a.rules || {}).composite || {}, p = c.periods || {}, e = p.ema || [], md = p.macd || [], mc = c.macd || {};
    const ev = { a: n0(e[0]), b: n0(e[1]), c: n0(e[2]) };
    const tier = (arr, name) => (arr || []).map((t) => `${esc(name)} ≤ ${nn(t.le)} → ${n0(t.pts)}`).join(sep());
    const emaT = (arr, els) => (arr || []).map((t) => `${esc(T("ab.ema." + t.cond, ev))} → ${n0(t.pts)}`).concat([T("ab.otherwise", { pts: n0(els) })]).join(sep());
    const rows = [
      [T("ab.cp_rsi", { n: n0(p.rsi) }), tier(c.rsi_tiers, "RSI") + sep() + T("ab.otherwise", { pts: "0" })],
      [T("ab.cp_macd", { f: n0(md[0]), s: n0(md[1]), g: n0(md[2]) }), T("ab.cp_macd_rule", { pos: n0(mc.pos), max: nn(num(mc.scale) != null && num(mc.factor) != null ? mc.scale * mc.factor : null) })],
      [T("ab.cp_ema", ev), emaT(c.ema_with_200, c.ema_with_200_else) + `<br>${T("ab.cp_ema_short", { bars: n0(p.ema200_min_bars), c: ev.c })}: ` + emaT(c.ema_no_200, c.ema_no_200_else)],
      [T("ab.cp_bb", { n: n0(p.bb), k: nn(p.bb_k) }), tier(c.bb_tiers, "BB%") + sep() + T("ab.otherwise", { pts: "0" })],
    ];
    const labs = (c.label_cuts || []).map((t) => `${esc(I18.code("signal", t.label))} ≥ ${n0(t.ge)}`).concat([`${esc(I18.code("signal", c.label_else))}: ${T("ab.below")}`]).join(sep());
    return sec("ab.h_score", `<p>${T("ab.cp_intro", { max: n0(c.max) })}</p>`
      + table([{ t: T("ab.th_part") }, { t: T("ab.th_points") }], rows) + `<p>${T("ab.cp_labels", { items: labs })}</p>`);
  }
  // 売買スコア（about.json の rules.score = marketcalc.score.rules()。配分を手で書かない）
  function tradeScore(a) {
    const r = (a.rules || {}).score;
    if (!r) return "";
    const w = r.weights || {}, mx = r.max || {};
    const part = (k) => T("sc.part_" + k);
    const item = (grp, k) => (grp === "chart" || grp === "sell") && k !== "cci_both_down" ? esc(sig(k)) : T("ab.sc_item." + k);
    const rows = ["value", "quality", "chart", "penalty", "sell"].map((g) => [
      (g === "sell" ? T("col.score_sell") : part(g)) + (g === "quality" ? `<br><span>${T("sc.unverified")}</span>` : ""),
      Object.entries(w[g] || {}).map(([k, v]) => `${item(g, k)} ${g === "penalty" ? "−" : ""}${n0(v)}`).join(sep()),
      g in mx ? n0(mx[g]) : "—",
    ]);
    const c2 = (a.rules || {}).cci200 || {};
    const pt = c2.points || {};
    if (Object.keys(pt).length) {
      const per = c2.periods || [];
      rows.splice(3, 0, [T("ab.c2_row", { l: n0(c2.level), s: n0(per[0]), ll: n0(per[1]) }),
        Object.entries(pt).map(([m, v]) => `${T("ab.mkt." + m)}: ` + Object.entries(v).map(([k, p]) => `${k.endsWith("_spike") ? T("ab.c2_spike") : esc(sig(k))} ${p > 0 ? "+" : p < 0 ? "−" : ""}${n0(Math.abs(p))}`).join(sep())
          + ((c2.unverified_markets || []).includes(m) ? ` ${T("vf.c200_unverified")}` : "")).join("<br>"), "—"]);
    }
    const tiers = (r.tiers || []).map((t) => `${T("sc.tier_n", { n: n0(t.tier) })} ≥ ${n0(t.ge)}`).concat([T("sc.tier_n", { n: n0(r.tier_else) }) + ": " + T("ab.below")]).join(sep());
    const st = ((a.verify || {}).score_tiers) || {};
    const res = Object.entries(st).map(([k, t]) => {
      const f = (t.full || {}).tier5 || {}, b = (t.full || {}).base || {};
      return `<li>${esc(I18.code("verify_market", k === "us" ? "us_union" : k))}: ${T("ab.sc_top", { n: n0(f.n), m: pct(f.median), base: pct(b.median) })}`
        + (t.weakened === true ? ` <span class="ab-bad">${T("vf.weak_mark")}</span>` : "") + `</li>`;
    }).join("");
    return sec("ab.h_trade_score", `<p>${T("ab.sc_intro", { total: (r.total || []).map(part).join(" + ") })}</p>`
      + table([{ t: T("ab.th_part") }, { t: T("ab.th_points") }, { t: T("ab.sc_th_max"), r: 1 }], rows)
      + `<p>${T("ab.sc_rules", { pct: nn(num(r.low_turnover_q) == null ? null : r.low_turnover_q * 100), days: n0(r.turnover_days), bd: n0(r.earnings_soon_bdays) })}</p>`
      + `<p>${T("ab.sc_tiers", { items: tiers })}</p><p>${T("ab.sc_gate")}</p><p>${T("ab.sc_public_jp")}</p>`
      + `<p>${T("code.sell_note.sell_note")}</p>` + (res ? `<p>${T("ab.sc_results")}</p><ul>${res}</ul>` : ""));
  }
  function indicators(a) {
    const P = (a.params || {}).P || {}, p = (a.params || {}).composite_periods || {}, md = p.macd || [], e = p.ema || [];
    const items = [
      ["CCI", T("ab.ind_cci", { s: n0(P.cci_short), l: n0(P.cci_long), th: n0(P.cci_th) })],
      ["BB", T("ab.ind_bb", { s: n0(P.bb_short), l: n0(P.bb_long), k2: nn(P.k2), k3: nn(P.k3), n: n0(p.bb) })],
      ["RSI", T("ab.ind_rsi", { n: n0(p.rsi) })],
      ["MACD", T("ab.ind_macd", { f: n0(md[0]), s: n0(md[1]), g: n0(md[2]) })],
      ["EMA", T("ab.ind_ema", { a: n0(e[0]), b: n0(e[1]), c: n0(e[2]) })],
      ["ATR", T("ab.ind_atr", { n: n0(p.atr) })],
      [T("ab.ind_score_name"), T("ab.ind_score")],
    ];
    return sec("ab.h_ind", `<dl>${items.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`);
  }
  function verify(a) {
    const v = a.verify || {};
    if (!v.available) return sec("ab.h_verify", `<p class="ab-bad">${T("ab.vf_none")}</p>`);
    const m = v.method || {};
    let h = `<p>${T("ab.vf_intro", { h: n0(m.horizon_days), mo: n0(m.recent_months), asof: v.as_of ? I18.fmtDate(v.as_of, "ymd") : "—" })}</p>`;
    const wi = (v.weakened_items || []).map((x) => (window.SIG && SIG.weakItem ? SIG.weakItem(x) : esc(x))).join(sep());
    h += `<p>${v.weakened ? `<span class="ab-bad">${T("ab.vf_weak", { items: esc(wi) })}</span>` : `<span class="ab-ok">${T("ab.vf_not_weak")}</span>`}</p>`;
    const codes = ((a.rules || {}).buy_type || []).concat((a.rules || {}).sell_type || []);
    Object.entries(v.markets || {}).forEach(([k, mk]) => {
      const full = mk.full || {}, rec = mk.recent6m || {}, b = full.base || {}, w = mk.weakened || {};
      const row = (name, s, rs, weak) => [name, n0((s || {}).n), pct((s || {}).median), num((s || {}).up_pct) == null ? "—" : I18.fmtNum(s.up_pct, 0) + "%",
        pct((rs || {}).median), weak === true ? `<span class="ab-bad">${T("vf.weak_mark")}</span>` : weak === false ? T("ab.vf_ok") : "—"];
      const rows = [row(T("vf.base_row"), b, rec.base, null)].concat(codes.map((c) => row(esc(sig(c)), (full.chart || {})[c], (rec.chart || {})[c], w["chart:" + c])));
      h += `<h4>${T("ab.vf_market", { label: esc(I18.code("verify_market", mk.label || k)), n: n0(mk.symbols), last: mk.last_date ? I18.fmtDate(mk.last_date, "ymd") : "—" })}</h4>`
        + table([{ t: T("vf.th_judge") }, { t: T("vf.th_n"), r: 1 }, { t: T("vf.th_median"), r: 1 }, { t: T("vf.th_up"), r: 1 }, { t: T("ab.th_recent_median"), r: 1 }, { t: T("ab.th_weak") }], rows);
    });
    return sec("ab.h_verify", h + `<p>${T("ab.vf_more")}</p>`);
  }
  function limits(a) {
    return sec("ab.h_limits", `<ul>${(a.limitations || []).map((c) => `<li>${T("ab.lim." + c)}</li>`).join("")}</ul>`);
  }
  function mac(a) {
    const mm = a.mac_mini || {}, tp = (mm.theory_price || {}).params || {}, ov = mm.overall || {}, cq = ov.cheap_quintile || {}, cn = mm.cci_notify || {};
    const p100 = (v) => (num(v) == null ? "—" : I18.fmtNum(v * 100));
    const mk = (arr) => (arr || []).map((k) => T("ab.mkt." + k)).join(sep());
    const items = [
      T("ab.mac_theory", { r: p100(tp.r), years: n0(tp.years), cap: p100(tp.roe_cap), keep: p100(tp.payout_keep) }),
      T("ab.mac_overall", { buy: (ov.buy_type || []).map(sig).join(sep()), markets: (cq.tse_markets || []).map((k) => T("ab.tse." + k)).join(sep()), mcap: n0(cq.min_market_cap_oku_jpy) }),
      T("ab.mac_notify", { markets: mk(cn.markets), spike: mk(cn.spike_markets), unv: mk(cn.unverified_markets) }),
    ];
    return sec("ab.h_mac", `<p>${T("ab.mac_intro")}</p><ul>${items.map((x) => `<li>${x}</li>`).join("")}</ul><p>${T("ab.mac_private")}</p>`);
  }

  function render(a) {
    if (!a) return `<h2>${T("tab.about")}</h2><p>${T(S.state === "loading" ? "ab.loading" : "ab.unreadable")}</p>`;
    return `<h2>${T("ab.title")}</h2><p class="ab-disc">${T("ab.disclaimer")}</p><p>${T("ab.intro")}</p>`
      + status(a) + tabs(a) + chartRules(a) + cci200(a) + tradeScore(a) + composite(a) + cciEvents(a) + indicators(a) + verify(a) + sources(a) + limits(a) + mac(a)
      + sec("ab.h_json", `<p>${T("ab.json_text", { link: `<a href="about.json" target="_blank" rel="noopener">about.json</a>` })}</p>`);
  }

  async function load() {
    if (S.state === "ok" || S.state === "loading") return;
    S.state = "loading";
    try {
      const r = await fetch("about.json?t=" + Date.now(), { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      S.data = await r.json(); S.state = "ok";
    } catch (e) { S.data = null; S.state = "error"; }
    const p = document.getElementById("about-pane");
    if (p && p.style.display === "block") p.innerHTML = render(S.data);
  }
  function show() {
    const p = document.getElementById("about-pane"); if (!p) return;
    p.style.display = "block";
    const tw = document.querySelector(".tbl-wrap"); if (tw) tw.style.display = "none";
    const tb = document.getElementById("toolbar"); if (tb) tb.style.display = "none";
    p.innerHTML = render(S.data);
    load();
  }
  function hide() {
    const p = document.getElementById("about-pane"); if (p) p.style.display = "none";
  }

  window.ABOUT = { render, show, hide, load, state: S };
})();
