/* survival.js — SURVIVAL タブ (Agent A + Agent D)
 *
 * Renders the SURVIVAL pane from DATA.survival_loop.
 * Mode-B "taken / skipped" and Mode-C "outcome" are recorded in localStorage
 * (NEVER posted back to the repo / network). Aggregates hit_rate / ROI /
 * Brier / pattern win rates client-side from the same log.
 */
(function(){
  "use strict";

  const LOG_KEY = "hf_survival_log_v1";

  // ── i18n: the single dictionary (assets/i18n/dict.js) ------------
  function t(k, v){ return T("sv." + k, v); }
  const code = (f, v) => I18.code(f, v);
  // pattern = (regime, distortion) のコード 2 つ → 「高ボラ / ゆがみ大」など（辞書で訳す）
  const patternLabel = (regime, dist) => code("pattern_regime", regime) + " / " + code("pattern_distortion", dist);

  // ── localStorage helpers (公開リポに値を書かない) ----------------
  function loadLog(){
    try { return JSON.parse(localStorage.getItem(LOG_KEY) || "[]"); }
    catch (e) { return []; }
  }
  function saveLog(arr){
    try { localStorage.setItem(LOG_KEY, JSON.stringify(arr || [])); } catch (e) {}
  }
  function addEntry(entry){
    const arr = loadLog();
    arr.push(Object.assign({ ts: Date.now() }, entry));
    saveLog(arr);
  }
  function recordOutcome(id, outcome, realizedPct){
    const arr = loadLog();
    const idx = arr.findIndex(e => e.id === id);
    if (idx < 0) return;
    arr[idx].outcome = outcome;
    if (typeof realizedPct === "number" && Number.isFinite(realizedPct)) {
      arr[idx].realized_pct = realizedPct;
    }
    saveLog(arr);
  }

  // ── number formatting --------------------------------------------
  function fmtPct(v, d){
    if (v === null || v === undefined || !Number.isFinite(+v)) return t("no_data");
    return I18.fmtNum(v, d != null ? d : 2) + "%";
  }
  function fmtNum(v, d){
    if (v === null || v === undefined || !Number.isFinite(+v)) return t("no_data");
    return I18.fmtNum(v, d != null ? d : 2);
  }
  function esc(s){
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;",
    }[c]));
  }

  // ── Risk gate banner ---------------------------------------------
  function renderRiskGate(rg){
    const el = document.getElementById("sv-risk-gate");
    if (!el || !rg) return;
    const color = rg.color || "yellow";
    const label = code("risk_gate_label", rg.label || "neutral");
    const reasons = (rg.reasons || []).slice(0, 4).map(x => esc(x && typeof x === "object" ? T("code.risk_gate_reason." + x.code, x.vars || x) : code("risk_gate_reason", x))).join(" · ") || "—";
    el.dataset.color = color;
    el.innerHTML =
      '<div class="sv-rg-line">' +
        '<span class="sv-rg-tag sv-rg-' + esc(color) + '">' + esc(label) + '</span>' +
        '<span class="sv-rg-label">' + esc(t("risk_gate")) + '</span>' +
      '</div>' +
      '<div class="sv-rg-reasons"><b>' + esc(t("reasons")) + ':</b> ' + reasons + '</div>';
  }

  // ── Auto risk card -----------------------------------------------
  function renderAutoRisk(ar){
    const el = document.getElementById("sv-auto-risk");
    if (!el || !ar) return;
    el.innerHTML =
      '<div class="sv-card-hd">' + esc(t("auto_risk")) + '</div>' +
      '<div class="sv-card-grid">' +
        '<div><b>' + esc(t("per_trade")) + '</b><span>' + fmtPct(ar.per_trade_pct, 3) + '</span></div>' +
        '<div><b>' + esc(t("max_concurrent")) + '</b><span>' + esc(ar.max_concurrent) + '</span></div>' +
        '<div><b>' + esc(t("dd_shrink")) + '</b><span>' + fmtPct(ar.dd_shrink_pct, 1) + '</span></div>' +
        '<div><b>' + esc(t("dd_stop")) + '</b><span>' + fmtPct(ar.dd_stop_pct, 1) + '</span></div>' +
        '<div><b>' + esc(t("target_vol")) + '</b><span>' + fmtPct(ar.target_vol_pct, 2) + '</span></div>' +
        '<div><b>' + esc(t("realized_vol")) + '</b><span>' + fmtPct(ar.realized_vol_pct, 2) + '</span></div>' +
      '</div>' +
      '<div class="sv-card-src">' + esc(ar.source ? code("auto_risk_source", ar.source) : "") + '</div>';
  }

  // ── Candidates table ---------------------------------------------
  function renderCandidates(list){
    const el = document.getElementById("sv-candidates");
    if (!el) return;
    if (!Array.isArray(list) || !list.length) {
      el.innerHTML = '<div class="sv-empty">' + esc(t("no_candidates")) + '</div>';
      return;
    }
    const shown = list.slice(0, 8);
    let html =
      '<div class="sv-card-hd">' + esc(t("candidates")) + ' (' + shown.length + ')</div>' +
      '<table class="sv-table"><thead><tr>' +
        ths(["symbol", "edge", "dir", "stretch", "vol_pct", "pf", "status"]) + '<th></th>' +
      '</tr></thead><tbody>';
    shown.forEach(c => {
      const id = "C-" + c.symbol + "-" + (c.as_of || "").slice(0, 10);
      html +=
        '<tr data-cid="' + esc(id) + '" data-symbol="' + esc(c.symbol) + '">' +
          '<td>' + esc(c.symbol) + '<br><small>' + esc(c.name || "") + '</small></td>' +
          '<td class="sv-num">' + fmtNum(c.edge_score, 1) + '</td>' +
          '<td>' + esc(c.direction_hint ? code("direction", c.direction_hint) : "—") + '</td>' +
          '<td class="sv-num">' + fmtNum(c.stretch, 2) + '</td>' +
          '<td class="sv-num">' + fmtPct(c.vol_context_pct, 2) + '</td>' +
          '<td class="sv-num">' + fmtNum(c.positioning_fuel, 2) + '</td>' +
          '<td>' + esc(c.data_status ? code("data_status", c.data_status) : "") + '</td>' +
          '<td>' +
            '<button class="sv-btn sv-btn-take">' + esc(t("take")) + '</button> ' +
            '<button class="sv-btn sv-btn-skip">' + esc(t("skip")) + '</button>' +
          '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
    el.querySelectorAll('button.sv-btn-take, button.sv-btn-skip').forEach(b => {
      b.addEventListener('click', function(){
        const tr = b.closest('tr');
        if (!tr) return;
        const cid = tr.getAttribute('data-cid');
        const sym = tr.getAttribute('data-symbol');
        const action = b.classList.contains('sv-btn-take') ? 'taken' : 'skipped';
        // Find candidate row (closure-captured list)
        const cand = shown.find(c => ("C-" + c.symbol + "-" + (c.as_of || "").slice(0,10)) === cid);
        if (!cand) return;
        addEntry({
          id: cid,
          mode: 'B',
          action: action,
          symbol: sym,
          direction: cand.direction_hint || null,
          predicted_prob: (cand.edge_score != null) ? cand.edge_score / 100 : null,
          entry_date: (cand.as_of || '').slice(0, 10),
          stretch: cand.stretch,
          vol_pct: cand.vol_context_pct,
          outcome: null,
          realized_pct: null,
        });
        tr.classList.add(action === 'taken' ? 'sv-row-taken' : 'sv-row-skipped');
        renderLogAndAggregates();
      });
    });
  }

  // ── Mode A positions ---------------------------------------------
  function renderModeA(list){
    const el = document.getElementById("sv-mode-a");
    if (!el) return;
    if (!Array.isArray(list) || !list.length) {
      el.innerHTML = '<div class="sv-card-hd">' + esc(t("mode_a")) + '</div><div class="sv-empty">—</div>';
      return;
    }
    let html = '<div class="sv-card-hd">' + esc(t("mode_a")) + ' (' + list.length + ')</div>' +
      '<table class="sv-table"><thead><tr>' +
        ths(["symbol", "dir", "size_pct", "tp", "sl", "pattern", "edge"]) +
      '</tr></thead><tbody>';
    list.forEach(p => {
      html +=
        '<tr>' +
          '<td>' + esc(p.symbol) + '<br><small>' + esc(p.name || "") + '</small></td>' +
          '<td>' + esc(code("direction", p.direction)) + '</td>' +
          '<td class="sv-num">' + fmtPct(p.size_pct, 3) + '</td>' +
          '<td class="sv-num sv-pos">' + fmtPct(p.exit && p.exit.take_profit_pct, 2) + '</td>' +
          '<td class="sv-num sv-neg">' + fmtPct(p.exit && p.exit.stop_loss_pct, 2) + '</td>' +
          '<td>' + esc(patternLabel(p.pattern && p.pattern.regime, p.pattern && p.pattern.distortion)) + '</td>' +
          '<td class="sv-num">' + fmtNum(p.entry_edge_score, 0) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  // ── Pattern table -----------------------------------------------
  function renderPatternTable(pt){
    const el = document.getElementById("sv-pattern");
    if (!el) return;
    if (!pt || !Object.keys(pt).length) {
      el.innerHTML = '<div class="sv-empty">—</div>';
      return;
    }
    let html = '<div class="sv-card-hd">' + esc(t("pattern_table")) + '</div>' +
      '<table class="sv-table"><thead><tr>' +
        ths(["pattern", "tp_pct", "sl_fixed"]) +
      '</tr></thead><tbody>';
    Object.keys(pt).forEach(k => {
      const c = pt[k];
      html +=
        '<tr>' +
          '<td>' + esc(patternLabel(k.split("|")[0], k.split("|")[1])) + '</td>' +
          '<td class="sv-num sv-pos">' + fmtPct(c.take_profit_pct, 2) + '</td>' +
          '<td class="sv-num sv-neg sv-fixed">' + fmtPct(c.stop_loss_pct, 2) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table><div class="sv-card-src">' + esc(t("sl_fixed_note")) + '</div>';
    el.innerHTML = html;
  }

  // ── Bankruptcy heatmap ------------------------------------------
  function renderBankruptcy(bs){
    const el = document.getElementById("sv-bankruptcy");
    if (!el || !bs) return;
    const grid = bs.risk_grid || [];
    let html = '<div class="sv-card-hd">' + esc(t("bankruptcy")) + '</div>' +
      '<table class="sv-table"><thead><tr>' +
        ths(["risk_pct", "ror_mc", "ror_kf"]) +
      '</tr></thead><tbody>';
    grid.forEach(g => {
      const ror = g.ror_mc;
      const cls = ror >= 0.5 ? 'sv-ror-hi' : ror >= 0.1 ? 'sv-ror-md' : 'sv-ror-lo';
      html +=
        '<tr>' +
          '<td class="sv-num">' + fmtPct(g.risk_pct, 3) + '</td>' +
          '<td class="sv-num ' + cls + '">' + fmtNum(ror, 3) + '</td>' +
          '<td class="sv-num">' + fmtNum(g.ror_kaufman, 3) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>' +
      '<div class="sv-card-src">' +
        esc(t("mc_params", { trades: I18.fmtNum(bs.trades, 0), runs: I18.fmtNum(bs.runs, 0), p: bs.win_prob_used, b: bs.win_loss_ratio_used })) +
      '</div>';
    el.innerHTML = html;
  }

  // ── Local result log + aggregates -------------------------------
  function computeAggregates(arr){
    const taken = arr.filter(e => e.action === 'taken');
    const wins = taken.filter(e => e.outcome === 'win').length;
    const losses = taken.filter(e => e.outcome === 'loss').length;
    const closed = wins + losses;
    const hit_rate = closed > 0 ? wins / closed : null;
    const realized = taken.filter(e => typeof e.realized_pct === 'number');
    const avg_roi = realized.length > 0
      ? realized.reduce((s, e) => s + e.realized_pct, 0) / realized.length
      : null;
    // Brier: predicted_prob - (outcome==win ? 1 : 0)
    const brier_inputs = taken.filter(e =>
      typeof e.predicted_prob === 'number' && (e.outcome === 'win' || e.outcome === 'loss')
    );
    const brier = brier_inputs.length > 0
      ? brier_inputs.reduce((s, e) => s + Math.pow(e.predicted_prob - (e.outcome === 'win' ? 1 : 0), 2), 0)
        / brier_inputs.length
      : null;
    // Pattern win-rate
    const pw = {};
    taken.forEach(e => {
      if (!e.pattern) return;
      const k = e.pattern;
      pw[k] = pw[k] || { wins: 0, losses: 0 };
      if (e.outcome === 'win') pw[k].wins++;
      else if (e.outcome === 'loss') pw[k].losses++;
    });
    const pattern_wr = {};
    Object.keys(pw).forEach(k => {
      const x = pw[k]; const tot = x.wins + x.losses;
      pattern_wr[k] = tot > 0 ? x.wins / tot : null;
    });
    return { count: arr.length, taken: taken.length, wins, losses, closed,
             hit_rate, avg_roi_pct: avg_roi, brier, pattern_wr };
  }

  function renderLogAndAggregates(){
    const arr = loadLog();
    const aggEl = document.getElementById("sv-aggregate");
    if (aggEl) {
      const a = computeAggregates(arr);
      aggEl.innerHTML =
        '<div class="sv-card-hd">' + esc(t("aggregate")) + '</div>' +
        '<div class="sv-card-grid">' +
          '<div><b>' + esc(t("hit_rate")) + '</b><span>' +
            (a.hit_rate != null ? fmtPct(a.hit_rate * 100, 1) : '—') + ' (' + a.closed + ')</span></div>' +
          '<div><b>' + esc(t("roi")) + '</b><span>' +
            (a.avg_roi_pct != null ? fmtPct(a.avg_roi_pct, 2) : '—') + '</span></div>' +
          '<div><b>' + esc(t("brier")) + '</b><span>' +
            (a.brier != null ? fmtNum(a.brier, 3) : '—') + '</span></div>' +
          '<div><b>' + esc(t("log_short")) + '</b><span>' + esc(t("rows_n", { n: I18.fmtNum(a.count, 0) })) + '</span></div>' +
        '</div>';
    }
    const logEl = document.getElementById("sv-log");
    if (logEl) {
      const recent = arr.slice(-12).reverse();
      if (!recent.length) {
        logEl.innerHTML = '<div class="sv-card-hd">' + esc(t("log")) + '</div><div class="sv-empty">—</div>';
        return;
      }
      let html = '<div class="sv-card-hd">' + esc(t("log")) + ' (' + arr.length + ')</div>' +
        '<table class="sv-table"><thead><tr>' +
          ths(["date", "sym", "mode", "act", "p", "out", "roi_pct"]) + '<th></th>' +
        '</tr></thead><tbody>';
      recent.forEach(e => {
        const d = e.entry_date || new Date(e.ts || Date.now()).toISOString().slice(0, 10);
        const outClass = e.outcome === 'win' ? 'sv-pos' : e.outcome === 'loss' ? 'sv-neg' : 'sv-flat';
        html +=
          '<tr data-id="' + esc(e.id || "") + '">' +
            '<td>' + esc(I18.fmtDate(d, "ymd")) + '</td>' +
            '<td>' + esc(e.symbol || '') + '</td>' +
            '<td>' + esc(e.mode || '') + '</td>' +
            '<td>' + esc(e.action ? t("act_" + e.action) : '') + '</td>' +
            '<td class="sv-num">' + (e.predicted_prob != null ? fmtNum(e.predicted_prob, 2) : '—') + '</td>' +
            '<td class="' + outClass + '">' + esc(e.outcome === 'win' ? t("win") : e.outcome === 'loss' ? t("lose") : '—') + '</td>' +
            '<td class="sv-num">' + (e.realized_pct != null ? fmtPct(e.realized_pct, 2) : '—') + '</td>' +
            '<td>' +
              '<button class="sv-mini sv-mini-win">' + esc(t("win_btn")) + '</button> ' +
              '<button class="sv-mini sv-mini-lose">' + esc(t("lose_btn")) + '</button>' +
            '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
      logEl.innerHTML = html;
      logEl.querySelectorAll('button.sv-mini-win, button.sv-mini-lose').forEach(b => {
        b.addEventListener('click', function(){
          const tr = b.closest('tr'); if (!tr) return;
          const id = tr.getAttribute('data-id');
          const isWin = b.classList.contains('sv-mini-win');
          // Realized pct = pattern TP if win, else SL (rough placeholder, user can override later)
          const arr2 = loadLog();
          const item = arr2.find(x => x.id === id);
          let realized = null;
          if (item) {
            // Mode C: also pairs Mode A (machine) result virtually
            const dl = window.DATA && window.DATA.survival_loop;
            const tbl = dl && dl.pattern_table;
            // Use a default 1.5% / -1% if no pattern info
            realized = isWin ? 1.5 : -1.0;
            if (tbl && item.pattern && tbl[item.pattern]) {
              realized = isWin
                ? tbl[item.pattern].take_profit_pct
                : tbl[item.pattern].stop_loss_pct;
            }
          }
          recordOutcome(id, isWin ? 'win' : 'loss', realized);
          renderLogAndAggregates();
        });
      });
    }
  }

  // ── Top-level render ---------------------------------------------
  function renderAll(){
    const D = window.DATA;
    const sl = D && D.survival_loop;
    if (!sl) {
      const root = document.getElementById("survival-pane");
      if (root) root.querySelector(".sv-empty-msg").style.display = "block";
      return;
    }
    const empty = document.querySelector("#survival-pane .sv-empty-msg");
    if (empty) empty.style.display = "none";
    renderRiskGate(sl.risk_gate);
    renderAutoRisk(sl.auto_risk);
    renderCandidates(sl.candidates);
    renderModeA(sl.mode_a_positions);
    renderPatternTable(sl.pattern_table);
    renderBankruptcy(sl.bankruptcy_simulation);
    renderLogAndAggregates();
    // Notes
    const nt = document.getElementById("sv-notes");
    if (nt && Array.isArray(sl.notes)) {
      nt.innerHTML = '<div class="sv-card-hd">' + esc(t("notes")) + '</div>' +
        '<ul>' + sl.notes.map(n => '<li>' + esc(code("survival_note", n)) + '</li>').join('') + '</ul>';
    }
    // Notify panel (Phase 1.6): refresh when survival is rendered.
    if (typeof window.__survivalNotifyRefresh === "function") {
      try { window.__survivalNotifyRefresh(); } catch (e) {}
    }
    // Backtest + backfill panels (Phase 1.7).
    if (typeof window.__survivalBacktestRefresh === "function") {
      try { window.__survivalBacktestRefresh(); } catch (e) {}
    }
    if (typeof window.__survivalBackfillRefresh === "function") {
      try { window.__survivalBackfillRefresh(); } catch (e) {}
    }
    // H1 単独検証パネル (Phase 1.9).
    if (typeof window.__survivalH1Refresh === "function") {
      try { window.__survivalH1Refresh(); } catch (e) {}
    }
  }

  window.__survivalShow = function(){
    const p = document.getElementById("survival-pane");
    if (p) p.style.display = "block";
    const tw = document.querySelector(".tbl-wrap"); if (tw) tw.style.display = "none";
    const tb = document.getElementById("toolbar"); if (tb) tb.style.display = "none";
    const mf = document.getElementById("mf-pane"); if (mf) mf.style.display = "none";
    renderAll();
  };
  window.__survivalHide = function(){
    const p = document.getElementById("survival-pane");
    if (p) p.style.display = "none";
    const tw = document.querySelector(".tbl-wrap"); if (tw) tw.style.display = "";
    const tb = document.getElementById("toolbar"); if (tb) tb.style.display = "";
  };
  window.__survivalRefresh = renderAll;
  // 表の見出し（辞書キー sv.th_*）
  function ths(keys){ return keys.map(k => '<th>' + esc(t("th_" + k)) + '</th>').join(''); }
})();
