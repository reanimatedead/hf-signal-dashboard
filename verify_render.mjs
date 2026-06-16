// verify_render.mjs — Macro タブ描画ハーネス（BUILD_SPEC v4 §A5 増築版）
// 本番(MacBook)で実行: `npm i puppeteer` 後 `node verify_render.mjs`
// docs/ を静的配信して puppeteer で Macro タブをクリック → DOM/Canvas 検査。
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";

const DIR = new URL("./docs/", import.meta.url).pathname;
const PORT = parseInt(process.env.PORT || "8788", 10);
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".json": "application/json",
  ".css": "text/css",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".csv": "text/csv",
};

const server = http.createServer(async (req, res) => {
  try {
    let urlPath = req.url === "/" ? "/index.html" : req.url.split("?")[0];
    const p = join(DIR, urlPath);
    const body = await readFile(p);
    res.writeHead(200, { "Content-Type": MIME[extname(p)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("404");
  }
});

function out(o) {
  console.log(JSON.stringify(o, null, 2));
  process.exit(o.result === "PASS" ? 0 : 1);
}

await new Promise(r => server.listen(PORT, r));

let puppeteer;
try {
  puppeteer = (await import("puppeteer")).default;
} catch {
  out({
    harness: "verify_render.mjs",
    result: "FAIL",
    failed: ["puppeteer 未導入。`npm i puppeteer` を実行してください。"],
    note: "本番 (MacBook) で実行してください。",
  });
}

const errors = [];
const badRequests = [];
const isBenignUrl = (u) => /favicon|googleapis|gstatic/.test(u);
const isBenignMsg = (s) => /favicon|googleapis|gstatic|Failed to load resource/.test(s);
const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
try {
  const page = await browser.newPage();
  page.on("console", m => {
    if (m.type() !== "error") return;
    const t = m.text() || "";
    if (isBenignMsg(t)) return;
    errors.push(t);
  });
  page.on("pageerror", e => {
    const s = String(e);
    if (isBenignMsg(s)) return;
    errors.push(s);
  });
  page.on("response", res => {
    const u = res.url();
    if (res.status() >= 400 && !isBenignUrl(u)) badRequests.push(`${res.status()} ${u}`);
  });
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle0", timeout: 20000 });

  // 既存ダッシュボードが初期化されるまで少し待つ
  await new Promise(r => setTimeout(r, 1500));

  // Macro タブを評価＆クリック
  const tabExists = await page.evaluate(() => !!document.getElementById("hf-macro-tab-btn"));
  if (!tabExists) {
    await browser.close(); server.close();
    out({
      harness: "verify_render.mjs",
      result: "FAIL",
      failed: ["#hf-macro-tab-btn が存在しない（タブが追加されていない）"],
      generated_at: new Date().toISOString(),
    });
  }
  await page.evaluate(() => document.getElementById("hf-macro-tab-btn").click());
  // データロード＋アニメ進行を待つ
  await new Promise(r => setTimeout(r, 2500));

  const checks = await page.evaluate(() => {
    const pane = document.getElementById("hf-macro-pane");
    const paneVisible = !!(pane && getComputedStyle(pane).display !== "none");
    const cv = document.getElementById("hf-macro-cv");
    const animOK = !!(cv && cv.getContext && cv.getContext("2d"));
    const tiles = document.querySelectorAll('#hf-macro-tiles [data-tile]');
    let docsOK = tiles.length > 0;
    tiles.forEach(t => {
      const ex = t.querySelector('.hf-macro-explain');
      const cv = t.querySelector('.hf-macro-caveat');
      if (!ex || !ex.textContent.trim() || !cv || !cv.textContent.trim()) docsOK = false;
    });
    const tw = document.querySelector(".tbl-wrap");
    const tableHiddenOnMacro = !!(tw && getComputedStyle(tw).display === "none");
    const disc = document.body.innerText.includes("売買助言ではない") ||
                 document.body.innerText.toLowerCase().includes("not investment advice");
    // 既存 per-symbol タブが DOM 上に残っているか
    const existingTabsPresent = !!document.querySelector(".tab[onclick*=\"nikkei225\"]");
    return {
      paneVisible,
      animOK,
      tileCount: tiles.length,
      docsOK,
      tableHiddenOnMacro,
      disc,
      existingTabsPresent,
    };
  });

  // 既存タブに戻って回帰しないか確認
  await page.evaluate(() => {
    const t = document.querySelector(".tab[onclick*=\"nikkei225\"]");
    if (t) t.click();
  });
  await new Promise(r => setTimeout(r, 500));
  const regr = await page.evaluate(() => {
    const pane = document.getElementById("hf-macro-pane");
    const paneHidden = !!(pane && getComputedStyle(pane).display === "none");
    const tw = document.querySelector(".tbl-wrap");
    const tableVisible = !!(tw && getComputedStyle(tw).display !== "none");
    return { paneHidden, tableVisible };
  });

  const failed = [];
  if (errors.length) failed.push("console errors: " + errors.slice(0, 3).join(" | "));
  if (badRequests.length) failed.push("bad requests: " + badRequests.slice(0, 3).join(" | "));
  if (!checks.paneVisible) failed.push("macro pane not visible after tab click");
  if (!checks.animOK) failed.push("canvas/anim not initialized");
  if (checks.tileCount < 1) failed.push("no macro tiles rendered");
  if (!checks.docsOK) failed.push("macro tile missing explain/caveat");
  if (!checks.tableHiddenOnMacro) failed.push("existing tbl-wrap not hidden on macro");
  if (!checks.disc) failed.push("missing 'not investment advice' disclaimer");
  if (!checks.existingTabsPresent) failed.push("existing per-symbol tabs missing (regression)");
  if (!regr.paneHidden) failed.push("macro pane stayed visible after switching back");
  if (!regr.tableVisible) failed.push("table did not restore after switching back");

  out({
    harness: "verify_render.mjs",
    result: failed.length ? "FAIL" : "PASS",
    tileCount: checks.tileCount,
    paneVisible: checks.paneVisible,
    tableHiddenOnMacro: checks.tableHiddenOnMacro,
    existingTabsPresent: checks.existingTabsPresent,
    failed,
    generated_at: new Date().toISOString(),
  });
} finally {
  try { await browser.close(); } catch {}
  try { server.close(); } catch {}
}
