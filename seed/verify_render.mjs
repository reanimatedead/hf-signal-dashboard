// verify_render.mjs — ヘッドレス描画チェック (BUILD_SPEC §6.2)
// 本番(MacBook)で実行: `npm i puppeteer` 後 `node verify_render.mjs`
// 静的配信して http で開く(file:// のCORS回避)。
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";

const DIR = new URL("./public/", import.meta.url).pathname;
const PORT = 8787;
const MIME = { ".html":"text/html", ".js":"text/javascript", ".json":"application/json", ".css":"text/css" };

const server = http.createServer(async (req, res) => {
  try {
    const p = join(DIR, req.url === "/" ? "index.html" : req.url.split("?")[0]);
    const body = await readFile(p);
    res.writeHead(200, { "Content-Type": MIME[extname(p)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("404"); }
});

function out(o){ console.log(JSON.stringify(o, null, 2)); process.exit(o.result === "PASS" ? 0 : 1); }

await new Promise(r => server.listen(PORT, r));

let puppeteer;
try { puppeteer = (await import("puppeteer")).default; }
catch { out({ harness:"verify_render.mjs", result:"FAIL", failed:["puppeteer 未導入。`npm i puppeteer`"], note:"本番(MacBook)で実行してください" }); }

const errors = [];
const browser = await puppeteer.launch({ headless: "new", args:["--no-sandbox"] });
try {
  const page = await browser.newPage();
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle0", timeout: 15000 });
  await new Promise(r => setTimeout(r, 1200)); // アニメ進行

  const checks = await page.evaluate(() => {
    const tiles = document.querySelectorAll('[data-tile]');
    let docsOK = true;
    tiles.forEach(t => { if (!t.querySelector('.explain')?.textContent || !t.querySelector('.caveat')?.textContent) docsOK = false; });
    const cv = document.getElementById('cv');
    const animOK = !!(cv && cv.getContext && cv.getContext('2d'));
    const disc = document.body.innerText.includes("売買助言ではない") || document.body.innerText.toLowerCase().includes("not investment advice");
    return { tileCount: tiles.length, docsOK, animOK, disc };
  });

  const failed = [];
  if (errors.length) failed.push("console errors: " + errors.slice(0,3).join(" | "));
  if (checks.tileCount < 1) failed.push("no tiles rendered");
  if (!checks.docsOK) failed.push("tile missing explain/caveat");
  if (!checks.animOK) failed.push("canvas/anim not initialized");
  if (!checks.disc) failed.push("missing 'not investment advice' disclaimer");

  out({ harness:"verify_render.mjs", result: failed.length ? "FAIL":"PASS",
        tileCount: checks.tileCount, failed,
        generated_at: new Date().toISOString() });
} finally {
  await browser.close(); server.close();
}
