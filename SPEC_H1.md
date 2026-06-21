# SPEC_H1.md — 単一仮説 H1 「US→日本オーバーナイト波及」 / 単独 walk-forward 検証 (Phase 1.9)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: 「前セッションの US 終値リターンが、日本株の翌オーバーナイト方向を同符号で予測する」
> という単一仮説 (H1) のみを実装し、素の予測力を walk-forward で測る。
>
> ★ **H2〜H10 は本フェーズで実装しない** (多重検定・無限ビルド防止)。
> ★ **学習 (Phase 2) も実装しない**。固定仮説の単発測定のみ。

---

## 0. 大原則 (硬い柱)

- **H1 のみ実装**。H2〜H10 (他仮説) は本フェーズで実装しない。
  テスト `test_h1_only.py` が `backtest/` 配下に `h2.py..h10.py` 等が存在しないことを構造保証。
- **学習禁止**。`test_no_learning_code` を流用し H1 でも検知。
- **look-ahead 禁止 (最重要)**: バー T (JST) 時点の特徴量は **「JP date T より厳密に過去」の
  US 終値のみ** を使う。同日 US 終値 (US date T close = JST 翌朝 06:00) を 1 度でも触れたら
  テスト fail。物理保証は「特徴量を pre-compute → predictor は precomputed feature dict のみ
  参照 → US 生バーは触れない」のレイヤーで成立する。
- **3 ラベル定義** (固定):
  1. `overnight` = `(JP_open[T] - JP_close[T-1]) / JP_close[T-1]`
  2. `open_to_close` = `(JP_close[T] - JP_open[T]) / JP_open[T]`
  3. `next_week` = `(JP_close[T+5] - JP_close[T]) / JP_close[T]` (5 営業日先)
- **2 セグメント分割** (固定): `pre_2023` (JP date < 2023-01-01) と `since_2023`
  (JP date >= 2023-01-01)。BOJ 正常化前後の構造断絶を別評価する。
- **サニティチェック** (リサーチの定性予測の再現確認):
  - `overnight` 上で US 前日リターンとの Pearson 相関が **正かつ |t| > 2** → PASS
  - `open_to_close` 上で同相関が **|r| < 0.10 かつ |t| < 2.5** → PASS
  - これが出なければデータのタイムゾーン/整列が壊れている (= 信号以前の問題)。
  両セグメントで個別に判定し、UI と JSON に明示する。
- **GRC**: SURVIVAL の H1 パネルに「単一仮説の素の予測力測定 / not investment advice」を
  最上部に明示。トレード/損益はリポに置かない (data/local/ は既存 .gitignore 済)。
- **Phase 1〜1.8 への回帰なし**: 既存 183 テスト緑のまま。

---

## 1. 特徴量 (Agent A, `backtest/h1.py: build_features`)

```python
us_returns = build_us_close_returns(us_bars)        # {us_date_str: close_to_close_return}
features   = build_features(jp_bars, us_returns)    # {jp_date_str: us_prev_return}
```

ルール:
- US 銘柄 = `^GSPC`。jsonl/duckdb から既存 `local_loader` で読み込み (重複除去・昇順整列済)。
- 各 JP date T (JST) に対し、 `us_date = max(us_dates)` where `us_date < T_jp` の close_return を使う。
  - 例: JP 2024-01-08 (月) → US 2024-01-05 (金) の close return。
  - 同日 US (例 JP 2024-01-08 → US 2024-01-08) は **使わない** (US close は JST 翌朝 06:00 確定)。
- US 側で「最初の close return」(初日) は計算不能 → そのキーは無し → 対応する JP date は特徴量無しとなり除外。

### 1.1 look-ahead 物理保証 (テスト `test_h1_feature_lookahead.py`)

- `build_features` を呼んだ後、US バーのうち `ts >= T_jp` を全削除 / 改竄しても、特徴量
  dict が変化しないことをアサート。
- predictor は features dict だけを引数に受け取り、US 生バーには触れない (型シグネチャで保証)。

---

## 2. 3 ラベル (Agent B, `backtest/h1.py: compute_labels`)

各 JP バー i について 3 ラベルを計算:

| label | formula | 欠損条件 |
|---|---|---|
| `overnight` | `(open[i] - close[i-1]) / close[i-1]` | i=0 |
| `open_to_close` | `(close[i] - open[i]) / open[i]` | open<=0 |
| `next_week` | `(close[i+5] - close[i]) / close[i]` | i+5 >= n |

ラベルは features と同じ ts でキー化される dict.

---

## 3. walk-forward + 集計 (Agent B/C, `backtest/h1.py: run_h1`)

```python
result = run_h1(jp_symbol="^N225", us_symbol="^GSPC",
                segments=(("pre_2023", None, "2023-01-01"),
                          ("since_2023", "2023-01-01", None)),
                bootstrap_runs=300, n_min=30)
```

- JP 銘柄: 既定 `^N225` (将来 `1306.T` 等を切り替え可、本フェーズは `^N225` のみ動作確認)。
- 既存 `walk_forward.make_splits` で時系列分割 (anchored, purge+embargo).
- segment フィルタは「JP 日付」で行う。
- ラベルごとに `metrics.summarize` を呼び `hit_rate/Brier/avg_net_pct_ci/judge` を取得.
  - `judge` は `backtest.cli._classify_judge` (Phase 1.8) を再利用。

### 3.1 EV の意味

予測方向 = `sign(feature)`。realized = `label_value * sign(prediction)`。
EV CI は realized の bootstrap CI (1000 回。コスト無し / 純粋な forecast 精度)。
これは「トレード可能か」ではなく「単一特徴の素の予測力があるか」を測る指標。
SPEC 上「想定トレード戦略の EV」とは別物 (Phase 1.8 は後者、本 H1 は前者)。

### 3.2 サニティチェック

```python
sanity = {
  "overnight":      {"pearson": <r>, "t": <t>, "n": <int>, "pass": bool},
  "open_to_close":  {"pearson": <r>, "t": <t>, "n": <int>, "pass": bool},
  "next_week":      {"pearson": <r>, "t": <t>, "n": <int>, "pass": bool},
}
```

- `pass` の判定:
  - `overnight`: `r > 0` かつ `|t| > 2` (US beta が正で有意)
  - `open_to_close`: `|r| < 0.10` かつ `|t| < 2.5` (ほぼ無相関)
  - `next_week`: 評価のみ。pass / fail のラベルは付けない (期待値が無いため)。

---

## 4. CLI 結線 (Agent C, `backtest/cli.py`)

```sh
python3 -m backtest.cli --hypothesis=h1 --source=local
python3 -m backtest.cli --hypothesis=h1 --source=local --jp-symbol=^N225 --us-symbol=^GSPC \
       --bootstrap-runs=300
```

出力:

```jsonc
{
  "ok": true, "as_of_utc": "...",
  "hypothesis": "h1",
  "jp_symbol": "^N225", "us_symbol": "^GSPC",
  "segments": [
    {"name": "pre_2023", "from": null, "to": "2023-01-01",
     "n_jp_bars": <int>, "n_with_feature": <int>,
     "sanity": {<3-labels above>},
     "labels": {
       "overnight":     {<metrics.summarize 全フィールド + judge>},
       "open_to_close": {...}, "next_week": {...}
     }},
    {"name": "since_2023", ...}
  ],
  "note": "Single-hypothesis raw predictive-power measurement. Not investment advice."
}
```

公開抜粋を `docs/data/h1_summary_public.json` に書く。詳細は `data/local/h1/<run_id>.json`
(リポ外)。

---

## 5. SURVIVAL UI (Agent D, `backtest_panel.js`)

`#sv-backtest` の直下に H1 パネル領域を追加 (既存 v4.6 live 表示は壊さない):
- ヘッダ「H1 単独検証: US 前日リターン → 日本 オーバーナイト」
- 2 セグメント × 3 ラベル のテーブル (n / hit / Brier / EV CI / judge 色分け)。
- サニティチェック結果 (3 ラベル、PASS は緑バッジ / FAIL は赤バッジ)。
- "Single-hypothesis raw predictive-power measurement. Not investment advice." を上部に明示。
- 公開ファイル不在時は「H1 未実行」を表示 (落とさない)。

---

## 6. CI / pytest (Agent E)

| ファイル | 目的 |
|---|---|
| `tests/test_h1_feature_lookahead.py` | 同時/未来 US バーを改竄しても features が不変 (look-ahead 物理保証) |
| `tests/test_h1_labels.py` | overnight / open_to_close / next_week のラベル式と欠損規則 |
| `tests/test_h1_e2e.py` | 仮想 JP/US データで run_h1() が 2 segment × 3 labels + sanity を返す |
| `tests/test_h1_only.py` | `backtest/h2..h10.py` が存在しない (H1 のみ) + 学習混入 grep |

既存 183 件は緑のまま (回帰なし)。

---

## 7. 受け入れ条件 (PR 本文へ転写)

1. H1 のみ実装 (H2-H10 未実装をテストで担保). 学習コード未追加.
2. 特徴量は前日 US 終値リターンのみ. 同時/未来データ不使用を `test_h1_feature_lookahead` で物理保証.
3. `overnight / open_to_close / next_week` の 3 ラベルで hit/Brier/EV 95% CI/folds 算出.
4. サニティチェック: overnight で US beta 正・有意, open_to_close でほぼ無相関 (予測の再現).
5. `pre_2023` と `since_2023` の 2 セグメントで別々に judge 分類.
6. Phase1-1.8/HARD_CAPS/既存タブ 回帰なし. not advice 維持.
7. ★ **実走後 3 ラベル × 2 セグメントの EV 95% CI 位置** を明示報告.
