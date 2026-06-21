# SPEC_LOOP.md — 過学習を物理的に防ぐ 5 仮説 ループ (Phase 1.9.2)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: Phase 1.9.1 で `H1 open_to_close` が 4 ゲート全滅して撤退判断となった上で、
> 「288 線および指数モメンタムの **指数限定** 転用」を 5 仮説で 1 回ずつ評価し、
> Phase 1.9.1 の頑健性ゲート (cost / outlier / subperiod / fade-skew) を通る仮説が
> **存在するか否か** を確認する。
>
> ★禁止事項 (違反したら設計失敗):
>   - 同一仮説のパラメータを自動で書き換えて「通るまで再試行」しない (p-hacking)
>   - 1 仮説 = 1 試行。試行数で合格ラインを吊り上げる (DSR / PBO)
>   - **直近 2 年は一発ホールドアウト**。開発系から物理ブロック
>   - 個別株は対象外。指数 / 先物 / FX のみ
>   - 全試行を改竄不能ハッシュチェーンログに記録 (Phase 1.6 の Chain 思想を再利用)

---

## 0. ユニバース (指数限定)

```
ALLOWED_SYMBOLS = {
  # 指数 (現物 / 先物の代用)
  "^N225", "^GSPC", "^DJI", "^NDX",
  # ボラ系
  "^VIX", "^MOVE",
  # 金利 (米長期)
  "^TNX", "^TYX",
  # 主要 FX
  "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "EURJPY=X",
}
```

`BTC-USD` / `ETH-USD` は **対象外** (crypto は別問題)。
個別株は **対象外** (混入したらテスト failure)。

---

## 1. 一発ホールドアウト (物理ブロック)

```
HOLDOUT_START = (today - 2 years)         # 2026-06-21 実行時 = 2024-06-21
```

- すべての仮説評価で `bars = [b for b in bars if b.ts < HOLDOUT_START]` を loop.runner
  の **入口で物理的に削る**。
- テスト `test_loop_holdout_block` で:
  - HOLDOUT_START 以降の bar を含む全期間 list を渡しても、loop.runner.run_trial が
    返す trades の ts はすべて HOLDOUT_START より小さい。
  - 各仮説の predict 関数に「最大 ts 監視 list」を渡し、HOLDOUT_START 以降を
    1 度でも読んだら AssertionError。
- 開発フェーズ (= 本 SPEC を含むすべての試行) では、ホールドアウト区間にアクセス
  できない。一発検証のときだけ別ファイル `loop/holdout_eval.py` (本 Phase では未実装)
  を作って評価する設計。

---

## 2. 5 仮説 登録簿 (各 1 行の理論根拠必須)

| ID | 名前 | 予測ルール (固定) | 理論根拠 (1 行) |
|---|---|---|---|
| HA | `288_cross` | close が 288MA を上抜けで long, 下抜けで short | 288 日 ≈ 1 年。長期 MA クロスは大型機関のリバランス節目 (Fama-French momentum literature) |
| HB | `288_slope` | 288MA の 5 日前比が正なら long, 負なら short | MA 傾きは "trend persistence" の最小限の指標 (Hong-Stein 2007) |
| HC | `288_band` | close が 288MA + 2σ 超で short (mean revert), -2σ 未満で long | Bollinger Band on 1Y window — 長期 σ から逸脱は平均回帰候補 (Lehmann 1990 mean-reversion) |
| HD | `index_tsmom` | 過去 60 日リターン符号で direction (long if past>0) | Time-series momentum, Moskowitz-Ooi-Pedersen 2012 (12 month TSMOM, 我々は 60 日へ短縮) |
| HE | `regime_tsmom` | HD と同じだが「close > 288MA」のときだけ取引 (リスクオフでは何もしない) | regime filter は "trend in trend" を捕える (Faber 2007 Tactical Asset Allocation) |

★パラメータ (288, 5, 2σ, 60) は **固定**。後で書き換えない。
書き換える場合は SPEC を書き直して新試行として登録 (= 試行数 +1)。

---

## 3. ループフロー (Agent 2 `loop/runner.py`)

```python
def run_loop(symbols=None, holdout_start=None, ...):
    universe = symbols or sorted(ALLOWED_SYMBOLS)
    # 1. 物理ブロック: holdout 以降は load 時点で削る
    bars_by_sym = {s: filter_pre_holdout(load(s), holdout_start) for s in universe}
    trials = []
    for hypothesis in REGISTRY:           # 順に 1 回ずつ
        all_trades = []
        for s, bars in bars_by_sym.items():
            trades = run_one(hypothesis, bars, symbol=s)
            all_trades.extend(trades)
        verdict = evaluate_4_gates(all_trades) + dsr_pbo
        log_to_chain(hypothesis, verdict)
        trials.append({hypothesis, verdict, ...})
    return aggregate_report(trials)
```

- 同一仮説に対する 2 度目の `run_one` は呼ばない (テストで保証)。
- 各 trade は close-to-close 1-bar-fwd return: `realized = (close[t+1]-close[t])/close[t] * sign(direction) * 100`.
- 4 ゲート評価は既存 `backtest.h1_robustness` を再利用 (cost_sensitivity, outlier_sensitivity,
  subperiod_table, fade_summary)。

---

## 4. 過学習制御 (Agent 3 `loop/overfit.py`)

### 4.1 Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014 簡略版)

```
SR_raw = mean(net_pct) / std(net_pct) * sqrt(252)
expected_max_SR(N) ≈ sqrt(2 * ln(N))  # for N trials with N~Normal(0,1) SRs
DSR_adj = SR_raw - expected_max_SR(N_trials)
```

判定: `DSR_adj > 0` で「多重検定補正後も平均的に edge あり」と暫定判定。
N=5 仮説の場合 `expected_max_SR ≈ sqrt(2*ln 5) = 1.794`。

### 4.2 PBO (Probability of Backtest Overfitting) 簡略版

各仮説について:
1. trades を時間順に半々に分割
2. 前半 SR vs 後半 SR の符号
3. 一致 = overfit ではない / 不一致 = overfit 候補

仮説空間 5 件の PBO = 不一致仮説数 / 全仮説数。

### 4.3 試行数で吊り上がる合格閾値

| 試行数 | DSR 合格 | PBO 合格 |
|---|---|---|
| 1 | DSR > 0 | (PBO 評価せず) |
| 2-5 | DSR > 0 | 仮説の PBO 符号一致 |
| 6+ | DSR > 0.5 | PBO < 0.30 |

本 Phase は 5 試行なので **DSR > 0 かつ 半々分割で符号一致** が合格。

---

## 5. 改竄不能ログ (Phase 1.6 思想再利用)

`data/local/loop_trials.jsonl` に試行を append-only で書き込む。
`prev_hash + canonical_json(payload) → sha256 → curr_hash` のチェーン。
ファイルは `.gitignore` 済 (data/local/)。

`loop.log.append_trial(payload)` を新設 (notify.chain と同一思想だがスキーマ別)。

---

## 6. レポート (Agent 4)

`docs/data/loop_report_public.json` に:
- 試行ごとに: name / params / n_trades / hit_rate /
  cost_table (5/10/20bps) / outlier_table / subperiod_table /
  fade_summary / SR_raw / DSR / pbo_sign_consistent / verdict
- 集計: `frontier = [(hit_rate, skew) for trial]`
  (「高 hit 率は負スキュー側にしか無い」現象の可視化)

ターミナルにも同等の要約を JSON 出力。

---

## 7. 受け入れ条件 (PR 本文へ転写)

1. 5 仮説 (HA-HE) が REGISTRY に登録され、各 1 行の理論根拠を持つ。
2. 同一仮説の自動パラメータ探索が存在しない (`test_loop_no_autotuning`)。
3. 直近 2 年ホールドアウトが物理ブロックされている (`test_loop_holdout_block`)。
4. 4 ゲート + DSR + PBO 半々一致 で各仮説を判定。
5. 全試行が `data/local/loop_trials.jsonl` (リポ外) にハッシュチェーン記録される。
6. 個別株未混入 (`test_loop_universe_indices_only`)。
7. Phase 1〜1.9.1 回帰なし。
8. **最終 1 行判定**:
   - 4 ゲート全 PASS かつ DSR>0 の仮説あり → `"transfer-candidate-survived: <name> (要・一発ホールドアウト確認)"`
   - 全滅 → `"empty-set under current gate → 指数転用は防御止まり / 転用Completion-B"`
