// tools/preview_screens.mjs — サイトを Playwright で撮る（全タブ + 銘柄詳細 7735.T・FX 1 本）× ja/en × 幅。
// 使い方:
//   node tools/preview_screens.mjs http://127.0.0.1:8765 OUT_DIR [--offline] [--langs ja,en] [--widths 1280,390]
//   出力: OUT_DIR/{lang}_{width}_{name}.png と OUT_DIR/console_report.json
// --offline: 架空データのプレビュー用。外部ホスト（Google Fonts / macro-fx-base）へは出ず、空の応答で代替する
//            （サンドボックスや CI のプレビューから外へ出られないため。代替した URL は report.stubbed に残す）。
// ブラウザのコンソールエラー（console.error）と pageerror（未捕捉の例外）が 1 件でもあれば exit 1。
// 訳し漏れ: 各タブ・各詳細で「見えている文字」(innerText) に snake_case（英小文字_英小文字 の形）が
// 残っていたら type=snake のエラーにする（data.json のコードが辞書を通らずそのまま出ている印）。
import { createRequire } from "module";
import fs from "fs";
import path from "path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const base = (args[0] && !args[0].startsWith("--") ? args[0] : "http://127.0.0.1:8765").replace(/\/$/, "");
const out = args[1] && !args[1].startsWith("--") ? args[1] : "preview";
const offline = args.includes("--offline");
// --warn-only: 公開後の確認用（deploy.yml full）。見つかったものは ::warning:: として出し、常に exit 0（公開は止めない）。
const warnOnly = args.includes("--warn-only");
const langs = opt("--langs", "ja,en").split(",");
const widths = opt("--widths", "1280,390").split(",").map(Number);
const TABS = ["survival", "nikkei225", "dow30", "nasdaq100", "sp500", "fx", "rates_vol", "pos_val", "relations", "moneyflow", "verify"];
const JP_SYMBOL = "7735.T";
fs.mkdirSync(out, { recursive: true });

const origin = new URL(base).origin;
const report = { base, offline, errors: [], stubbed: [], shots: [] };
const browser = await chromium.launch();
// snake_case: 英小文字/数字の語が _ でつながった形（例 high_vol, n_symbols）。URL・ファイル名は innerText に出ない前提。
// 2026-11: 点でつながった ID（real_yield.10y / fx_rate_corr.usdeur.2y.30d / yield_curve.slope.10y_2y）も 1 語として捕まえる。
// ファイル名（*.json など）は除く。
const SNAKE = /(?<![A-Za-z0-9_.\/-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\.[a-z0-9_]+)*(?![A-Za-z0-9_\/-])/g;
const FILE_EXT = /\.(json|jsonl|js|csv|html|png|xlsx)$/;
async function scanSnake(page, tag, where, root) {
  const text = await page.evaluate((sel) => {
    const el = sel ? document.querySelector(sel) : document.body;
    return el ? el.innerText : "";
  }, root || null);
  const hits = [...new Set((text.match(SNAKE) || []).filter((h) => !FILE_EXT.test(h)))];
  if (hits.length) report.errors.push({ tag, type: "snake", text: `${where}: ${hits.join(", ")}` });
}

function macroFxStub() {
  const ids = ["yield_curve.slope.10y_2y", "yield_curve.slope.10y_3m", "yield_curve.slope.30y_5y",
    "real_yield.1y", "real_yield.2y", "real_yield.5y", "real_yield.10y", "real_yield.30y",
    "fx_rate_corr.usdeur.2y.30d", "fx_rate_corr.usdeur.10y.30d", "fx_rate_corr.jpyeur.2y.30d",
    "fx_rate_corr.jpyeur.10y.30d", "fx_rate_corr.gbpeur.2y.30d", "fx_rate_corr.gbpeur.10y.30d"];
  const fam = (id) => (id.startsWith("yield_curve") ? "slope" : id.startsWith("real_yield") ? "real_yield" : "fx_corr");
  const meta = {}, series = {};
  const d = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
  for (const id of ids) {
    meta[id] = { family: fam(id), label_ja: "架空の指標" };              // label_en は付けない（本番と同じ）。名前に ID を入れない
    series[id] = [{ observed_at: d(2), value: 0.5 }, { observed_at: d(1), value: 0.6 }];
  }
  return { meta, series, interpretations: {} };
}

async function stub(route) {
  const url = route.request().url();
  report.stubbed.push(url);
  if (/\.css(\?|$)|fonts\.googleapis/.test(url)) return route.fulfill({ status: 200, contentType: "text/css", body: "" });
  if (/scenarios\.json/.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: '{"scenarios":[]}' });
  // macro-fx-base latest.json: 本物と同じ形（英語名 label_en は無し＝本番と同じ条件）で 14 指標を返す。
  // 英語表示で ID（real_yield.10y など）がそのまま出る訳し漏れを、オフラインでも snake_case 検査で見つけるため。
  if (/latest\.json/.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(macroFxStub()) });
  if (/\.json(\?|$)/.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  return route.fulfill({ status: 204, body: "" });
}

for (const lang of langs) {
  for (const width of widths) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, locale: lang === "ja" ? "ja-JP" : "en-US" });
    await ctx.addInitScript((l) => { try { localStorage.setItem("hf_lang", l); } catch (e) { /* ignore */ } }, lang);
    if (offline) await ctx.route((u) => new URL(u).origin !== origin, stub);
    const page = await ctx.newPage();
    const tag = `${lang}_${width}`;
    page.on("console", (m) => { if (m.type() === "error") report.errors.push({ tag, type: "console", text: m.text(), url: (m.location() || {}).url }); });
    page.on("pageerror", (e) => report.errors.push({ tag, type: "pageerror", text: String(e && e.stack || e) }));
    await page.goto(base + "/index.html", { waitUntil: "networkidle" });
    await page.waitForSelector("#main", { state: "visible", timeout: 20000 });
    await page.waitForTimeout(600);
    const shot = async (name, el) => {
      const p = path.join(out, `${tag}_${name}.png`);
      if (el) await el.screenshot({ path: p }); else await page.screenshot({ path: p, fullPage: true });
      report.shots.push(p); console.log("saved", p);
    };
    for (const t of TABS) {
      await page.click(`.tab[data-tab="${t}"]`);
      await page.waitForTimeout(t === "relations" || t === "moneyflow" ? 900 : 500);
      await shot(`tab_${t}`);
      await scanSnake(page, tag, `tab_${t}`);
    }
    // 銘柄詳細: 日経225 の 7735.T と FX 1 本（USDJPY があればそれ、無ければ最初のチャートあり行）
    const detail = async (tabKey, pickSym, name) => {
      await page.click(`.tab[data-tab="${tabKey}"]`);
      await page.waitForTimeout(400);
      const sym = await page.evaluate(pickSym, JP_SYMBOL);
      if (!sym) { report.errors.push({ tag, type: "missing", text: `no row for ${name} on ${tabKey}` }); return; }
      await page.click(`#tbody tr[data-sym="${sym}"] td:nth-child(2)`);
      await page.waitForSelector("tr.detail-row .dt-wrap", { timeout: 8000 });
      await page.waitForTimeout(400);
      const det = await page.$("tr.detail-row");
      await det.scrollIntoViewIfNeeded();
      await shot(name, det);
      await scanSnake(page, tag, name, "tr.detail-row");
    };
    // ── E2E: 銘柄を表示している表すべてで、1行目を押すと銘柄詳細が開く ──
    // 通常の表（日経225 / Dow 30 / Nasdaq 100 / S&P 500 / FX）と、米国の買い判定一覧（Nasdaq 100 タブの上）。
    // 買い判定一覧は Enter キーでも開くこと・cursor: pointer であることも見る。
    // （SURVIVAL の候補表は Take/Skip の操作用、金利・債券・VOL と ポジション/割安度 は詳細を出さない設計なので対象外）
    const opened = async (where) => {
      try { await page.waitForSelector("tr.detail-row .dt-wrap", { timeout: 8000 }); }
      catch (e) { report.errors.push({ tag, type: "e2e", text: `${where}: 1行目を押しても銘柄詳細が開かない` }); return false; }
      await page.evaluate(() => document.querySelectorAll("tr.detail-row").forEach((e) => e.remove()));
      return true;
    };
    for (const t of ["nikkei225", "dow30", "nasdaq100", "sp500", "fx"]) {
      await page.click(`.tab[data-tab="${t}"]`);
      await page.waitForTimeout(400);
      const first = await page.$("#tbody tr[data-sym]:not([data-sym=''])");
      if (!first) { report.errors.push({ tag, type: "e2e", text: `${t}: 表に銘柄の行が無い` }); continue; }
      await first.click();
      await opened(`${t} の表`);
    }
    await page.click('.tab[data-tab="nasdaq100"]');
    await page.waitForTimeout(400);
    const ub = await page.$("#us-buy-list tr.ub-row");
    if (ub) {
      const cur = await ub.evaluate((el) => getComputedStyle(el).cursor);
      if (cur !== "pointer") report.errors.push({ tag, type: "e2e", text: `米国の買い判定一覧: cursor が ${cur}（pointer であるべき）` });
      await ub.click();
      if (await opened("米国の買い判定一覧（クリック）")) {
        await ub.focus();
        await page.keyboard.press("Enter");
        await opened("米国の買い判定一覧（Enter）");
      }
    } else if (await page.$("#us-buy-list table")) {
      report.errors.push({ tag, type: "e2e", text: "米国の買い判定一覧: 表はあるのに押せる行（tr.ub-row）が無い" });
    }
    await detail("nikkei225", (s) => (document.querySelector(`#tbody tr[data-sym="${s}"]`) ? s : null), "detail_7735T").catch((e) => report.errors.push({ tag, type: "script", text: String(e) }));
    await detail("fx", () => {
      const rows = [...document.querySelectorAll("#tbody tr[data-sym]")].map((r) => r.getAttribute("data-sym"));
      return rows.find((s) => /^USDJPY/.test(s)) || rows[0] || null;
    }, "detail_fx").catch((e) => report.errors.push({ tag, type: "script", text: String(e) }));
    await ctx.close();
  }
}
await browser.close();
report.error_count = report.errors.length;
fs.writeFileSync(path.join(out, "console_report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ shots: report.shots.length, error_count: report.error_count, stubbed: [...new Set(report.stubbed)] }));
if (report.errors.length) {
  if (warnOnly) {
    for (const e of report.errors) console.log(`::warning::${e.type} ${e.tag} ${String(e.text).slice(0, 300).replace(/\r?\n/g, " ")}`);
    process.exit(0);
  }
  console.error("errors:", JSON.stringify(report.errors, null, 2)); process.exit(1);
}
