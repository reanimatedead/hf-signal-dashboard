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
const langs = opt("--langs", "ja,en").split(",");
const widths = opt("--widths", "1280,390").split(",").map(Number);
const TABS = ["survival", "nikkei225", "dow30", "nasdaq100", "sp500", "fx", "rates_vol", "pos_val", "relations", "moneyflow", "verify"];
const JP_SYMBOL = "7735.T";
fs.mkdirSync(out, { recursive: true });

const origin = new URL(base).origin;
const report = { base, offline, errors: [], stubbed: [], shots: [] };
const browser = await chromium.launch();
// snake_case: 英小文字/数字の語が _ でつながった形（例 high_vol, n_symbols）。URL・ファイル名は innerText に出ない前提。
const SNAKE = /(?<![A-Za-z0-9_.\/-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_.\/-])/g;
async function scanSnake(page, tag, where, root) {
  const text = await page.evaluate((sel) => {
    const el = sel ? document.querySelector(sel) : document.body;
    return el ? el.innerText : "";
  }, root || null);
  const hits = [...new Set(text.match(SNAKE) || [])];
  if (hits.length) report.errors.push({ tag, type: "snake", text: `${where}: ${hits.join(", ")}` });
}

async function stub(route) {
  const url = route.request().url();
  report.stubbed.push(url);
  if (/\.css(\?|$)|fonts\.googleapis/.test(url)) return route.fulfill({ status: 200, contentType: "text/css", body: "" });
  if (/scenarios\.json/.test(url)) return route.fulfill({ status: 200, contentType: "application/json", body: '{"scenarios":[]}' });
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
if (report.errors.length) { console.error("errors:", JSON.stringify(report.errors, null, 2)); process.exit(1); }
