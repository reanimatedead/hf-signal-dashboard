# SPEC_BACKTEST_LIVE.md — 実レート結線 / システム単体の想定精度測定 (Phase 1.8)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: Phase 1.7 で配線した walk-forward ハーネスを `data/local/history_*.jsonl`
> (and / or `data/local/history.duckdb`) の **実レート OHLC** に流し、
> 銘柄別 & 全体の **想定精度** を測る。**自分の実トレード結果は使わない**。
> Phase 2 (学習 / 重み更新) は **実装しない**。Phase 2 着工可否は本フェーズの結果を見てから判断。

---

## 0. 大原則

- **測定のみ**: 学習 / 重み更新 / モデル fit 等のコードを追加しない。
  テスト `test_no_learning_code.py` が `backtest/` と `collector/` 配下を grep し、
  `sklearn`, `torch`, `tensorflow`, `xgboost`, `.fit(`, `train(` 等のキーワード混入を
  検知して失敗する。
- **look-ahead 厳禁**: 既存 `backtest.walk_forward.WatchedBars` を必ず経由。
  バー i 時点の判定は `bars[:i+1]` のみ参照。
- **理想約定にしない**: `simulator.simulate_fold` で slip / fee を控除。
- **天井クランプ**: `survival.risk_engine.HARD_CAPS["PER_TRADE_PCT_MAX"]=0.5%` を size に強制。
- **捏造禁止**: バーが不足する銘柄は `judge="insufficient_data"` で除外し集計に入れない。
- **GRC**: SURVIVAL UI の `#sv-backtest` 表に
  「これは想定精度であり実トレード結果ではない / not advice」を必ず表示。
- **Phase 1〜1.7 回帰なし**: 既存 169 テスト緑のまま。
- **data/local は git 管理外** (.gitignore 済)。実レート jsonl / 結果 jsonl を公開しない。

---

## 1. ローカルデータローダ (Agent A, `backtest/local_loader.py`)

### 1.1 入力

- 既定: `data/local/history.duckdb` が存在すれば DuckDB の `bars` テーブル.
- 無ければ `data/local/history_*_<interval>.jsonl` をスキャン。
- ファイル名規則: `history_<sanitized_symbol>_<interval>.jsonl`
  (collector.backfill が書く形と一致 — `_sanitize()` で `.` を `_` に置換済 → 銘柄名復元は jsonl 内 `symbol` フィールドを優先).

### 1.2 API

```python
loaded = local_loader.load_all(interval="1d",
                               min_bars=400,                # walk-forward に必要な最低本数
                               source="auto" | "duckdb" | "jsonl")
# loaded = {
#   "interval": "1d",
#   "source_used": "duckdb" | "jsonl",
#   "symbols": {
#       "USDJPY=X": {"bars": [{"ts","open","high","low","close","volume"}, ...],
#                    "n": int, "first_ts": "...", "last_ts": "..."},
#       ...
#   },
#   "excluded": {
#       "<sym>": {"reason": "insufficient_data", "n": int, "min_required": int}, ...
#   },
# }
```

### 1.3 正規化ルール

- 各銘柄を `ts` 昇順にソート。
- (symbol, ts) で重複行を除去 (最新の close を採用).
- `close` が None / 非数値の行は弾く。
- `n < min_bars` の銘柄は `excluded` に入れて `symbols` には出さない (捏造しない).

---

## 2. 実レート walk-forward (Agent B, `backtest/cli.py --source=local`)

### 2.1 サブコマンド

```sh
python3 -m backtest.cli --source=local
python3 -m backtest.cli --source=local --interval=1d --mode=anchored \
       --train-min=400 --test-window=80 --purge=5 --embargo=5 \
       --slip-pct=0.02 --fee-pct=0.01 --size-pct=0.5
python3 -m backtest.cli --source=local --symbols=USDJPY=X,EURUSD=X
```

### 2.2 ルール

- 銘柄ごとに `walk_forward.make_splits` → `run_fold(predict_fn = 既存 _predict)` → `simulate_fold` → 銘柄別 trades.
- 銘柄横断で trades を連結し、全体メトリクスを 1 セット計算。
- IS と OOS を両方算出 (既存 `metrics.summarize_pair`).
- 既存 `_predict` (過去 10 本リターン → 方向、`predicted_prob=0.55` 固定) を **そのまま** 使用。
  これは "システム単体の素の精度" の測定。Phase 2 で予測器を差し替える前段。

### 2.3 judge 分類 (per-symbol + overall)

| judge | 条件 |
|---|---|
| `edge` | `N >= 30` かつ 95% CI 下限 > 0 |
| `no-edge` | `N >= 30` かつ 95% CI 上限 < 0 |
| `inconclusive` | `N >= 30` かつ CI が 0 を跨ぐ |
| `insufficient` | `N < 30` |

`metrics.summarize` 既存出力 (`judge`, `ev_ambiguous`) を解釈する薄いラッパで実装。

### 2.4 出力

```jsonc
{
  "ok": true,
  "as_of_utc": "<ISO>",
  "source_used": "jsonl",
  "interval": "1d",
  "fold_config": {"mode":"anchored","train_min":400,"test_window":80,"purge":5,"embargo":5},
  "exec_config": {"slip_pct":0.02,"fee_pct":0.01,"size_pct":0.5},
  "per_symbol": [
    {"symbol":"USDJPY=X","n_bars":7686,"folds":52,
     "in_sample":{...},"out_of_sample":{...},
     "overfit_gap":{...},
     "judge":"edge|no-edge|inconclusive|insufficient",
     "calibration":[...]},
    ...
  ],
  "excluded": [
    {"symbol":"X","n_bars":120,"min_required":400,"reason":"insufficient_data"}
  ],
  "overall": {
    "n_symbols": <int>,
    "n_excluded": <int>,
    "in_sample":{...},
    "out_of_sample":{...},
    "overfit_gap":{...},
    "judge":"edge|no-edge|inconclusive|insufficient",
    "calibration":[...]
  },
  "note": "想定精度のみ / not investment advice. Phase 2 (学習) 未実装."
}
```

- 公開抜粋を `docs/data/backtest_summary_public.json` に書く (Phase 1.7 既存ファイルを上書き).
- 詳細結果は `data/local/backtest/<run_id>_live.json` に保存 (リポ外).

---

## 3. 想定精度メトリクス (Agent C)

既存 `backtest.metrics` で完結:

- `hit_rate`, `brier`, `brier_decomposition`, `calibration` (10 bins),
  `avg_net_pct`, `avg_net_pct_ci` (bootstrap 1000), `max_dd_pct`, `judge`.
- 全銘柄連結の overall 集計には `summarize_pair` を流用.
- Phase 1.8 はこれ以上の指標を増やさない (測定先行).

---

## 4. SURVIVAL UI 更新 (Agent D)

### 4.1 `#sv-backtest` 拡張

`docs/assets/survival/backtest_panel.js`:
- 既存 IS/OOS テーブル + overfit_gap + EV CI を全体 summary として残す。
- **per_symbol テーブル** を下に追加。列:
  `symbol | n_bars | folds | OOS hit | OOS Brier | OOS EV CI | judge`.
  judge の色分け: 緑=`edge` / 灰=`inconclusive` / 赤=`no-edge` / 薄字=`insufficient`.
- excluded 銘柄も末尾に小さく列挙 (insufficient_data の透明性).
- **較正曲線** を全体 OOS の calibration から SVG で描画 (バー数 = bin の n に比例).
- 「これは想定精度であり実トレード結果ではない / not investment advice」 を最上部の disclaimer に追加。

公開ファイル: `docs/data/backtest_summary_public.json` (per_symbol + overall + 較正データ含む abridged).

---

## 5. 学習コード未追加の担保 (Agent E)

`tests/test_no_learning_code.py`:
- `backtest/`, `collector/` 配下の `.py` を全 ASCII 検査 (UTF-8 OK).
- 禁止語: `sklearn`, `torch`, `tensorflow`, `xgboost`, `keras`, `lightgbm`, `catboost`,
  `\.fit(`, `\.train(`, `loss\.backward`, `optimizer\.`, `model\.compile`, `gradient`,
  `learn_rate`, `learning_rate`.
- いずれかが見つかったら fail。
- コメント中の "learning" 等は許す (`# learning is not implemented`).
  → 文字列リテラル / docstring も対象だが、許容パターン `"not implemented"`, `"Phase 2"`,
  `"# noqa: learning"` を含む行は除外。
- `survival/`, `notify/`, `pipeline/`, `tests/` は対象外 (Phase 2 は別ディレクトリで作る前提).

---

## 6. CI / pytest (Agent E)

| ファイル | 目的 |
|---|---|
| `tests/test_local_loader.py` | jsonl 読込 / 重複除去 / min_bars 未満は excluded |
| `tests/test_backtest_live.py` | 仮想 jsonl で `cli.run_local()` が e2e で動く / judge 分類 |
| `tests/test_no_learning_code.py` | 学習語の混入を検知 |

既存 Phase 1〜1.7 (169 件) は緑のまま (回帰なし).

---

## 7. 受け入れ条件 (PR 本文へ転写)

1. `python3 -m backtest.cli --source=local` が 14 万行 jsonl から想定精度を出す.
2. 銘柄別 + 全体で hit_rate / Brier / EV 95% CI / DD / fold 数 + judge 分類.
3. IS / OOS 並列 + overfit_gap, look-ahead リーク無し (テスト保証).
4. slip / fee 控除 + 天井クランプ, 薄い銘柄は `insufficient_data` で除外.
5. 自分の実トレード未投入 (本フェーズ範囲外), 学習コード未追加 (test_no_learning_code).
6. Phase 1〜1.7 回帰なし. not advice 維持.
7. **全体 EV 95% CI がどこにあるか (正側/0またぎ/負側) を実行ログとして報告**.

---

## 8. Phase 2 判断のためのチェックリスト (運用メモ, 実装スコープ外)

- overall judge = `edge` (CI 全正側) → Phase 2 でこの予測器を強化する価値あり.
- overall judge = `inconclusive` (CI 0 跨ぎ) → 予測器の入れ替えが必要.
- overall judge = `no-edge` (CI 全負側) → slip/fee/ロジック設計の見直しが先.
- overall judge = `insufficient` → backfill を延長して bar 数を稼ぐ.
