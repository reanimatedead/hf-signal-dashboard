# SPEC_BACKTEST.md — Walk-Forward 予測精度ハーネス + データ厚盛り (Phase 1.7)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: 「予測 vs 実レート」を **時間順 out-of-sample** で答え合わせし、
> 過学習を構造で排除する。学習 (Phase 2) と勝敗自動判定 (Phase 3) は本フェーズで実装しない。
>
> 今夜のゴール: **配線疎通** (仮装データで e2e 緑、実データ検証は明日 backfill 後)。

---

## 0. 大原則

- **過学習禁止**: in-sample fit を「成績」と呼ばない。
  時間順 out-of-sample (walk-forward) のみを実力とする。
  在 in-sample と out-of-sample の **両方を並列表示** し、乖離 (overfit gap) を可視化。
- **look-ahead 厳禁**: バー i 時点の予測は `bars[0..i]` のみ参照。
  `bars[i+1:]` を 1 度でも触れたらテスト失敗 (監視 list で物理保証)。
- **理想約定にしない**: スリッページ + 手数料を **必ず** 控除。
- **天井クランプを仮想にも適用**: `survival.risk_engine.HARD_CAPS["PER_TRADE_PCT_MAX"]=0.5%`
  をシミュレータのポジションサイズに強制。
- **小標本では判定保留**: 各 fold の評価サンプル数 N<30 で「judge=undetermined」を返す。
  Bootstrap CI が 0 を跨ぐ場合も同様。
- **全 keyless / リポ汚染禁止**: 市場データは yfinance / FRED CSV など既存ソース。
  個別トレード履歴と DuckDB は `data/local/` (.gitignore 済)。
- **Phase 1 / 1.5 / 1.6 への回帰なし**: 既存 141 テスト緑のまま。

---

## 1. backtest/ パッケージ構成

| ファイル | 役割 |
|---|---|
| `backtest/__init__.py` | パッケージ説明のみ |
| `backtest/walk_forward.py` | anchored / rolling 分割 + purge + embargo + look-ahead 監視 |
| `backtest/simulator.py` | 1 fold の仮想取引実行 (slip / fee / HARD_CAPS 強制) |
| `backtest/metrics.py` | hit_rate / Brier 分解 / EV / maxDD / bootstrap CI / undetermined 判定 |
| `backtest/cli.py` | `python3 -m backtest.cli` で仮装データ or 実履歴を流して結果 JSON 出力 |

---

## 2. walk-forward (Agent A, `walk_forward.py`)

### 2.1 API

```python
splits = walk_forward.make_splits(
    n_bars,
    mode="anchored" | "rolling",
    train_min=200,                 # 最初の fold までに最低この本数
    test_window=40,                # 1 fold の test 長さ
    rolling_train_window=400,      # rolling 時の train 長さ (anchored 無視)
    purge=5,                       # train 末尾 - test 先頭 のラベル重複緩衝
    embargo=5,                     # test 直前を train から除外する追加緩衝
)
# splits: list[Split{train_start, train_end, test_start, test_end}]
```

### 2.2 ルール

- `anchored`: 各 fold で `train = [0, anchor]`、`test = [anchor + purge + embargo + 1, anchor + purge + embargo + test_window]`。
  anchor は train_min から始まり、毎 fold で `test_window` 進む。
- `rolling`: `train = [anchor - rolling_train_window, anchor]`、test は同じ。
- `purge` + `embargo` でラベル重複リークを断つ。両方 0 は禁止 (`ValueError`).

### 2.3 look-ahead 監視 (テスト保証)

`walk_forward.run_fold(bars, split, predict_fn, evaluator)` の中で、`predict_fn` には
**監視 list でラップした bars** を渡す。`predict_fn` が `train_end` を越える index を読んだ瞬間
`AssertionError`。テスト `test_walk_forward.test_predict_fn_cannot_peek_future` で検知。

---

## 3. 仮想トレード実行 (Agent B, `simulator.py`)

### 3.1 API

```python
result = simulator.simulate_fold(
    test_bars,           # [{ts, open, high, low, close}, ...]
    signals,             # [{bar_index, direction, predicted_prob, pattern}, ...]
                         # bar_index は test_bars の index (0..len-1)
    pattern_table,       # survival.pattern_table.DEFAULT_PATTERN_TABLE
    slip_pct=0.05,       # 片道スリッページ %
    fee_pct=0.02,        # 片道手数料 %
    size_pct=0.5,        # 仮想サイズ (天井クランプ強制)
)
# returns {
#   "trades": [{entry_bar, exit_bar, side, entry_price, exit_price,
#                gross_pct, net_pct, predicted_prob, outcome01, kind}, ...],
#   "equity_curve": [1.0, 1.0+..., ...],
#   "max_dd_pct": -3.2,
#   "n_trades": int,
# }
```

### 3.2 ルール

- entry 価格: `signal` のバー close × (1 + side*slip_pct/100)。
- exit 価格: TP/SL/TIMEOUT 到達バー close × (1 - side*slip_pct/100)。
- realized: `(exit - entry) / entry * 100` × side。
- net = realized - 2*fee_pct - 2*slip_pct (注意: スリッページは価格に既に乗ってるので fee だけ追加)。
  実装では entry/exit を slip 込みで計算済 → net = gross - 2*fee_pct で十分。
- size_pct = `min(size_pct, HARD_CAPS["PER_TRADE_PCT_MAX"]=0.5)` 強制。
- 同時保有 = `MAX_CONCURRENT=3` 強制。

### 3.3 結果保存

- `data/local/backtest/<run_id>.jsonl` に append (リポ外)。
- 集計は metrics.py に渡す。

---

## 4. 予測精度・較正 (Agent C, `metrics.py`)

### 4.1 API

```python
m = metrics.summarize(trades, predicted_probs, outcomes01,
                      bootstrap_runs=1000, ci=0.95, n_min=30)
# returns {
#   "n": int,
#   "judge": "ok" | "undetermined",   # N<n_min か CI が 0 を跨ぐと undetermined
#   "hit_rate": <0..1>,
#   "brier": <float>,
#   "brier_decomposition": {"reliability": <f>, "resolution": <f>, "uncertainty": <f>},
#   "calibration": [{"bin": [low, high], "n": <int>, "pred_mean": <f>, "obs_rate": <f>}, ...],
#   "avg_net_pct": <f>,
#   "avg_net_pct_ci": [<lo>, <hi>],
#   "ev_ambiguous": <bool>,   # CI が 0 を跨ぐ
#   "max_dd_pct": <f>,
# }
```

### 4.2 ルール

- **N<30** → judge="undetermined"、サンプル数不足の警告のみ表示。
- **CI が 0 を跨ぐ** → ev_ambiguous=True かつ judge="undetermined" (実力不明)。
- **Brier 分解**: Murphy decomposition.
  - `Brier = Reliability − Resolution + Uncertainty`
  - 0.1 刻みの 10-bin で reliability / resolution を計算。
- **較正曲線** (calibration table): 10-bin の (pred_mean, obs_rate) を返す。
- bootstrap: trades を 1000 回 with-replacement リサンプリングして avg_net_pct の分布を作る。

### 4.3 in-sample vs out-of-sample

`metrics.summarize_pair(is_trades, oos_trades, ...)` は両方を計算し:

```python
{
  "in_sample": {...},
  "out_of_sample": {...},
  "overfit_gap": {
    "hit_rate":  is.hit_rate - oos.hit_rate,
    "brier":     oos.brier   - is.brier,           # OOS が悪化する向きを正
    "avg_net":   is.avg_net_pct - oos.avg_net_pct
  }
}
```

UI は両者を並べ、`overfit_gap > 一定` で黄色フラグ。

---

## 5. データ厚盛り CLI (Agent D, `collector/backfill.py`)

### 5.1 目的

各銘柄について **取得可能な最長期間** を一括 download し、`data/local/history.duckdb`
(or `data/local/history_<sym>.jsonl` fallback) に保存。明日以降の walk-forward の
fold 数を稼ぐ。

### 5.2 CLI

```sh
python3 -m collector.backfill                       # 既定: 主要シンボル全部、1d 最長
python3 -m collector.backfill --symbols=^N225,USDJPY=X
python3 -m collector.backfill --period=10y --interval=1d
python3 -m collector.backfill --intervals=1d,1wk    # 複数 timeframe
python3 -m collector.backfill --dry-run             # 計画だけ表示
```

### 5.3 ルール

- **keyless**: yfinance のみ。429/5xx は exponential backoff (collector.runtime.retry を再利用)。
- **冪等**: 同銘柄を 2 回流しても重複行ゼロ (date,interval,symbol を一意キーに正規化)。
- **部分失敗許容**: 単一銘柄の失敗で全体落とさない。失敗は collect_log.jsonl に行追加。
- **DuckDB optional**: `import duckdb` 成功時は `data/local/history.duckdb` の `bars` テーブルへ。
  失敗時は `data/local/history_<sanitized_sym>.jsonl` に書く (fallback)。テストは両ルートを通る。
- **容量監視**: data/local の利用量と空き容量を確認、空き < 20GB で WARN を stderr に出す。
- **進捗 JSON 出力**: `data/local/backfill_progress.json` に `{symbol: {bars, first_ts, last_ts, status}}` を書く。

### 5.4 SURVIVAL UI 連携

- `docs/data/backfill_progress_public.json` (公開抜粋) を SURVIVAL タブが fetch して表示。
- 表示要素: 銘柄数 / 累計バー数 / カバー期間 (min..max) / ストレージ使用量。
- 公開抜粋では symbol リストを伏せても良い (size と range だけでも可)。

---

## 6. UI: SURVIVAL の追加パネル

- `#sv-backtest`: 直近の backtest run 結果サマリ
  (IS / OOS の hit/Brier/EV/maxDD/judge、CI が 0 を跨ぐ場合は赤)。
- `#sv-backfill`: 収集進捗 (銘柄数 / バー数 / カバー期間 / 残容量)。

両者とも `docs/data/<name>_public.json(l)` を fetch。
ファイルが無ければ「履歴蓄積中」と表示し、配線が落ちないこと。

---

## 7. CI / pytest (Agent E)

| ファイル | 目的 |
|---|---|
| `tests/test_walk_forward.py` | anchored/rolling split 数 / purge+embargo 効く / look-ahead 監視 list が検知 |
| `tests/test_backtest_simulator.py` | スリッページ + 手数料控除 / 天井クランプ強制 / TP/SL/TIMEOUT 発火 |
| `tests/test_backtest_metrics.py` | Brier 分解の恒等式 / N<30 で undetermined / CI が 0 を跨ぐ判定 / IS/OOS 並列 |
| `tests/test_backfill_cli.py` | CLI 起動可能 / 冪等 (2 回実行で同じ jsonl) / 部分失敗で例外送出しない / DuckDB optional |
| `tests/test_backtest_e2e_smoke.py` | 仮装データ (固定 seed の random walk) で walk_forward → simulator → metrics が e2e 緑 |

既存 Phase 1 / 1.5 / 1.6 のテスト (141) は **緑のまま**。

---

## 8. 明日 (実データ投入) の手順

```sh
# 1. データ厚盛り (90 分〜数時間かかる)
python3 -m collector.backfill --period=max --interval=1d 2>&1 | tee data/local/backfill.log
# (任意) 4h / 1wk も埋めたい場合
python3 -m collector.backfill --intervals=1d,4h,1wk

# 2. backtest を実データで実行
python3 -m backtest.cli --source=duckdb --symbols=auto \
        --mode=anchored --train-min=400 --test-window=60

# 3. SURVIVAL タブを開いて #sv-backtest, #sv-backfill を確認 (履歴蓄積中 → 数値表示に切替)

# 4. judge=ok の銘柄だけ実トレード投入を検討する (Phase 3)
```

---

## 9. 受け入れ条件 (PR 本文へ転写)

1. 仮装データで walk_forward → simulator → metrics が e2e で回り、IS と OOS の両方が出る。
2. overfit_gap が surfaced されている (UI / metrics 出力に存在)。
3. スリッページ + 手数料控除 / 天井クランプ / look-ahead 厳禁 がテストで保証。
4. `python3 -m collector.backfill` で最大履歴をローカル DuckDB / jsonl fallback に蓄積する CLI が動く。
5. data/local/ は .gitignore 済。トレード履歴 / DB がコミットされない。
6. Phase 1 / 1.5 / 1.6 / HARD_CAPS / 既存タブ 回帰なし。Phase 2 / 3 未実装。
7. not investment advice / 環境可視化 文言維持。
