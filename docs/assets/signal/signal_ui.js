/* assets/signal/signal_ui.js — 株式タブのチャート判定・検証・詳細チャート（DATA_CONTRACT §21）。
 *
 * - 判定の列（chart_signal）と、その横に必ず検証結果（verify.json: 20営業日後の中央値・上昇割合・件数 vs 基準）
 * - 売り系には「空売りの根拠なし。新しく買わない・利益を確定する目安」
 * - 日経225 の 理論株価・割安度・総合判定 は「Mac mini のローカル版のみ」（公開版では値を持たない）
 * - Nasdaq 100 タブの上に「米国の買い判定一覧」（Dow/NDX/S&P の和集合）
 * - 「検証」タブ（verify.json）、「根拠が弱まっています」バナー、上部の「データが○時間前のまま」
 * - 銘柄詳細チャート（終値・BB48/BB288 ±2σ/±3σ・▲買い/▼売り、下段 CCI48/CCI288 と ±100・0）
 * 計算はしない（値は data.json / charts/{tab}.json / verify.json を読むだけ）。
 */
(function () {
  "use strict";
  const BUY = ["強い買い", "買い", "買い（長期の売られすぎ）"];
  const SELL = ["売り", "強い売り"];
  const SELL_NOTE = "空売りの根拠なし。新しく買わない・利益を確定する目安";
  const LOGIN_ONLY = "Mac mini のローカル版のみ";
  const US_TABS = ["dow30", "nasdaq100", "sp500"];
  const EQ_TABS = ["nikkei225"].concat(US_TABS);
  const C_BLUE = "#3b82f6", C_ORANGE = "#f97316";
  const S = { verify: null, state: "loading" };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const pct = (v, d = 1) => (num(v) == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(d) + "%");

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
  #us-buy-list{display:none;padding:8px 16px 4px}
  #us-buy-list h3{font-size:13px;margin:4px 0 6px;color:var(--text)}
  #us-buy-list table{width:100%;border-collapse:collapse;font-size:12px}
  #us-buy-list th,#us-buy-list td{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
  #us-buy-list .ub-empty{color:var(--text-faint);font-size:12px;padding:6px 0}
  #verify-pane{display:none;padding:12px 16px}
  #verify-pane h2{font-size:15px;margin:4px 0 8px} #verify-pane h3{font-size:13px;margin:14px 0 6px}
  #verify-pane table{border-collapse:collapse;font-size:12px;min-width:560px}
  #verify-pane th,#verify-pane td{padding:4px 8px;border-bottom:1px solid var(--border);text-align:right}
  #verify-pane th:first-child,#verify-pane td:first-child{text-align:left}
  #verify-pane .vf-meta{font-size:12px;color:var(--text-dim);line-height:1.6}
  #verify-pane .vf-weak{color:#e5a23d;font-weight:700}
  .dt-chart:has(.sg-chart){max-width:min(1100px,100%)}
  .sg-chart{background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:4px;width:min(1100px,92vw)}
  .sg-chart svg{width:100%;height:auto;display:block}
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
  function statsFor(tab, label, kind = "chart") {
    const m = S.verify && S.verify.markets && S.verify.markets[mkt(tab)];
    if (!m || !m.full) return null;
    return { sig: (m.full[kind] || {})[label] || null, base: m.full.base || null };
  }
  function vsText(tab, label) {
    if (S.state === "loading") return "検証: 読み込み中…";
    if (S.state !== "ok") return "検証データなし（verify.json を読めません）";
    const st = statsFor(tab, label);
    if (!st || !st.base) return "検証データなし";
    const b = st.base;
    const baseT = `基準 中央値 ${pct(b.median)}・上昇 ${b.up_pct == null ? "—" : b.up_pct + "%"}`;
    if (!label || label === "様子見" || !st.sig) return `20日後 ${baseT}`;
    const s = st.sig;
    if (!s.n) return `20日後: この判定の過去例 0件（${baseT}）`;
    return `20日後 中央値 <b>${pct(s.median)}</b>・上昇 <b>${s.up_pct}%</b>・${s.n}件（${baseT}）`;
  }
  function labCls(l) {
    return l === "強い買い" ? "js-sbuy" : l === "買い" ? "js-buy" : l === "買い（長期の売られすぎ）" ? "js-lo"
      : l === "強い売り" ? "js-ssell" : l === "売り" ? "js-sell" : "js-wait";
  }
  function judgeCell(r, tab) {
    const l = r.chart_signal;
    if (!l) return `<div class="js-cell"><span class="js-lab js-wait">判定なし</span><span class="js-vs">${esc(r.chart_signal_note || "日足が足りません")}</span></div>`;
    const note = SELL.includes(l) ? `<span class="js-note">${SELL_NOTE}</span>` : "";
    return `<div class="js-cell"><span class="js-lab ${labCls(l)}">${esc(l)}</span><span class="js-vs">${vsText(tab, l)}</span>${note}</div>`;
  }

  // ── 列 ──
  const C_SIG = [
    { k: "chart_signal_code", l: "判定（チャート）＋検証", a: "left", w: 300 },
  ];
  const C_IND = [
    { k: "cci288", l: "CCI288", a: "right", w: 66 },
    { k: "cci48", l: "CCI48", a: "right", w: 62 },
    { k: "bb48_z", l: "BB48 z", a: "right", w: 62 },
    { k: "bb288_z", l: "BB288 z", a: "right", w: 66 },
  ];
  const C_US = [
    { k: "magic_rank", l: "魔法の公式順位", a: "right", w: 90 },
    { k: "f_score", l: "F", a: "center", w: 52 },
  ];
  const C_JP = [
    { k: "__theory_price", l: "理論株価", a: "center", w: 92 },
    { k: "__value_gap", l: "割安度", a: "center", w: 92 },
    { k: "__overall", l: "総合判定", a: "center", w: 92 },
  ];
  function cols(tab, base) {
    if (!EQ_TABS.includes(tab)) return base;
    const head = base.slice(0, 2), rest = base.slice(2);   // Signal / Score はそのまま先頭
    return head.concat(C_SIG, rest, C_IND, tab === "nikkei225" ? C_JP : C_US);
  }
  function cell(c, r, tab) {
    switch (c.k) {
      case "chart_signal_code": return judgeCell(r, tab);
      case "cci288": case "cci48": {
        const v = num(r[c.k]); if (v == null) return `<span style="color:var(--text-faint)">—</span>`;
        const co = v >= 100 ? "var(--green)" : v <= -100 ? "var(--red)" : "var(--text-dim)";
        return `<span style="color:${co}">${v > 0 ? "+" : ""}${v.toFixed(0)}</span>`;
      }
      case "bb48_z": case "bb288_z": {
        const v = num(r[c.k]); if (v == null) return `<span style="color:var(--text-faint)">—</span>`;
        const co = v <= -2 ? "var(--green)" : v >= 2 ? "var(--red)" : "var(--text-dim)";
        return `<span style="color:${co}">${v > 0 ? "+" : ""}${v.toFixed(2)}σ</span>`;
      }
      case "magic_rank": return num(r.magic_rank) == null ? `<span style="color:var(--text-faint)">—</span>` : `${r.magic_rank}位`;
      case "f_score": return num(r.f_score) == null ? `<span style="color:var(--text-faint)">—</span>` : `${r.f_score}/${r.f_max}`;
      case "__theory_price": case "__value_gap": case "__overall": return `<span class="login-only">${LOGIN_ONLY}</span>`;
    }
    return null;
  }

  // ── 米国の買い判定一覧（Nasdaq 100 タブの上） ──
  function renderUsBuyList(tab, DATA) {
    const el = document.getElementById("us-buy-list"); if (!el) return;
    if (tab !== "nasdaq100") { el.style.display = "none"; return; }
    const seen = {}, rows = [];
    US_TABS.forEach((t) => ((DATA.markets || {})[t] || []).forEach((r) => {
      if (!r || String(r.symbol || "").startsWith("^") || !BUY.includes(r.chart_signal)) return;
      if (!seen[r.symbol]) { seen[r.symbol] = { r, idx: [] }; rows.push(seen[r.symbol]); }
      seen[r.symbol].idx.push({ dow30: "Dow", nasdaq100: "NDX", sp500: "S&P" }[t]);
    }));
    const order = { "強い買い": 0, "買い": 1, "買い（長期の売られすぎ）": 2 };
    rows.sort((a, b) => (order[a.r.chart_signal] - order[b.r.chart_signal]) || ((a.r.bb48_z ?? 0) - (b.r.bb48_z ?? 0)));
    el.style.display = "block";
    const body = rows.map(({ r, idx }) => `<tr><td>${judgeCell(r, "us")}</td><td><b>${esc(r.symbol)}</b></td><td>${esc(r.name || "")}</td>`
      + `<td>${esc(idx.join("・"))}</td><td style="text-align:right">${num(r.price) == null ? "—" : r.price}</td>`
      + `<td style="text-align:right">${cell({ k: "cci288" }, r)}</td><td style="text-align:right">${cell({ k: "bb48_z" }, r)}</td>`
      + `<td style="text-align:right">${cell({ k: "magic_rank" }, r)}</td><td style="text-align:center">${cell({ k: "f_score" }, r)}</td></tr>`).join("");
    el.innerHTML = `<h3>米国の買い判定一覧（Dow 30・Nasdaq 100・S&amp;P 500 の和集合・${rows.length}銘柄）</h3>`
      + (rows.length ? `<table><thead><tr><th>判定＋検証（20営業日後）</th><th>Symbol</th><th>Name</th><th>指数</th><th>Price</th><th>CCI288</th><th>BB48 z</th><th>魔法の公式</th><th>F</th></tr></thead><tbody>${body}</tbody></table>`
        : `<div class="ub-empty">今日は買い系の判定（強い買い・買い・買い（長期の売られすぎ））の銘柄がありません。</div>`);
  }

  // ── バナー ──
  function renderStaleBanner(DATA) {
    const el = document.getElementById("stale-banner"); if (!el || !DATA || !DATA.meta) return;
    const t = Date.parse(DATA.meta.updated_at || "");
    const lim = num(DATA.meta.stale_hours) || 48;          // tools/gate_thresholds.STALE_HOURS と同じ値
    if (!isFinite(t)) { el.style.display = "block"; el.textContent = "⚠ データの更新時刻が読めません"; return; }
    const h = (Date.now() - t) / 36e5;
    if (h <= lim) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.textContent = `⚠ データが${Math.floor(h)}時間前のまま（${lim}時間を超えて更新されていません・最終更新 ${DATA.meta.updated_at_str || DATA.meta.updated_at}）`;
  }
  function renderWeakBanner(t) {
    const el = document.getElementById("weak-banner"); if (!el) return;
    const v = S.verify;
    if (!v || v.weakened !== true || !(EQ_TABS.includes(t) || t === "verify")) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.innerHTML = `<span class="wb">⚠ 根拠が弱まっています — 直近6か月、次の判定の後の値動き（20営業日後の中央値）が基準を下回りました: ${esc((v.weakened_items || []).join("、"))}（「検証」タブで詳細）</span>`;
  }

  // ── 検証タブ ──
  function vrow(name, s, base) {
    if (!s) return `<tr><td>${esc(name)}</td><td colspan="5" style="text-align:left;color:var(--text-faint)">—</td></tr>`;
    const diff = num(s.median) != null && base && num(base.median) != null ? s.median - base.median : null;
    return `<tr><td>${esc(name)}</td><td>${s.n}</td><td>${pct(s.median, 2)}</td><td>${pct(s.mean, 2)}</td><td>${s.up_pct == null ? "—" : s.up_pct + "%"}</td>`
      + `<td>${diff == null ? "—" : (diff > 0 ? "+" : "") + diff.toFixed(2) + "pt"}</td></tr>`;
  }
  function vtable(part, weak) {
    if (!part) return "<p>—</p>";
    const b = part.base;
    const head = `<tr><th>判定</th><th>件数</th><th>中央値</th><th>平均</th><th>上昇割合</th><th>基準との差（中央値）</th></tr>`;
    const w = (k) => (weak && weak[k] === true ? ' <span class="vf-weak">⚠ 弱まり</span>' : "");
    const chart = BUY.concat(SELL).map((l) => vrow(l + (SELL.includes(l) ? "（※）" : ""), (part.chart || {})[l], b).replace("</td>", w("chart:" + l) + "</td>")).join("");
    const comp = ["STRONG BUY", "BUY", "HOLD", "WATCH", "AVOID"].filter((l) => (part.composite || {})[l])
      .map((l) => vrow("既存 " + l, part.composite[l], b).replace("</td>", w("composite:" + l) + "</td>")).join("");
    return `<table><thead>${head}</thead><tbody>${vrow("基準（全営業日）", b, b)}${chart}${comp}</tbody></table>`;
  }
  function renderVerify() {
    const p = document.getElementById("verify-pane"); if (!p) return;
    const v = S.verify;
    if (S.state === "loading") { p.innerHTML = "<p>verify.json を読み込み中…</p>"; return; }
    if (!v) { p.innerHTML = `<h2>検証</h2><p>verify.json を読めませんでした（毎日の更新で作られます）。</p>`; return; }
    const m = v.method || {};
    let h = `<h2>検証 — 判定の後、${m.horizon_days || 20}営業日でどう動いたか</h2>
      <div class="vf-meta">検証日（データの最終日）: <b>${esc(v.as_of || "—")}</b>　作成: ${esc(String(v.generated_at || "").slice(0, 16).replace("T", " "))}<br>
      方法: 判定が出た日の終値から${m.horizon_days || 20}営業日後の騰落率。同じ銘柄の連続した判定は${m.gap_days || 20}日に1回だけ数える。基準 = ${esc(m.base || "")}。
      指標が揃うまでの${m.warmup_bars || 288}本は数えない。価格: ${esc(m.price_source || "")}。<br>
      ※ 売り系: ${SELL_NOTE}。<br>${esc(m.note || "")}</div>`;
    Object.entries(v.markets || {}).forEach(([k, mk]) => {
      h += `<h3>${esc(mk.label || k)}（${mk.symbols}銘柄・最終日 ${esc(mk.last_date || "—")}）</h3>`;
      h += `<div class="vf-meta">全期間</div>` + vtable(mk.full, null);
      h += `<div class="vf-meta" style="margin-top:6px">直近6か月（${esc((mk.recent6m || {}).since || "")} 以降）— 弱まりの判定に使う</div>` + vtable(mk.recent6m, mk.weakened);
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

  // ── 銘柄詳細チャート ──
  function chartHTML(series) {
    const s = series || {}; const close = s.close || []; const n = close.length;
    if (n < 2) return "";
    const W = 640, PH = 210, CH = 110, G = 14, L = 4, R = 4;
    const X = (i) => L + (i / (n - 1)) * (W - L - R);
    const b48 = s.bb48 || {}, b288 = s.bb288 || {};
    const ys = [];
    [close, b48.p3, b48.m3, b288.p2, b288.m2].forEach((a) => (a || []).forEach((v) => { if (num(v) != null) ys.push(v); }));
    let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    const Y = (v) => 6 + (1 - (v - lo) / (hi - lo)) * (PH - 12);
    const poly = (a, Yf) => { let out = "", seg = []; (a || []).forEach((v, i) => { if (num(v) == null) { if (seg.length > 1) out += seg.join(" ") + "|"; seg = []; } else seg.push(X(i).toFixed(1) + "," + Yf(v).toFixed(1)); }); if (seg.length > 1) out += seg.join(" "); return out.split("|").filter(Boolean); };
    const line = (a, Yf, col, w, dash, clip) => poly(a, Yf).map((pts) => `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="${w}"${dash ? ` stroke-dasharray="${dash}"` : ""} clip-path="url(#${clip})"/>`).join("");
    let svg = `<svg viewBox="0 0 ${W} ${PH + G + CH}" role="img" aria-label="終値とボリンジャーバンド48/288、CCI48/288">`
      + `<defs><clipPath id="sgcp"><rect x="0" y="0" width="${W}" height="${PH}"/></clipPath><clipPath id="sgcc"><rect x="0" y="${PH + G}" width="${W}" height="${CH}"/></clipPath></defs>`
      + `<rect x="0" y="0" width="${W}" height="${PH}" fill="none" stroke="var(--border)"/>`;
    svg += line(b288.p3, Y, C_ORANGE, 1, "1.5 2.5", "sgcp") + line(b288.m3, Y, C_ORANGE, 1, "1.5 2.5", "sgcp");
    svg += line(b288.p2, Y, C_ORANGE, 1.2, "", "sgcp") + line(b288.m2, Y, C_ORANGE, 1.2, "", "sgcp");
    svg += line(b48.p3, Y, C_BLUE, 1, "1.5 2.5", "sgcp") + line(b48.m3, Y, C_BLUE, 1, "1.5 2.5", "sgcp");
    svg += line(b48.p2, Y, C_BLUE, 1.2, "", "sgcp") + line(b48.m2, Y, C_BLUE, 1.2, "", "sgcp");
    svg += line(close, Y, "var(--text)", 1.6, "", "sgcp");
    (s.marks || []).forEach((m) => {
      const v = num(close[m.i]); if (v == null) return;
      const x = X(m.i).toFixed(1);
      if (m.type === "sell") svg += `<text x="${x}" y="${(Y(v) - 6).toFixed(1)}" text-anchor="middle" font-size="11" fill="#dc2626">▼</text>`;
      else svg += `<text x="${x}" y="${(Y(v) + 14).toFixed(1)}" text-anchor="middle" font-size="11" fill="${m.type === "long_oversold" ? "#0d9488" : "#16a34a"}">▲</text>`;
    });
    // 下段 CCI
    const cv = []; [s.cci48, s.cci288].forEach((a) => (a || []).forEach((v) => { if (num(v) != null) cv.push(Math.abs(v)); }));
    const cap = Math.max(200, Math.ceil(Math.max(0, ...cv) / 50) * 50);
    const top = PH + G, YC = (v) => top + 4 + (1 - (Math.max(-cap, Math.min(cap, v)) + cap) / (2 * cap)) * (CH - 8);
    svg += `<rect x="0" y="${top}" width="${W}" height="${CH}" fill="none" stroke="var(--border)"/>`;
    [[100, "3 3"], [-100, "3 3"], [0, ""]].forEach(([g, d]) => {
      svg += `<line x1="${L}" x2="${W - R}" y1="${YC(g).toFixed(1)}" y2="${YC(g).toFixed(1)}" stroke="var(--text-faint)" stroke-width="0.8"${d ? ` stroke-dasharray="${d}"` : ""}/>`
        + `<text x="${W - R - 2}" y="${(YC(g) - 2).toFixed(1)}" text-anchor="end" font-size="9" fill="var(--text-faint)">${g > 0 ? "+" : ""}${g}</text>`;
    });
    svg += line(s.cci288, YC, C_ORANGE, 1.3, "", "sgcc") + line(s.cci48, YC, C_BLUE, 1.3, "", "sgcc");
    svg += `</svg>`;
    const leg = `<div class="sg-leg"><span><i style="border-color:var(--text)"></i>終値</span>`
      + `<span><i style="border-color:${C_BLUE}"></i>BB48 ±2σ</span><span><i class="dot" style="border-color:${C_BLUE}"></i>BB48 ±3σ</span>`
      + `<span><i style="border-color:${C_ORANGE}"></i>BB288 ±2σ</span><span><i class="dot" style="border-color:${C_ORANGE}"></i>BB288 ±3σ</span>`
      + `<span style="color:#16a34a">▲ 買い</span><span style="color:#0d9488">▲ 買い（長期の売られすぎ）</span><span style="color:#dc2626">▼ 売り</span>`
      + `<span>｜下段: <i style="border-color:${C_BLUE}"></i>CCI48 <i style="border-color:${C_ORANGE}"></i>CCI288（±100・0 の線）</span></div>`;
    return `<div class="sg-chart">${svg}${leg}<div class="dt-cap">チャート判定: 買い = CCI288&gt;0 かつ 終値≦BB48−2σ かつ CCI48&lt;−100（−3σ で強い買い）。売り = その逆。▼売りは ${SELL_NOTE}。過去の値動きの表示であり、売買の推奨ではありません。</div></div>`;
  }

  window.SIG = { loadVerify, cols, cell, judgeCell, renderUsBuyList, renderStaleBanner, renderWeakBanner,
    showVerify, hideVerify, chartHTML, EQ_TABS, BUY, SELL, SELL_NOTE, state: S };
})();
