// verify_render.mjs — v4.1 rendering harness
//   - 8 tabs present (rates_vol / pos_val / moneyflow 含む)
//   - 背景 canvas (#bg-fx) が body 直下・pointer-events:none・aria-hidden
//   - お金の流れタブで 3 地域 canvas が描画され、借金カウンタが値表示
//   - 既存の検索/ウォッチリスト/CSV/Dark-Light/SVGチャートに回帰なし
//
// 実行: `npm i puppeteer` 後、`node verify_render.mjs`
// puppeteer が未導入なら FAIL を JSON で返して終了。

import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";

const DIR = new URL("./docs/", import.meta.url).pathname;

// ── corr-network: independent edge/null count from docs/data.json ─────────
// Mirrors the browser-side logic in docs/index.html's drawCorrNetwork():
// upper-triangle only (i<j, diagonal excluded), null/undefined/NaN -> "nulls",
// |r|>=0.3 -> "edges". Computed independently here (not by reading the
// browser's own output) so the gate can catch a regression in either side.
function countEdgesNulls(matrix, n) {
  let edges = 0;
  let nulls = 0;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const rVal = matrix[i] ? matrix[i][j] : null;
      if (rVal === null || rVal === undefined || Number.isNaN(rVal)) {
        nulls++;
        continue;
      }
      if (Math.abs(rVal) >= 0.3) edges++;
    }
  }
  return { edges, nulls };
}

async function computeCorrExpected() {
  const raw = await readFile(join(DIR, "data.json"), "utf8");
  const data = JSON.parse(raw);
  const corr = data.correlations;
  if (!corr || !Array.isArray(corr.labels)) {
    throw new Error("docs/data.json missing correlations.labels — cannot compute expected edge/null counts");
  }
  const n = corr.labels.length;
  return {
    "60d": countEdgesNulls(corr.matrix_60d, n),
    "20d": countEdgesNulls(corr.matrix_20d, n),
  };
}
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
    const urlPath = req.url === "/" ? "/index.html" : req.url.split("?")[0];
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

await new Promise((r) => server.listen(PORT, r));

let puppeteer;
try {
  puppeteer = (await import("puppeteer")).default;
} catch {
  out({
    harness: "verify_render.mjs",
    result: "FAIL",
    failed: ["puppeteer 未導入。`npm i puppeteer` を実行してください。"],
    note: "本番 (MacBook) で実行。CI では tests/test_index_html_contract.py が同等の静的チェック。",
  });
}

const errors = [];
const badRequests = [];
const isBenignUrl = (u) => /favicon|googleapis|gstatic/.test(u);
const isBenignMsg = (s) => /favicon|googleapis|gstatic|Failed to load resource/.test(s);

const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
try {
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text() || "";
    if (isBenignMsg(t)) return;
    errors.push(t);
  });
  page.on("pageerror", (e) => {
    const s = String(e);
    if (isBenignMsg(s)) return;
    errors.push(s);
  });
  page.on("response", (res) => {
    const u = res.url();
    if (res.status() >= 400 && !isBenignUrl(u)) badRequests.push(`${res.status()} ${u}`);
  });

  await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle0", timeout: 25000 });
  await new Promise((r) => setTimeout(r, 1500));

  const init = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll("#tabs .tab[data-tab]"));
    const bg = document.getElementById("bg-fx");
    const bgStyle = bg ? getComputedStyle(bg) : null;
    const bgbtn = document.getElementById("bgbtn");
    const active = document.querySelector("#tabs .tab.active[data-tab]");
    const sp = document.getElementById("survival-pane");
    const rg = document.getElementById("sv-risk-gate");
    return {
      tabCount: tabs.length,
      tabIds: tabs.map((t) => t.getAttribute("data-tab")),
      bgPresent: !!bg,
      bgZ: bgStyle ? bgStyle.zIndex : null,
      bgPe: bgStyle ? bgStyle.pointerEvents : null,
      bgAria: bg ? bg.getAttribute("aria-hidden") : null,
      bgBtnPresent: !!bgbtn,
      activeOnLoad: active ? active.getAttribute("data-tab") : null,
      survivalPaneVisibleOnLoad: !!(sp && getComputedStyle(sp).display !== "none"),
      riskGateTextLen: rg ? rg.textContent.trim().length : 0,
      candidateRowsOnLoad: document.querySelectorAll("#sv-candidates tbody tr").length,
      bankruptcyRowsOnLoad: document.querySelectorAll("#sv-bankruptcy tbody tr").length,
    };
  });

  // Click お金の流れ
  await page.evaluate(() => {
    const t = document.querySelector('#tabs .tab[data-tab="moneyflow"]');
    if (t) t.click();
  });
  await new Promise((r) => setTimeout(r, 2000));

  const mf = await page.evaluate(() => {
    const pane = document.getElementById("mf-pane");
    const paneVisible = !!(pane && getComputedStyle(pane).display !== "none");
    const tw = document.querySelector(".tbl-wrap");
    const tableHidden = !!(tw && getComputedStyle(tw).display === "none");
    const canvases = ["us", "eu", "jp"].map((r) => {
      const c = document.getElementById("mf-cv-" + r);
      return c ? { has: true, w: c.width, h: c.height } : { has: false };
    });
    const counters = ["us", "eu", "jp"].map((r) => {
      const el = document.getElementById("mf-counter-" + r);
      return el ? el.textContent.trim() : null;
    });
    const badges = ["us", "eu", "jp"].map((r) => {
      const el = document.getElementById("mf-fresh-" + r);
      return el ? el.textContent.trim() : null;
    });
    const disc =
      document.body.innerText.includes("not investment advice") ||
      document.body.innerText.includes("売買助言") ||
      document.body.innerText.includes("環境");
    return { paneVisible, tableHidden, canvases, counters, badges, disc };
  });

  // ── corr-network: canvas visibility + stats at initial (60d) window ──
  const corrExpected = await computeCorrExpected();
  const corrInit = await page.evaluate(() => {
    const cv = document.getElementById("corr-network");
    if (!cv) return { present: false };
    const rect = cv.getBoundingClientRect();
    return {
      present: true,
      w: rect.width,
      h: rect.height,
      stats: window.__corrNetworkStats || null,
    };
  });

  // Toggle to 20d window via the .cp-wbtn button (not calling internals directly)
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll(".cp-wbtn"));
    const b20 = btns.find((el) => /20d|20日/.test(el.textContent) || el.getAttribute("onclick")?.includes("'20d'"));
    if (b20) b20.click();
  });
  await new Promise((r) => setTimeout(r, 500));

  const corr20 = await page.evaluate(() => {
    const cv = document.getElementById("corr-network");
    if (!cv) return { present: false };
    const rect = cv.getBoundingClientRect();
    return {
      present: true,
      w: rect.width,
      h: rect.height,
      stats: window.__corrNetworkStats || null,
    };
  });

  // Cycle background mode twice and capture transitions
  const bgBefore = await page.evaluate(() => localStorage.getItem("hf_bg_mode") || "clean");
  await page.evaluate(() => document.getElementById("bgbtn")?.click());
  await new Promise((r) => setTimeout(r, 300));
  const bgAfter1 = await page.evaluate(() => localStorage.getItem("hf_bg_mode"));
  await page.evaluate(() => document.getElementById("bgbtn")?.click());
  await new Promise((r) => setTimeout(r, 200));
  const bgAfter2 = await page.evaluate(() => localStorage.getItem("hf_bg_mode"));

  // Toggle language
  await page.evaluate(() => document.getElementById("lngbtn")?.click());
  const lng = await page.evaluate(() => localStorage.getItem("hf_lang"));

  // Switch back to a regular tab
  await page.evaluate(() => {
    const t = document.querySelector('#tabs .tab[data-tab="nikkei225"]');
    if (t) t.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  const back = await page.evaluate(() => {
    const pane = document.getElementById("mf-pane");
    const paneHidden = !!(pane && getComputedStyle(pane).display === "none");
    const tw = document.querySelector(".tbl-wrap");
    const tableVisible = !!(tw && getComputedStyle(tw).display !== "none");
    const rows = document.querySelectorAll("#tbody tr").length;
    return { paneHidden, tableVisible, rows };
  });

  const failed = [];
  if (init.tabCount !== 9) failed.push(`expected 9 tabs, got ${init.tabCount}`);
  const want = ["survival","nikkei225","dow30","nasdaq100","sp500","fx","rates_vol","pos_val","moneyflow"];
  if (init.tabIds.join(",") !== want.join(","))
    failed.push(`tab order mismatch: ${init.tabIds.join(",")}`);
  if (!init.bgPresent) failed.push("#bg-fx canvas missing");
  if (init.bgPe !== "none") failed.push(`#bg-fx pointer-events must be 'none' (got ${init.bgPe})`);
  if (init.bgAria !== "true") failed.push(`#bg-fx aria-hidden must be 'true' (got ${init.bgAria})`);
  if (!init.bgBtnPresent) failed.push("#bgbtn missing");

  if (!mf.paneVisible) failed.push("mf-pane not visible after moneyflow click");
  if (!mf.tableHidden) failed.push("tbl-wrap not hidden in moneyflow");
  mf.canvases.forEach((c, i) => {
    const r = ["us","eu","jp"][i];
    if (!c.has) failed.push(`mf-cv-${r} canvas missing`);
    else if (!c.w || !c.h) failed.push(`mf-cv-${r} canvas has zero size`);
  });
  mf.counters.forEach((t, i) => {
    if (!t) failed.push(`mf-counter-${["us","eu","jp"][i]} not rendered`);
  });
  if (!mf.disc) failed.push("missing disclaimer ('not investment advice' / 売買助言)");

  if (bgAfter1 === bgBefore) failed.push("background mode cycle did not change first time");
  if (bgAfter2 === bgAfter1) failed.push("background mode cycle did not change second time");
  if (!lng || (lng !== "ja" && lng !== "en")) failed.push("language toggle did not persist");

  if (init.activeOnLoad !== "survival") failed.push(`default-active tab must be 'survival', got '${init.activeOnLoad}'`);
  if (!init.survivalPaneVisibleOnLoad) failed.push("survival-pane not visible on first load");
  if (init.riskGateTextLen === 0) failed.push("risk gate not rendered on load");
  if (init.bankruptcyRowsOnLoad === 0) failed.push("bankruptcy heatmap empty on load");
  if (init.candidateRowsOnLoad === 0) failed.push("no SURVIVAL candidates on load");

  if (!back.paneHidden) failed.push("mf-pane stayed visible after returning to nikkei225");
  if (!back.tableVisible) failed.push("table did not restore on return");
  if (back.rows === 0) failed.push("no table rows after returning to nikkei225 (regression)");

  // ── gate: corr_network_canvas ──────────────────────────────────────
  if (!corrInit.present) failed.push("corr_network_canvas: #corr-network canvas missing after moneyflow tab click");
  else if (!(corrInit.w > 0 && corrInit.h > 0))
    failed.push(`corr_network_canvas: #corr-network has zero size (w=${corrInit.w}, h=${corrInit.h})`);

  // ── gate: corr_network_edge_parity ───────────────────────────────────
  // Compares the browser-reported window.__corrNetworkStats against an
  // independent edge/null count computed directly from docs/data.json
  // (see computeCorrExpected/countEdgesNulls above), for both the initial
  // 60d window and after clicking the 20d .cp-wbtn toggle.
  if (!corrInit.stats) {
    failed.push("corr_network_edge_parity: window.__corrNetworkStats missing on initial (60d) render");
  } else {
    if (corrInit.stats.window !== "60d")
      failed.push(`corr_network_edge_parity: expected initial window '60d', got '${corrInit.stats.window}'`);
    const exp60 = corrExpected["60d"];
    if (corrInit.stats.edges !== exp60.edges)
      failed.push(`corr_network_edge_parity: 60d edges mismatch — expected ${exp60.edges}, got ${corrInit.stats.edges}`);
    if (corrInit.stats.nulls !== exp60.nulls)
      failed.push(`corr_network_edge_parity: 60d nulls mismatch — expected ${exp60.nulls}, got ${corrInit.stats.nulls}`);
  }
  if (!corr20.stats) {
    failed.push("corr_network_edge_parity: window.__corrNetworkStats missing after 20d toggle click");
  } else {
    if (corr20.stats.window !== "20d")
      failed.push(`corr_network_edge_parity: expected window '20d' after toggle, got '${corr20.stats.window}'`);
    const exp20 = corrExpected["20d"];
    if (corr20.stats.edges !== exp20.edges)
      failed.push(`corr_network_edge_parity: 20d edges mismatch — expected ${exp20.edges}, got ${corr20.stats.edges}`);
    if (corr20.stats.nulls !== exp20.nulls)
      failed.push(`corr_network_edge_parity: 20d nulls mismatch — expected ${exp20.nulls}, got ${corr20.stats.nulls}`);
  }

  // ── gate: corr_network_js_errors ─────────────────────────────────────
  // Reuses the page-wide `errors` collector (console 'error' + pageerror),
  // which already ran through the corr-network render + 20d toggle above.
  // The pre-existing isBenignMsg() (top of file) filters out favicon's
  // "Failed to load resource ... 404" — the one known, unrelated 404 this
  // static server produces — plus googleapis/gstatic noise. That filter is
  // untouched here; this gate simply asserts the (already-filtered) errors
  // collected during the corr-network interactions is empty.
  if (errors.length) failed.push("corr_network_js_errors: console errors: " + errors.slice(0, 5).join(" | "));

  if (badRequests.length) failed.push("bad requests: " + badRequests.slice(0, 3).join(" | "));

  out({
    harness: "verify_render.mjs",
    result: failed.length ? "FAIL" : "PASS",
    init,
    moneyFlow: { paneVisible: mf.paneVisible, tableHidden: mf.tableHidden,
                 canvases: mf.canvases, counters: mf.counters, badges: mf.badges },
    corrNetwork: {
      canvas60d: { w: corrInit.w, h: corrInit.h },
      canvas20d: { w: corr20.w, h: corr20.h },
      expected: corrExpected,
      actual: { "60d": corrInit.stats, "20d": corr20.stats },
    },
    bgCycle: { before: bgBefore, after1: bgAfter1, after2: bgAfter2 },
    langPersisted: lng,
    backToNikkei: back,
    failed,
    generated_at: new Date().toISOString(),
  });
} finally {
  try { await browser.close(); } catch {}
  try { server.close(); } catch {}
}
