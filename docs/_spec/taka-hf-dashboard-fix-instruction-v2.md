---
date: 2026-07-25
tags: [taka-automation, hf-signal-dashboard, claude-code, instruction, macro, gamma]
関連: [[hf-signal-dashboard]] [[fx-analysis-system]] [[taka-hf-dashboard-fix-instruction]]
出典: data.json / CBOE / FRED / ECB 実測（2026-07-25）
種別: 単一完結指示書（分割ハンドオフ禁止）
supersedes: taka-hf-dashboard-fix-instruction v1.0
---

# hf-signal-dashboard 修正指示書 v2.0

## 0. v1 からの訂正（重要・先に読むこと）

v1 には実行時に判明した誤りがあった。v2 はそれを織り込んでいる。

| v1 の記述 | 実際 | 出典 |
|---|---|---|
| `index.html` | **`docs/index.html`** | `git diff --stat` 実測 |
| correlations は `fetch_signals.py` | **`pipeline/build_corr.py`**（`corr.yml` が実行） | Claude Code の探索結果 |
| 検証に `\|\| echo OK` を使用 | **禁止**。ファイル不在で誤合格する | 実際に誤合格を出した |
| Buffett リンク `fredgraph/?g=qLC` | **誤り**。開くと "Gross Domestic Product" | HTTP 実測 |
| VIX/MOVE を `kind:"source"` | **`kind:"quote"`** が正しい | Yahoo の正規クォートページ |
| Agent 4 は名目金利ベース | **実質金利ベース**に全面改訂 | 名目は符号が逆のものを合成してしまう |
| 容量予算 6MB | CBOE チェーン 1.7MB/日 を織り込み再設計 | gzip 実測 |

## 1. 現在地（2026-07-25 21:05 実測）

```
実行機      : M1 mac mini（MacBook Pro は使わない）
リポジトリ  : /Users/takahiroyamada/hf-signal-dashboard
ブランチ    : fix/dashboard-links-charts-eu
HEAD        : a5d7e24 fix(link): resolve per-row link from source_ticker instead of active tab
origin/main : cd5fd3d（未 push）
作業ツリー  : clean
```

Agent 1（v1）は検証済みで合格。`function lnk` は 0 件、`docs/index.html` 内の `finance.yahoo` 直書きは 0 件、`build_link` は `fetch_signals.py:2171` に定義され `:2218` で結線済み。

**push は最後まで人間ゲート。各 Agent 完了ごとに `git status` を報告し停止すること。**

## 2. 検証コマンドの規約（違反禁止）

```bash
# 禁止
grep -n "X" file || echo OK          # ファイル不在で誤合格する

# 必須
test -f file && echo FILE_EXISTS && grep -c "X" file
```

不在と不一致を必ず分離する。`grep -c` の件数で判定する。
Python の import 検証は `PYTHONPATH=. python3 <script>` を使う（`/tmp` 直下実行だと sys.path が狂う）。
外部リンクの死活確認は **Yahoo に対し 2 秒以上の待機を挟む**（実測で HTTP 429 を踏んだ）。

---

## Agent 1: 基盤修正（パス・リンク・分割・遅延ロード）

### 1-1. リンクの積み残し2件を修正

`fetch_signals.py` の `build_link` 内。`SRC` 辞書から `"VIX"` と `"MOVE"` の行を削除し、辞書判定の**手前**に以下を挿入。

```python
    # VIX / MOVE は Yahoo の正規クォートページなので quote 扱いにする
    QUOTE_ALIAS = {"VIX": "^VIX", "MOVE": "^MOVE"}
    if sym in QUOTE_ALIAS:
        t = QUOTE_ALIAS[sym]
        return {"url": f"https://finance.yahoo.com/quote/{quote(t, safe='')}/",
                "label": f"Yahoo Finance ({t})", "kind": "quote"}
```

`SRC` の Buffett 行を修正（`?g=qLC` は GDP のページに飛ぶ。実測確認済み）。

```python
      "US_BUFFETT_INDICATOR": ("https://fred.stlouisfed.org/series/NCBEILQ027S",
                               "FRED (NCBEILQ027S)"),
```

検証:

```bash
cd /Users/takahiroyamada/hf-signal-dashboard && PYTHONPATH=. python3 /tmp/t_link.py
```

合格条件: `VIX` の `kind` が `quote`、`US_BUFFETT_INDICATOR` が `series/NCBEILQ027S`。

### 1-2. ペイロード分割と遅延ロード

現状 `data.json` = 1,308,034 B。1d チャート 1 件 ≈ 16.2 KB。株式 368 行全部に付けると 5.9 MB、4h/1w も足すと約 18 MB で破綻する。

出力を分離する。

```
docs/data.json          … 一覧表・指標サマリ・money_flow・survival_loop（charts を除去）
docs/charts/{tab}.json  … nikkei225 / dow30 / nasdaq100 / sp500 / fx / rates / crypto
docs/macro.json         … Agent 2 が生成
docs/relations.json     … Agent 3 が生成
docs/gamma.json         … Agent 4 が生成
```

`data.json` の各行は `charts` の代わりに `chart_status: "ready"|"pending"|"unavailable"` のみ持つ。

`docs/index.html` に遅延ローダを追加。

```js
const CHART_CACHE = {};
async function loadCharts(tabKey){
  if(CHART_CACHE[tabKey]) return CHART_CACHE[tabKey];
  try{
    const res = await fetch(`charts/${tabKey}.json`, {cache:"no-cache"});
    if(!res.ok) throw new Error(res.status);
    CHART_CACHE[tabKey] = await res.json();
  }catch(e){
    CHART_CACHE[tabKey] = {};
    console.warn("chart load failed", tabKey, e);
  }
  return CHART_CACHE[tabKey];
}
```

### 1-3. 容量予算（v2 で再設計）

| 対象 | 予算 |
|---|---|
| `docs/data.json` | **< 400 KB** |
| `docs/charts/*.json` 合計 | **< 5 MB** |
| `docs/macro.json` | < 300 KB |
| `docs/relations.json` | < 200 KB |
| `docs/gamma.json` | **< 400 KB**（生チェーンは公開しない。集計値のみ） |
| `taka-data/cboe-chains/`（非公開） | 1.7 MB/日 × 250 日 ≒ **425 MB/年** |

被覆率ポリシー:

| 優先 | 対象 | 時間足 |
|---|---|---|
| P0 | 指数 5 本（`^N225` `^DJI` `^NDX` `^GSPC` `^STOXX50E`） | 1d + 1w |
| P1 | FX 18・rates 9・crypto 4 | 4h + 1d + 1w |
| P2 | `composite_score` 上位 30 銘柄／各株式タブ | 1d |
| P3 | 残り全株式 | 1d（OHLC を 120→60 本に間引き） |

株式の 4h / 1w は**提供しない**。理由（全被覆で約 18 MB）を `DATA_CONTRACT.md` に明記する。

### 1-4. 空欄の廃止

```js
const CHART_MSG = {
  pending:     "この銘柄のチャートは容量方針により未生成です（指数・FX・金利は生成済み）",
  unavailable: "データ元にこの時間足の系列がありません"
};
```

黙って空欄にしない。理由を必ず出す。

### 完了条件

```bash
cd /Users/takahiroyamada/hf-signal-dashboard
test -f docs/data.json && echo FILE_EXISTS && wc -c docs/data.json
du -sh docs/charts/
git status --short
```

`docs/data.json` が 400 KB 未満。commit `fix(link,payload): patch link targets and split chart payload`。**push しない。**

---

## Agent 2: マクロ層取込（ECB + FRED）

すべて疎通確認済み（2026-07-25 実測）。`docs/macro.json` を新規生成する。

### 2-1. 欧州利回り（ECB Data Portal・日次）

FRED のドイツ 10 年（`IRLTLT01DEM156N`）は**月次で粒度不足のため不採用**。

```python
ECB_BASE = "https://data-api.ecb.europa.eu/service/data/YC"
ECB_KEYS = {"EU2Y":"SR_2Y", "EU10Y":"SR_10Y", "EU30Y":"SR_30Y"}

def fetch_ecb_yield(tenor_key, n=520):
    url = (f"{ECB_BASE}/B.U2.EUR.4F.G_N_A.SV_C_YM.{tenor_key}"
           f"?lastNObservations={n}&format=csvdata")
    r = requests.get(url, timeout=30); r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return [{"date": x["TIME_PERIOD"], "yield": float(x["OBS_VALUE"])} for x in rows]
```

| キー | 実測値 (2026-07-23) |
|---|---|
| `SR_2Y` | 2.8006 |
| `SR_10Y` | 3.2247 |
| `SR_30Y` | 3.6516 |

`markets.rates` に 3 レコード追加。既存 US/JP と**同一スキーマ**。`data_status: "auto_ecb"`、`source: "ECB Data Portal (YC B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y)"`、`source_ticker: None`、`link` は `build_link` が ECB へ向ける。

`meta.yield_curve` に `eu_10y_2y_spread` を追加。**US の逆イールド判定ロジックを EU に流用しない。** 既存 JP と同じ方針で「ECB 政策／構成国混在を前提に別評価」と注記する。

**ECB がダウンしても US/JP を巻き込まない。** EU 行を `data_status:"error"` にしてプロセスは継続。

### 2-2. FRED 系列（すべて日次・実測確認済み）

```python
FRED_SERIES = {
  # 分解（恒等式）
  "DGS10":        ("US 10Y nominal",        "rates_decomp"),
  "DFII10":       ("US 10Y real (TIPS)",    "rates_decomp"),
  "T10YIE":       ("10Y breakeven",         "rates_decomp"),
  "THREEFYTP10":  ("10Y term premium",      "rates_decomp"),
  # 信用
  "BAMLH0A0HYM2": ("US HY OAS",             "credit"),
  "BAMLC0A0CM":   ("US IG OAS",             "credit"),
  # 資金繰り
  "SOFR":         ("SOFR",                  "funding"),
  "IORB":         ("IORB",                  "funding"),
  "SOFR99":       ("SOFR 99th pct",         "funding"),
  "WRESBAL":      ("Bank reserves",         "funding"),
  # 環境・レジーム
  "NFCI":         ("Chicago Fed NFCI",      "conditions"),
  "ANFCI":        ("Adjusted NFCI",         "conditions"),
  "STLFSI4":      ("StL Fed Fin Stress",    "conditions"),
  "DTWEXBGS":     ("Broad Dollar Index",    "conditions"),
  "T10Y3M":       ("10Y-3M spread",         "recession"),
  "SAHMREALTIME": ("Sahm rule",             "recession"),
}

def fetch_fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=30); r.raise_for_status()
    out=[]
    for row in csv.DictReader(io.StringIO(r.text)):
        d = row[list(row.keys())[0]]; v = row[series_id]
        if v in (".", "", None): continue
        out.append({"date": d, "value": float(v)})
    return out
```

実測値（2026-07-23〜24）:

| 系列 | 値 | 意味 |
|---|---|---|
| `DGS10` | 4.71 | 名目 10 年 |
| `DFII10` | 2.43 | 実質 10 年 |
| `T10YIE` | 2.26 | 期待インフレ |
| `THREEFYTP10` | 0.7787 | ターム・プレミアム |
| `BAMLH0A0HYM2` | 2.77 | HY スプレッド |
| `BAMLC0A0CM` | 0.79 | IG スプレッド |
| `SOFR` / `IORB` | 3.64 / 3.65 | 差 −0.01 |
| `SOFR99` | 3.72 | 99% タイル |
| `WRESBAL` | 3,062,149 | 準備預金（百万ドル） |
| `NFCI` | −0.552 | 負＝緩和的 |
| `DTWEXBGS` | 120.5315 | 広義ドル指数 |
| `T10Y3M` | 0.73 | Estrella–Mishkin 型 |
| `SAHMREALTIME` | 0.07 | 発火閾値 0.50 |

### 2-3. 恒等式の検算をコードに埋める

```python
def check_fisher(nominal, real, breakeven, tol=0.05):
    """名目 = 実質 + 期待インフレ。ズレたらデータ不整合を疑う"""
    gap = abs(nominal - (real + breakeven))
    return {"ok": gap <= tol, "gap": round(gap, 4)}
# 実測: 4.71 vs 2.43 + 2.26 = 4.69 → gap 0.02 → ok
```

```python
expectations = nominal - term_premium   # 4.71 - 0.7787 = 3.93
```

**同じ 4.71% でも「利上げ予想 3.93%」と「リスク料 0.78%」の内訳で株への効き方が違う。** 両方を必ず表示する。

### 2-4. net_liquidity の是正

現行 `WALCL − TGA − RRP` は SNS 由来の簡易式。RRP は既に 0.0009 兆ドルでほぼ枯渇しており情報量がない。**`WRESBAL`（準備預金残高）を第一指標に格上げ**し、簡易式は参考値として残す。両方を並記し、どちらが主かを画面で明示する。

### 2-5. 相関ラベルの拡張

**編集先は `pipeline/build_corr.py`（`fetch_signals.py` ではない）。**
`correlations.labels` に `EU10Y`, `SX5E` を追加。10×10 → 12×12。`matrix_60d` / `matrix_20d` の再計算を確認する。

### 完了条件

```bash
cd /Users/takahiroyamada/hf-signal-dashboard
test -f docs/macro.json && echo FILE_EXISTS && python3 -c "
import json; d=json.load(open('docs/macro.json'))
print('series:', len(d['series']))
print('fisher:', d['identities']['fisher'])
print('regions:', sorted({r['region'] for r in json.load(open('docs/data.json'))['markets']['rates']}))
"
```

`rates` の region が `['EU','JP','US']` の 3 種。commit `feat(macro): add ECB EU yields and FRED decomposition/credit/funding series`。**push しない。**

---

## Agent 3: 天秤層（債券利回り × 株価）

**v1 の Agent 4 を全面改訂したもの。名目金利ベースの仕様は破棄する。**

### 3-0. なぜ名目では駄目か

名目 = 実質 + 期待インフレ。この 2 つは**株に対して符号が逆**。

- 期待インフレ上昇で名目が上がる → 名目成長期待 → 株にプラス寄り
- 実質金利上昇で名目が上がる → 割引率上昇 → 株にマイナス

名目だけを重ねると両者が相殺され、相関が薄まる。**実質金利を主線にする。**

### 3-1. 天秤の 4 部品

`docs/relations.json` に以下を出力する。

**部品1: 相対価値（ERP）— 未実装として明示**

```
ERP = 株式益回り(E/P) − 実質金利
```

指数の日次 EPS に信頼できる無料ソースが存在しない。Shiller の広く使われているミラーは **2024-09 で更新停止**（実測確認済み）。

→ `{"erp": {"value": null, "data_status": "unavailable",
   "reason": "指数の日次EPSに無料の信頼ソースがない。Shillerミラーは2024-09で停止。"}}`

**画面には「未実装」と明示表示する。空欄にしない。** 部品 2・3・4 だけで天秤の動作状態は判定できる。

**部品2: 相関レジーム（天秤が機能しているか）**

```python
# SPX日次対数リターン × 10年利回りの日次変化(bp)、120日ローリング
r_spx = np.log(spx).diff()
dy    = y10.diff() * 100
roll  = r_spx.rolling(120).corr(dy)
```

**必ずリターン×変化で取る。水準同士の相関はトレンドで見かけ上高く出る。**

実測（FRED 実データ、2007〜2026）:

| 期間 | 平均 r |
|---|---|
| コロナ期 (2020/3–2021/6) | **+0.28** |
| インフレ転換 (2022) | +0.01 |
| 直近1年 | −0.04 |
| **現在（直近120日）** | **−0.41** |

レジーム分類器:

```python
def regime(r):
    if r <= -0.20: return ("growth_shock_dominant",
                           "成長ショック主導。債券が株のヘッジになる＝天秤が機能")
    if r >=  0.20: return ("inflation_policy_shock_dominant",
                           "インフレ/政策ショック主導。株と債券が同時に落ちる＝天秤が壊れる")
    return ("transition", "移行期。符号が不安定")
```

**60/40 の前提はこの符号に依存している。** 符号を見ずに金利と株を語らない。

**部品3: 感応度（腕の長さ）**

```python
# 10bp の利回り上昇に対する日次リターン（直近250日、OLS傾き）
beta = np.polyfit(dy, r_index, 1)[0] * 100 * 10   # % per 10bp
```

実測（直近 250 日）:

| 指数 | %/10bp |
|---|---|
| Nasdaq100 | −0.559 |
| Dow30 | −0.519 |
| S&P500 | −0.451 |

Nasdaq が最も敏感なのはデュレーション（利益が遠い将来にある）で説明どおり。**ただし Dow > SPX は教科書と逆。断定せず観測対象として置き、`note` に明記する。**

**部品4: 機械的フロー（四半期末リバランス）**

年金・バランスファンドは目標比率を四半期末に戻す。株が債券より上がれば**強制的に株を売り債券を買う**。文字どおりの天秤。

```python
eq_ret   = spx.iloc[-1]/spx_q_start - 1
bond_ret = -8.0 * (y10.iloc[-1] - y10_q_start) / 100   # デュレーション8で近似
gap      = eq_ret - bond_ret
pressure = "sell_equity_buy_bond" if gap > 0 else "buy_equity_sell_bond"
```

実測（当四半期 7/1〜7/24）: 株式 −1.00% / 債券 −1.84% → 乖離 **+0.84pt** → **株を売り債券を買う圧力**。

`note` に「デュレーション 8 での近似。実際の年金比率と規模は非公開」と明記する。

### 3-2. パーセンタイル基盤（全画面に効く）

```python
def contextualize(series, value, lookback=1250):
    s = series.tail(lookback)
    return {
      "value": value,
      "pct_rank": round((s < value).mean()*100),
      "z": round((value - s.mean())/s.std(), 2),
      "d20_change": round(series.diff(20).iloc[-1], 4),
      "d20_z": round((series.diff(20).iloc[-1] - series.diff(20).tail(lookback).mean())
                     / series.diff(20).tail(lookback).std(), 2),
    }
```

実測: 10 年利回り 4.71% = **5 年で 98 パーセンタイル**。20 営業日変化 +30bp、z = +0.95。

**「4.71%」だけでは何も分からない。全数値に自分の履歴の中での位置を付ける。**
天秤を壊すのは水準ではなく**速度**。`d20_z` が +2 を超えたら画面に警告を出す。

### 3-3. 3 地域構成

```json
{
  "regions": {
    "us": {"equity":"^GSPC",     "real_yield":"DFII10", "nominal":"DGS10",
           "term_premium":"THREEFYTP10", "yields":["US2Y","US10Y","US30Y"]},
    "eu": {"equity":"^STOXX50E", "real_yield":null,     "nominal":"EU10Y",
           "term_premium":null,          "yields":["EU2Y","EU10Y","EU30Y"]},
    "jp": {"equity":"^N225",     "real_yield":null,     "nominal":"JP10Y",
           "term_premium":null,          "yields":["JP2Y","JP10Y","JP30Y"]}
  }
}
```

**EU / JP には実質金利とターム・プレミアムの無料日次系列がない。** `null` にして画面に「名目のみ・米国と非対称」と明示する。**米国だけ層が厚い非対称を隠さない。**

営業日が違う（日本の祝日／米国の祝日／TARGET 休業日）ので**必ず日付の inner join**。`"align": "inner_join"` を JSON に明記する。

### 3-4. 描画（新タブ「利回り×株価」）

既存の inline SVG 方式を踏襲。外部チャートライブラリを追加しない。既定は 3 地域同時表示。

- 上段: 株価（左軸・実線 `var(--accent)`）と **実質金利**（右軸・実線 `var(--yellow)`）。名目は破線でトグル
- 中段: 120 日ローリング相関 + レジームラベル
- 下段: 感応度ベータ棒グラフ（3 指数）
- サイドバー: 四半期末リバランス圧力、パーセンタイル、`d20_z`
- キャプション: `r(120d)` `n_obs` `as_of` `align` `data_status`
- 免責: `For data visualization purposes only. Not investment advice.`

### 完了条件

3 地域すべてで系列と相関が表示され、US は実質金利ベース、EU/JP は名目 + 非対称の明示。ERP は「未実装」表示。commit `feat(relations): add yield-equity balance layer (real yield, regime, beta, rebalance flow)`。**push しない。**

---

## Agent 4: ガンマ層（オプション・ディーラー建玉）

### 4-1. データ源（無料・認証不要・実測確認済み）

```
https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json
```

29,420 契約、13 MB（gzip 後 1.7 MB）。**gamma / delta / open_interest / volume / iv が最初から入っている。** ブラック・ショールズを自前で解く必要はない。

補助（CBOE 公開 CSV）:

```
https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv
https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv
```

### 4-2. スナップショット（既に稼働中・重複実装しない）

`~/taka-automation/bin/snapshot_cboe.sh` が launchd（火〜土 06:30 JST）で稼働済み。
保存先 `~/taka-data/cboe-chains/SPX-YYYY-MM-DD.json.gz`。
**Agent はこのスクリプトを再実装しない。読み取り側だけ書く。**

```python
CHAIN_DIR = os.path.expanduser("~/taka-data/cboe-chains")
def load_chain(date_str):
    with gzip.open(f"{CHAIN_DIR}/SPX-{date_str}.json.gz") as f:
        return json.load(f)
```

### 4-3. GEX 計算（実測済みコード）

```python
import re, math, json
from datetime import date
from collections import defaultdict
from scipy.stats import norm

PAT = re.compile(r'^SPXW?(\d{6})([CP])(\d{8})$')

def parse_chain(d, today):
    S = d['data']['close']; recs = []
    for x in d['data']['options']:
        m = PAT.match(x['option'])
        if not m: continue
        ymd, cp, k = m.groups()
        exp = date(2000+int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        T = max((exp-today).days/365.0, 1/365)
        oi = x.get('open_interest') or 0
        if oi <= 0: continue
        recs.append((cp, int(k)/1000.0, T, x.get('iv') or 0,
                     x.get('gamma') or 0, oi, x.get('volume') or 0))
    return S, recs

def gex_at(recs, spot, r=0.038):
    """慣習的仮定: ディーラーはコール買い / プット売り"""
    tot = 0.0
    for cp, K, T, iv, g, oi, vol in recs:
        if iv <= 0 or T <= 0: continue
        d1 = (math.log(spot/K) + (r + iv*iv/2)*T) / (iv*math.sqrt(T))
        gam = norm.pdf(d1) / (spot*iv*math.sqrt(T))
        v = gam * oi * 100 * spot * spot * 0.01
        tot += v if cp == 'C' else -v
    return tot

def zero_gamma(recs, S, lo_mult=0.85, hi_mult=1.15):
    lo, hi = S*lo_mult, S*hi_mult
    if gex_at(recs, lo) * gex_at(recs, hi) >= 0: return None
    for _ in range(40):
        mid = (lo+hi)/2
        if gex_at(recs, lo) * gex_at(recs, mid) < 0: hi = mid
        else: lo = mid
    return (lo+hi)/2

def gamma_walls(recs, S, bucket=25, top=10):
    by = defaultdict(float)
    for cp, K, T, iv, g, oi, vol in recs:
        v = g * oi * 100 * S * S * 0.01
        by[round(K/bucket)*bucket] += v if cp == 'C' else -v
    return sorted(by.items(), key=lambda x: -abs(x[1]))[:top]
```

実測結果（2026-07-25 05:10、SPX 7,411.98、建玉ありの 21,330 契約）:

| 項目 | 値 |
|---|---|
| 総 GEX | **−235 億ドル / 1% 変動** |
| ゼロガンマ（フリップ）水準 | **≈ 7,455** |
| 最大の負ガンマ壁 | 7,400（−157 億ドル） |
| 正ガンマ側 | 7,600 以上 |

読み: **現値はフリップより下＝増幅ゾーン。** ガンマが負のときディーラーは下落で売り上昇で買う → 動きを増幅する。正なら打ち消す（値が貼り付く）。

### 4-4. 必ず画面に出す前提条件（省略禁止）

```json
{"assumption": "naive_dealer_convention",
 "note": "ディーラーがコール買い/プット売りという慣習的仮定に基づく。CBOEは売買主体を公開していない。仮定が外れると符号が反転する。"}
```

**この注記を書かない GEX 表示が、この指標が胡散臭く見える原因になっている。必ず出す。**

### 4-5. 0DTE の分離

実測で建玉のある契約のうち約 70% が 0DTE。**建玉ベースの GEX は寄り引けで消える 0DTE の影響を過小評価する。** 日中の増幅は建玉ではなく出来高側に出るため、

- `gex_oi`（建玉ベース）
- `gex_volume_0dte`（当日満期の出来高ベース）

を**分けて出力する。合算しない。**

### 4-6. 地域の非対称を明示

日経オプションは JPX が建玉を出すがギリシャ文字がなく、Eurex も同様。**ガンマ層は実質的に米国限定。**
`{"coverage": {"us": "full", "eu": "unavailable", "jp": "unavailable"}}` を明記し、画面にも「この層は米国のみ」と出す。日欧米を揃える要求とは両立しない。

### 4-7. ボラ構造（CBOE CSV）

- `VIX3M / VIX` 比 → コンタンゴ（>1、平常）/ バックワーデーション（<1、ストレス）
- `SKEW` → テールの値段
- `MOVE / VIX` 比 → **両方 `data.json` に既にあるのに比率がない。** 金利ボラと株ボラのどちらが主犯かを示す

### 完了条件

`docs/gamma.json` に総 GEX・ゼロガンマ・壁上位 10・0DTE 分離・仮定注記・地域カバレッジが揃う。生チェーンは公開しない（集計値のみ、400 KB 未満）。commit `feat(gamma): add dealer gamma exposure layer from CBOE public chain`。**push しない。**

---

## Agent 5: 検証・契約・CI・レポート

### 5-1. 契約テスト `tests/test_contract.py`

```python
import os, glob, json
D = json.load(open("docs/data.json"))

def test_payload_budget():
    assert os.path.getsize("docs/data.json") < 400_000
    assert sum(os.path.getsize(p) for p in glob.glob("docs/charts/*.json")) < 5_000_000
    assert os.path.getsize("docs/gamma.json") < 400_000

def test_every_row_has_link():
    for market, rows in D["markets"].items():
        for r in rows:
            assert "link" in r and "kind" in r["link"], f"{market}/{r['symbol']}"

def test_no_yahoo_for_non_ticker():
    BAD = ("_IMM", "BUFFETT", "JP2Y", "JP10Y", "JP30Y", "EU2Y", "EU10Y", "EU30Y")
    for market, rows in D["markets"].items():
        for r in rows:
            if any(b in r["symbol"] for b in BAD):
                assert "finance.yahoo.com/quote/" not in r["link"]["url"], r["symbol"]

def test_vix_move_are_quote_links():
    for r in D["markets"]["volatility"]:
        if r["symbol"] in ("VIX", "MOVE"):
            assert r["link"]["kind"] == "quote", r["symbol"]

def test_rates_three_regions():
    assert {r["region"] for r in D["markets"]["rates"]} == {"US", "JP", "EU"}

def test_fisher_identity():
    M = json.load(open("docs/macro.json"))
    assert M["identities"]["fisher"]["ok"], M["identities"]["fisher"]

def test_relations_uses_real_yield_for_us():
    R = json.load(open("docs/relations.json"))
    assert R["regions"]["us"]["real_yield"] == "DFII10"
    assert R["regions"]["us"]["data_status"] == "live"
    for k in ("us", "eu", "jp"):
        assert len(R["regions"][k]["series"]) >= 200, k
    assert R["align"] == "inner_join"

def test_erp_marked_unavailable_not_blank():
    R = json.load(open("docs/relations.json"))
    e = R["balance"]["erp"]
    assert e["data_status"] == "unavailable" and e.get("reason")

def test_gamma_assumption_disclosed():
    G = json.load(open("docs/gamma.json"))
    assert G["assumption"] == "naive_dealer_convention" and G.get("note")
    assert "gex_oi" in G and "gex_volume_0dte" in G      # 合算していないこと
    assert G["coverage"]["jp"] == "unavailable"

def test_chart_status_enum():
    for market, rows in D["markets"].items():
        for r in rows:
            assert r.get("chart_status") in ("ready", "pending", "unavailable")

def test_percentile_context_present():
    M = json.load(open("docs/macro.json"))
    for key in ("DGS10", "DFII10", "BAMLH0A0HYM2", "NFCI"):
        c = M["series"][key]["context"]
        assert "pct_rank" in c and "z" in c and "d20_z" in c
```

### 5-2. 健全性ゲート `tools/health_gate.py`

```python
THRESHOLDS = {
  "us_rates": ("FAIL", 3),  "jgb": ("FAIL", 5),  "ecb": ("FAIL", 5),
  "fred_daily": ("FAIL", 4),
  "boj_assets": ("WARN", 45),   # 構造的遅延。FRED:JPNASSETS 側の制約
  "imm": ("WARN", 12),          # CFTC COT は週次
  "cboe_chain": ("FAIL", 4),
}
```

FAIL が 1 つでも出たら:
1. 画面最上部に赤帯（`PASS` 緑 / `WARN` 黄 / `FAIL` 赤）
2. **`docs/data.json` を上書きしない**（古い正常データを残す）
3. GitHub Actions を exit 1 で止める

### 5-3. リンク死活 `tools/check_links.py`

全 `link.url` に HEAD を投げる。**Yahoo には 2 秒以上の待機を必ず挟む**（実測で HTTP 429 を踏んだ）。
CI では**警告のみ**。レート制限による誤検知で fail させない。結果は Obsidian にレポート出力。

### 5-4. 判断ログ `docs/decisions.jsonl`（append-only）

```yaml
- date: 2026-07-25
  observation: "10Y 4.71%(5年98%tile) / 実質2.43 / TP 0.78 / 相関120d -0.41 / GEX -235億(フリップ7455)"
  reading: "実質金利は高位だが天秤は機能中。ディーラーは負ガンマで増幅ゾーン"
  falsifier: "相関が +0.20 を超えたら『天秤が機能している』という読みは外れ"
  review_date: 2026-10-25
```

**`falsifier` が本体。** これがないと都合のいい記憶だけが残る確認バイアス装置になる。
`review_date` 到来時に `health_gate` が WARN を出す。

### 5-5. `DATA_CONTRACT.md` 更新

記載必須:

- 新スキーマ（`link` / `chart_status` / `macro.json` / `relations.json` / `gamma.json`）
- 容量予算（上記の表）
- **株式の 4h / 1w を提供しない理由**（全被覆で約 18 MB）
- ERP が `unavailable` である理由（無料日次 EPS ソース不在、Shiller ミラーは 2024-09 停止）
- ガンマ層が米国限定である理由（JPX / Eurex はギリシャ文字非公開）
- EU / JP に実質金利とターム・プレミアムがない理由
- GEX の慣習的仮定と、それが外れた場合の影響
- yfinance 由来データは Yahoo 利用規約上「個人利用」想定である旨
- ECB / FRED / MoF / CFTC / CBOE の出典と再利用条件を分けて記載
- 「本サイトは無償であり、投資顧問契約に基づく助言を行わない」

### 5-6. Obsidian レポート

`~/Obsidian/taka-automation/hf-signal-dashboard/2026-07-25-v2-report.md`

- 変更ファイル一覧、`git diff --stat`
- リンク切れ件数（修正前 20 → 修正後）
- `docs/data.json` サイズ（1,308,034 B → ?）
- チャート被覆率（7.9% → ?）
- 新規層（macro / relations / gamma）の系列数と `data_status`
- 未解決の残課題

### 完了条件

```bash
cd /Users/takahiroyamada/hf-signal-dashboard && python3 -m pytest tests/ -q
```

全件通過。commit `test(contract): add v2 guards for payload, links, identities, gamma assumptions`。
**停止し、人間に push 可否を問う。**

---

## 実行順序と検証ゲート

```
Agent 1 (基盤)
   ↓
Agent 2 (マクロ層取込)  ──┐
                          ├→ Agent 3 (天秤層)  ──┐
Agent 4 (ガンマ層) ───────┘                      ├→ Agent 5 (検証)
                                                  ┘
                                                       ↓
                                              人間ゲート → push
```

- Agent 1 完了まで他は着手しない（`docs/` 分割の形が決まらないため）
- Agent 2 と Agent 4 は依存関係がないので並行可
- Agent 3 は Agent 2 の `DFII10` / `THREEFYTP10` が揃ってから
- **各 Agent 完了ごとに `python3 -m pytest tests/ -q` を実行。通らなければ次に進まない**

## 未解決として残す（バグではなく未実装。画面に `placeholder` バッジで区別する）

| 項目 | 理由 |
|---|---|
| ERP（株式リスクプレミアム） | 無料の日次指数 EPS が存在しない。Shiller ミラーは 2024-09 停止 |
| EU / JP の実質金利・ターム・プレミアム | 無料日次系列なし |
| EU / JP のディーラーガンマ | JPX / Eurex がギリシャ文字を公開していない |
| `JP_BUFFETT_INDICATOR` | 日本の時価総額/GDP の安定した無料日次ソース未特定 |
| EU debt / JP debt | Eurostat / MoF の四半期系列が未接続 |
| BoJ 総資産（53 日遅延） | FRED:JPNASSETS の更新頻度そのものの制約 |
| 株式の 4h / 1w | 容量予算超過のため意図的に非提供 |
| ブレッドス（均等 vs 時価総額加重、200 日線超え比率） | v3 候補。**SP500 103 銘柄を既に保持しているため追加取得ゼロで実装可能** |
| 株価指数先物の CFTC 建玉 | v3 候補。IMM は FX のみ |
| 銅金比率 | v3 候補 |
| `elliott`（全銘柄 `unknown`） | ヒューリスティックのプレースホルダ。撤去か「未実装」明示かを別途判断 |

## 環境の注意

mini の Python は macOS 同梱の 3.9（`NotOpenSSLWarning` / LibreSSL 2.8.3）。urllib3 v2 系はサポート外。
**v2 の作業に入る前に Homebrew Python へ切り替えるか決めること。作業途中で環境を変えると原因切り分けが壊れる。**
`scipy` が未導入なら Agent 4 の前に導入が必要（`norm.pdf` を使用）。
