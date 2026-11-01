// tools/preview_screens.mjs — 架空データのプレビュー（tools/build_preview.py）を Playwright で撮る。
// 使い方: node tools/preview_screens.mjs http://127.0.0.1:8765 OUT_DIR
// 撮るもの: 日経225 タブ / Nasdaq 100 タブ（米国の買い判定一覧）/ 銘柄詳細チャート / 検証タブ。
// ページのエラー（pageerror）があれば exit 1。
import { createRequire } from "module";
import fs from "fs";
import path from "path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.argv[2] || "http://127.0.0.1:8765";
const out = process.argv[3] || "preview";
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 2000, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base + "/index.html", { waitUntil: "networkidle" });
await page.waitForSelector("#main", { state: "visible" });
await page.waitForTimeout(800);

async function tab(key) {
  await page.click(`.tab[data-tab="${key}"]`);
  await page.waitForTimeout(600);
}
const shot = async (name, opts = {}) => {
  const p = path.join(out, name);
  await page.screenshot({ path: p, fullPage: false, ...opts });
  console.log("saved", p);
};

await tab("nikkei225");
await shot("01_nikkei225.png");
// 右端の列（理論株価・割安度・総合判定 =「ログイン版のみ」）が見えるように横スクロール
await page.evaluate(() => { const w = document.querySelector(".tbl-wrap"); if (w) w.scrollLeft = w.scrollWidth; window.scrollTo(document.body.scrollWidth, 0); });
await page.waitForTimeout(300);
await shot("01b_nikkei225_login_only.png");
await page.evaluate(() => { const w = document.querySelector(".tbl-wrap"); if (w) w.scrollLeft = 0; window.scrollTo(0, 0); });

await tab("nasdaq100");
await shot("02_nasdaq100_us_buy_list.png");

// 詳細チャート: Nasdaq 100 の AAA（架空・長期上向き→急落で▲が出る）を開く
await page.click('#tbody tr[data-sym="AAA"]');
await page.waitForSelector("tr.detail-row .sg-chart", { timeout: 5000 });
await page.waitForTimeout(400);
const det = await page.$("tr.detail-row");
await det.scrollIntoViewIfNeeded();
await det.screenshot({ path: path.join(out, "03_detail_chart.png") });
console.log("saved", path.join(out, "03_detail_chart.png"));

await tab("verify");
await shot("04_verify_tab.png", { fullPage: true });

const checks = await page.evaluate(() => ({
  stale: getComputedStyle(document.getElementById("stale-banner")).display !== "none",
  staleText: document.getElementById("stale-banner").textContent,
  weak: getComputedStyle(document.getElementById("weak-banner")).display !== "none",
  verifyText: document.getElementById("verify-pane").textContent.slice(0, 80),
}));
console.log(JSON.stringify(checks));
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
