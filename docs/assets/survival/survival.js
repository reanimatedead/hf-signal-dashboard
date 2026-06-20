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

  // ── i18n minimal --------------------------------------------------
  const I18N = {
    ja: {
      risk_gate: "本日の一文",
      reasons: "根拠",
      auto_risk: "自動リスク (人間入力ゼロ)",
      per_trade: "1トレード許容",
      max_concurrent: "同時保有上限",
      dd_shrink: "DD 縮小",
      dd_stop: "DD 全停止",
      candidates: "妙味候補",
      mode_a: "Mode A 仮想エントリ (機械)",
      pattern_table: "パターン別利確テーブル",
      take: "採用",
      skip: "見送り",
      log: "結果ログ (ローカルのみ)",
      aggregate: "集計 (直近)",
      hit_rate: "的中率",
      roi: "平均 ROI",
      brier: "Brier",
      pattern_wr: "パターン別 勝率",
      bankruptcy: "破産確率ヒートマップ (MC)",
      ror_mc: "RoR (MC)",
      ror_kf: "RoR (Kaufman)",
      notes: "Phase 1 注意事項",
      disc: "Macro environment visualization / not investment advice",
      no_data: "—",
      win: "勝", lose: "負", flat: "見送り",
      win_btn: "勝", lose_btn: "負",
    },
    en: {
      risk_gate: "Today's verdict",
      reasons: "Reasons",
      auto_risk: "Auto risk (zero human input)",
      per_trade: "Per-trade risk",
      max_concurrent: "Max concurrent",
      dd_shrink: "DD shrink",
      dd_stop: "DD stop",
      candidates: "Edge candidates",
      mode_a: "Mode A virtual entries (machine)",
      pattern_table: "Pattern exit table",
      take: "Take",
      skip: "Skip",
      log: "Result log (local only)",
      aggregate: "Recent aggregates",
      hit_rate: "Hit rate",
      roi: "Avg ROI",
      brier: "Brier",
      pattern_wr: "Pattern win-rate",
      bankruptcy: "Bankruptcy heatmap (MC)",
      ror_mc: "RoR (MC)",
      ror_kf: "RoR (Kaufman)",
      notes: "Phase 1 caveats",
      disc: "Macro environment visualization / not investment advice",
      no_data: "—",
      win: "win", lose: "loss", flat: "skip",
      win_btn: "win", lose_btn: "loss",
    },
  };
  function curLang(){
    let l = localStorage.getItem("hf_lang") || "ja";
    return I18N[l] ? l : "ja";
  }
  function t(k){ return (I18N[curLang()] && I18N[curLang()][k]) || k; }

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
    return Number(v).toFixed(d != null ? d : 2) + "%";
  }
  function fmtNum(v, d){
    if (v === null || v === undefined || !Number.isFinite(+v)) return t("no_data");
    return Number(v).toFixed(d != null ? d : 2);
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
    const label = (rg.label || "neutral").toUpperCase();
    const reasons = (rg.reasons || []).slice(0, 4).map(esc).join(" · ") || "—";
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
        '<div><b>target vol</b><span>' + fmtPct(ar.target_vol_pct, 2) + '</span></div>' +
        '<div><b>realized vol</b><span>' + fmtPct(ar.realized_vol_pct, 2) + '</span></div>' +
      '</div>' +
      '<div class="sv-card-src">' + esc(ar.source || "") + '</div>';
  }

  // ── Candidates table ---------------------------------------------
  function renderCandidates(list){
    const el = document.getElementById("sv-candidates");
    if (!el) return;
    if (!Array.isArray(list) || !list.length) {
      el.innerHTML = '<div class="sv-empty">No candidates today.</div>';
      return;
    }
    const shown = list.slice(0, 8);
    let html =
      '<div class="sv-card-hd">' + esc(t("candidates")) + ' (' + shown.length + ')</div>' +
      '<table class="sv-table"><thead><tr>' +
        '<th>Symbol</th><th>Edge</th><th>Dir</th><th>Stretch</th><th>Vol%</th><th>PF</th><th>Status</th><th></th>' +
      '</tr></thead><tbody>';
    shown.forEach(c => {
      const id = "C-" + c.symbol + "-" + (c.as_of || "").slice(0, 10);
      html +=
        '<tr data-cid="' + esc(id) + '" data-symbol="' + esc(c.symbol) + '">' +
          '<td>' + esc(c.symbol) + '<br><small>' + esc(c.name || "") + '</small></td>' +
          '<td class="sv-num">' + fmtNum(c.edge_score, 1) + '</td>' +
          '<td>' + esc(c.direction_hint || "—") + '</td>' +
          '<td class="sv-num">' + fmtNum(c.stretch, 2) + '</td>' +
          '<td class="sv-num">' + fmtPct(c.vol_context_pct, 2) + '</td>' +
          '<td class="sv-num">' + fmtNum(c.positioning_fuel, 2) + '</td>' +
          '<td>' + esc(c.data_status || "") + '</td>' +
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
        '<th>Symbol</th><th>Dir</th><th>Size%</th><th>TP</th><th>SL</th><th>Pattern</th><th>Edge</th>' +
      '</tr></thead><tbody>';
    list.forEach(p => {
      html +=
        '<tr>' +
          '<td>' + esc(p.symbol) + '<br><small>' + esc(p.name || "") + '</small></td>' +
          '<td>' + esc(p.direction) + '</td>' +
          '<td class="sv-num">' + fmtPct(p.size_pct, 3) + '</td>' +
          '<td class="sv-num sv-pos">' + fmtPct(p.exit && p.exit.take_profit_pct, 2) + '</td>' +
          '<td class="sv-num sv-neg">' + fmtPct(p.exit && p.exit.stop_loss_pct, 2) + '</td>' +
          '<td>' + esc((p.pattern && p.pattern.regime) || '—') + ' / ' +
                   esc((p.pattern && p.pattern.distortion) || '—') + '</td>' +
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
        '<th>Pattern</th><th>TP %</th><th>SL % (fixed)</th>' +
      '</tr></thead><tbody>';
    Object.keys(pt).forEach(k => {
      const c = pt[k];
      html +=
        '<tr>' +
          '<td>' + esc(k) + '</td>' +
          '<td class="sv-num sv-pos">' + fmtPct(c.take_profit_pct, 2) + '</td>' +
          '<td class="sv-num sv-neg sv-fixed">' + fmtPct(c.stop_loss_pct, 2) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table><div class="sv-card-src">SL は固定 (Phase 1 設計、daily_update で更新されない)。</div>';
    el.innerHTML = html;
  }

  // ── Bankruptcy heatmap ------------------------------------------
  function renderBankruptcy(bs){
    const el = document.getElementById("sv-bankruptcy");
    if (!el || !bs) return;
    const grid = bs.risk_grid || [];
    let html = '<div class="sv-card-hd">' + esc(t("bankruptcy")) + '</div>' +
      '<table class="sv-table"><thead><tr>' +
        '<th>Risk %</th><th>' + esc(t("ror_mc")) + '</th><th>' + esc(t("ror_kf")) + '</th>' +
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
        'trades=' + esc(bs.trades) + ' runs=' + esc(bs.runs) +
        ' · p=' + esc(bs.win_prob_used) + ' b=' + esc(bs.win_loss_ratio_used) +
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
          '<div><b>log</b><span>' + a.count + ' rows</span></div>' +
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
          '<th>date</th><th>sym</th><th>mode</th><th>act</th><th>p</th><th>out</th><th>roi%</th><th></th>' +
        '</tr></thead><tbody>';
      recent.forEach(e => {
        const d = e.entry_date || new Date(e.ts || Date.now()).toISOString().slice(0, 10);
        const outClass = e.outcome === 'win' ? 'sv-pos' : e.outcome === 'loss' ? 'sv-neg' : 'sv-flat';
        html +=
          '<tr data-id="' + esc(e.id || "") + '">' +
            '<td>' + esc(d) + '</td>' +
            '<td>' + esc(e.symbol || '') + '</td>' +
            '<td>' + esc(e.mode || '') + '</td>' +
            '<td>' + esc(e.action || '') + '</td>' +
            '<td class="sv-num">' + (e.predicted_prob != null ? fmtNum(e.predicted_prob, 2) : '—') + '</td>' +
            '<td class="' + outClass + '">' + esc(e.outcome || '—') + '</td>' +
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
        '<ul>' + sl.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul>';
    }
    // Notify panel (Phase 1.6): refresh when survival is rendered.
    if (typeof window.__survivalNotifyRefresh === "function") {
      try { window.__survivalNotifyRefresh(); } catch (e) {}
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
})();
