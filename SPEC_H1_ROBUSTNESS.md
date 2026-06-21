# SPEC_H1_ROBUSTNESS.md — H1 `open_to_close` 頑健性分析 (Phase 1.9.1)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: Phase 1.9 で唯一トレード可能な `open_to_close` ラベル (since_2023 で edge と
> 判定された EV CI [+0.012, +0.157]) が、(I) **本物の取引可能エッジ** か、
> (II) **fat-tail 人工物** か、(III) **危険な負スキュー fade** か、を判定する。
>
> ★本フェーズで **新仮説 (H2-H10) も学習も実装しない**。
> ★既存 H1 実装 (Phase 1.9) の出力 trades に対する頑健性分析のみ。
> ★`overnight` は参考表示のみ (取引不能の確認用)、`next_week` は対象外。

---

## 0. 大原則

- 既存 `backtest.h1` の `build_features` / `compute_labels` を再利用 (look-ahead
  禁止は構造保証済)。 trades 生成のみ薄く再構築する `backtest.h1_robustness` を新設。
- 学習禁止: `tests/test_no_learning_code` の grep が `backtest/+collector/` を継続検査。
- GRC: 「想定 + 頑健性検証 / not investment advice」を panel/JSON 上部に明示。
- Phase 1 〜 1.9 回帰なし。既存 203 テスト緑のまま。

---

## 1. EV 単位の定義 (Agent 1)

Phase 1.9 の trades の `net_pct` は:

```
realized_pct = label_value * sign(feature) * 100
```

ここで `label_value` は **小数のリターン** (`open_to_close = (close-open)/open`)。
従って `realized_pct` は **実 % リターン** (例: 0.080 = 0.08% / 1 トレード)。

往復コスト (bid-ask + 手数料 + スリッページ) は **%** で表現:

| 水準 | bps round-trip | % round-trip | 想定 |
|---|---|---|---|
| optimistic | 5 bps | 0.05% | ETF/先物の機関級 (1306/MNK 先物) |
| realistic | 10 bps | 0.10% | リテール ETF (1306/1321) 通常 |
| conservative | 20 bps | 0.20% | 個別株バスケット or リテール最悪 |

コスト控除後:

```
net_after_cost = realized_pct - cost_pct
```

3 水準で個別に bootstrap CI を算出。

### 1.1 JP_open の約定現実性

- ^N225 の open は **JP 板寄せ (9:00 JST)** の実取引価格。
- ETF (1306/1321) は同時に板寄せで約定可能 → open 価格を約定価格として使うのは妥当。
- 先物 (大証 NK225 mini など) は朝 8:45 開始だが板厚あり → 同等扱い可。
- 個別株バスケット組成は約定タイミングがズレるため上記対象外。
- 本分析では「JP open ≈ 約定可能価格、ただしリテールではスリッページ + 手数料が乗る」
  という前提を SPEC に明記し、JSON にも `executable_assumption` フィールドで記録。

---

## 2. 外れ値除外 (Agent 2)

`realized_pct` の絶対値で上位 1% / 5% を除外して再算出。

- 除外後でも EV CI が **完全正側** なら fat-tail 由来でない。
- 除外で EV が **消える / 反転** なら fat-tail 人工物のフラグを立てる。

---

## 3. サブ期間安定性 (Agent 3)

`since_2023` を年単位で分割: 2023 / 2024 / 2025 / 2026 (累計バー数に応じて)。
各サブ期間で `mean(realized_pct)` と簡易 CI を算出 (バー数が少ない場合は CI のみ非表示)。

判定:
- ある **1 サブ期間が全体の EV の > 50%** を占めるなら 「単一期間依存」 フラグ。
- もしくは ある サブ期間 で `mean(realized_pct)` が **負** なら不安定フラグ。

---

## 4. fade 戦略 + スキュー / テール (Agent 4)

fade 戦略 = US 符号の **逆** に賭ける:
```
fade_realized = label_value * (-sign(feature)) * 100
```

算出する 4 統計:
- `hit_rate_fade`
- `mean(fade_realized)`
- `skew` (Fisher-Pearson, 母集団近似): `mean((x-μ)/σ ** 3)`
- `max_dd_pct` (equity curve from cumulative `fade_realized`)
- `worst_day_loss_pct` (最小 `fade_realized` の 1 日損失)

判定:
- `skew < -0.5` → 中程度の負スキュー、`< -1.0` → 強い負スキュー (survival 原則違反)
- `worst_day_loss_pct < -5%` → 1 日で大損失の前科あり、リスク許容を超える可能性
- `(d) PASS` = `skew >= -0.5` かつ `worst_day_loss_pct >= -5%`

---

## 5. 統合判定 (Agent 5)

`open_to_close` (since_2023) について 4 条件を `pass/fail` で判定:

| 条件 | PASS 条件 |
|---|---|
| (a) コスト | 5bps / 10bps / 20bps **全て** で コスト控除後 EV 95% CI 下限 > 0 |
| (b) 外れ値 | top 1% 除外後 & top 5% 除外後 **両方** で EV 95% CI 下限 > 0 |
| (c) サブ期間 | 単一サブ期間に EV 過集中していない (no single > 50%) **かつ** 負期間 0 |
| (d) fade スキュー | fade の `skew >= -0.5` **かつ** `worst_day_loss_pct >= -5%` |

**最終判定**:
- (a) AND (b) AND (c) AND (d) すべて PASS → `"Stage2-conditioners-justified"`
- 1 つでも FAIL → `"raw-cross-asset-not-tradeable → Completion-B候補"`

出力:
- `docs/data/h1_robustness_public.json`
- ターミナル `python3 -m backtest.cli --hypothesis=h1-robustness --source=local`

---

## 6. CI / pytest (Agent 5 結線)

| ファイル | 目的 |
|---|---|
| `tests/test_h1_robustness_costs.py` | cost 控除式 / 3 水準 CI / 単位整合 |
| `tests/test_h1_robustness_outliers.py` | 外れ値除外で trade 数が想定通り減る / CI 再計算 |
| `tests/test_h1_robustness_subperiods.py` | 年単位分割 / 単一期間集中検知 |
| `tests/test_h1_robustness_fade_skew.py` | fade 計算 / skew/maxDD/worstday |
| `tests/test_h1_robustness_verdict.py` | (a)(b)(c)(d) → 最終判定 2 値 |

既存 Phase 1〜1.9 (203 件) は緑のまま。

---

## 7. 受け入れ条件 (PR 本文へ転写)

1. EV 単位を実 % に変換、5/10/20bps 感度表が出る。
2. 上位 1%/5% 除外で EV CI が消える/反転するかをフラグ。
3. since_2023 を年分割し各期間 EV を出す。単一期間集中をフラグ。
4. fade 版の hit/EV/skew/maxDD/worstday を算出、負スキュー判定。
5. (a)(b)(c)(d) 判定テーブルを公開 JSON とターミナルに出力。
6. 既存 Phase 1〜1.9 回帰なし、学習コード未追加。
7. **最終 1 行判定** を report に明示 (Stage2 or Completion-B候補)。
