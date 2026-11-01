/* assets/signal/names.js — 会社名の表示を揃える（表示の時だけ。data.json・取得側は変えない）。
 *
 * 取得元によって同じ会社の名前の書き方が違う（Nasdaq API: "Alphabet Inc. Class A Common Stock" /
 * Wikipedia: "Alphabet Inc. (Class A)" / iShares: "ALPHABET INC CL A"）。末尾の株式の種類の説明だけを外す:
 *   Common Stock / Common Shares / Capital Stock / Ordinary Shares / American Depositary Shares /
 *   New York Registry Shares / Subordinate Voting Shares / Shares（前に Class A・Series B・CL C が付いてもよい）、
 *   末尾の Class A・CL B、括弧の (Class A)・(DE)・(Ireland)。"Inc." などの会社の形は残す。
 * 会社名を出す所（表・米国の買い判定一覧・銘柄詳細の見出し・SURVIVAL の候補）はすべて companyName を通す。
 * companyCount: 名前を揃えた上で同じ会社を 1 社と数える（GOOG と GOOGL など 2 種類の株を持つ会社）。
 * 文言は持たない（辞書 assets/i18n/dict.js の外に表示文を置かない）。
 */
(function (root) {
  "use strict";
  const CLS = "(?:class|series|cl)\\s+[a-z]";
  const TAIL = [
    new RegExp("[\\s,]+(?:" + CLS + "\\s+)?(?:common\\s+stock|common\\s+shares|capital\\s+stock|ordinary\\s+shares"
      + "|american\\s+depositary\\s+shares|new\\s+york\\s+registry\\s+shares|subordinate\\s+voting\\s+shares|shares)$", "i"),
    new RegExp("[\\s,]+" + CLS + "$", "i"),
    new RegExp("\\s*\\((?:" + CLS + "|de|ireland)\\)$", "i"),
  ];

  function companyName(name) {
    let s = String(name == null ? "" : name).replace(/\s+/g, " ").trim();
    for (let changed = true; changed;) {
      changed = false;
      for (const re of TAIL) {
        const t = s.replace(re, "").replace(/[\s,]+$/, "");
        if (t !== s && t) { s = t; changed = true; }
      }
    }
    return s;
  }

  // 同じ会社かどうかの鍵: 揃えた名前を小文字・英数字だけにしたもの
  const key = (name) => companyName(name).toLowerCase().replace(/[^0-9a-z぀-鿿]+/g, "");

  // rows: [{symbol, name}] → { symbols, companies, shared: [[sym, sym], ...] }（名前が無い行は 1 行 1 社）
  function companyCount(rows) {
    const groups = new Map();
    (rows || []).forEach((r, i) => {
      const k = key(r && r.name) || "\u0000" + i;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(String((r && r.symbol) || ""));
    });
    const shared = [...groups.values()].filter((g) => g.length > 1).map((g) => g.slice().sort());
    return { symbols: (rows || []).length, companies: groups.size, shared };
  }

  root.NAMES = { companyName, companyCount };
})(typeof window !== "undefined" ? window : globalThis);
