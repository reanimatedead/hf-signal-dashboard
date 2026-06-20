# SPEC_SURVIVAL.md — 生存ループ / リスク自動設計 / 破産シミュレータ (Phase 1)

> 本ファイルは **テスト/実装より先にコミットされる**。
> 「死なない土台」と「嘘発見器」を Phase 1 で確立する。
> Phase 1 は **学習しない**。固定天井で殺さない。値はシステムが算出。人間入力ゼロを目標。

---

## 0. 設計哲学 (固定)

- **External-condition-independent**: 損切り / 追証 / DD 天井は外部状況で動かない固定絶対線。
- **% 基準内部表現**: 全ての risk は % で持つ。絶対額は `config.local` の初期残高定数を掛ける表示層のみ。
- **公開リポに損益/残高を書かない**: 個別取引結果は `localStorage`、`config.local` は `.gitignore` 経由。
- **Phase 1 では学習しない**:
  - 重み再学習・レジーム自動切替は実装しない。
  - リスクの「数値」は算出するが、損切り/追証/DD 天井は固定 (`HARD_CAPS`)。
  - 利確 (upside) は「マイデイリー微更新」で小さく動く。**下振れ側は更新禁止 (非対称)**。
- **GRC**: 全画面で "Macro environment visualization / not investment advice" を維持。
  執行助言テキスト・買い/売り推奨・TP/SL の指示形は出さない。

---

## 1. 固定天井 (HARD_CAPS, コードで強制)

`survival/risk_engine.py` の最上部に定数として固定。テストで天井超え提案は弾かれる。

| 項目 | 値 | 性質 |
|---|---|---|
| `PER_TRADE_PCT_MAX` | **0.5%** | 1 トレード許容リスク上限 (固定) |
| `DD_SHRINK_PCT` | **-10.0%** | この DD で全モード自動縮小 |
| `DD_STOP_PCT` | **-15.0%** | この DD で全モード停止 |
| `MAX_CONCURRENT` | **3** | 同時保有上限 (固定) |
| `TARGET_VOL_PCT` | **1.0%** | 逆ボラスケーリングの参照ボラ |
| `KELLY_FRACTION` | **0.25** | 1/4 Kelly 固定 |

- これらは **学習しない**。値そのものは年単位で見直す前提だが、本 Phase で自動的に動かない。

---

## 2. リスク自動設計 (Agent C, `survival/risk_engine.py`)

人間入力ゼロで以下を毎日算出する。

### 2.1 1 トレード許容リスク

```
per_trade_pct = min(PER_TRADE_PCT_MAX,
                    TARGET_VOL_PCT / realized_vol_pct * BASE)
BASE = 0.5  (固定)
```

`realized_vol_pct` は全シンボルの ATR/price 平均から推定 (Phase 1)。

### 2.2 ポジションサイズ (Kelly × 逆ボラ)

```
full_kelly = (b*p - q) / b           # b=win_loss_ratio, p=win_prob, q=1-p
size_pct   = max(0, full_kelly * KELLY_FRACTION) * (TARGET_VOL_PCT / realized_vol_pct) * 100
size_pct   = clamp(size_pct, 0.0, PER_TRADE_PCT_MAX)
```

- `win_prob` は **Brier 較正後の勝率推定**。本 Phase は履歴が無いため `0.50` (固定の不可知的推定) で動く。
- `win_loss_ratio` は `take_profit_pct / abs(stop_loss_pct)` をパターン表から計算。

### 2.3 DD 状態判定

```
peak_to_current = (current - peak) / peak * 100
state = "stop"   if peak_to_current <= DD_STOP_PCT     (= -15)
      | "shrink" if peak_to_current <= DD_SHRINK_PCT   (= -10)
      | "normal" otherwise
```

### 2.4 同時保有上限 (相関調整)

```
avg_abs_corr = 候補ペアの |相関| 平均
slots = round(MAX_CONCURRENT * (1 - avg_abs_corr))
slots = clamp(slots, 1, MAX_CONCURRENT)
```

### 2.5 証拠金シミュレータ

- 口座 API なし前提。`leverage_x = 0` (現物相当) を既定。
- `maint_margin_ratio = position_notional_pct / equity_pct`。`>= 80%` で警告。
- レバを使う場合の感応度 (1×, 2×, 3×) を併記 (執行助言ではない)。

---

## 3. パターン別利確テーブル (Agent D, `survival/pattern_table.py`)

### 3.1 構造

```
key = (regime, distortion)
  regime ∈ {"high_vol","low_vol"}    # 直近ボラの大小
  distortion ∈ {"high","mid","low"}  # 歪み度 (stretch)
value = {
  "take_profit_pct": float,   # >0
  "stop_loss_pct":  float,    # <0, 固定
}
```

初期値は **ボラ比例**。`DEFAULT_PATTERN_TABLE` で定義。

### 3.2 デイリー微更新ルール (上振れ側のみ)

```
for each cell with new realized results:
    new_tp = current_tp * 0.9 + avg_realized_tp * 0.1   # EWMA 10% pull
    new_tp = clamp(new_tp, MIN_TP_PCT=0.5, MAX_TP_PCT=6.0)
    cell.take_profit_pct = new_tp
    # stop_loss_pct は絶対に触らない (固定下振れ)
```

- 取り逃しは構わない、緩めれば死ぬ、という **非対称性** を構造で固定する。
- `daily_update` のテストで `stop_loss_pct` 不変であることを保証。

---

## 4. survival_loop ブロック (data.json トップレベル)

```jsonc
{
  "meta": {...},
  "summary": {...},
  "markets": {...},
  "money_flow": {...},
  "survival_loop": {
    "as_of": "<ISO UTC>",
    "version": "1",
    "risk_gate": {
      "label": "risk-on" | "neutral" | "risk-off",
      "color": "green"   | "yellow"  | "red",
      "score": <int>,
      "reasons": [<string>...]
    },
    "auto_risk": {
      "per_trade_pct": <float, <= 0.5>,
      "max_concurrent": <int, <= 3>,
      "dd_shrink_pct": -10.0,
      "dd_stop_pct":   -15.0,
      "target_vol_pct": 1.0,
      "realized_vol_pct": <float>,
      "source": "inverse_vol_scaling, kelly_quarter (Phase 1)"
    },
    "pattern_table": {
      "<regime>|<distortion>": {"take_profit_pct": <f>, "stop_loss_pct": <f<0>}
    },
    "candidates": [
      {
        "symbol": "...",
        "market": "...",
        "name": "...",
        "stretch": <float|null>,
        "positioning_fuel": <float|null>,
        "vol_context_pct": <float|null>,
        "edge_score": <0..100>,
        "data_status": "live|placeholder|stale|unknown",
        "as_of": "..."
      }
    ],
    "mode_a_positions": [
      {
        "symbol": "...",
        "direction": "long"|"short",
        "entry_date": "YYYY-MM-DD",
        "entry_edge_score": <int>,
        "pattern": {"regime":"...","distortion":"..."},
        "exit": {"take_profit_pct": <f>, "stop_loss_pct": <f>},
        "size_pct": <f, <= 0.5>,
        "data_status": "...",
        "note": "Mode A virtual entry (machine). Not advice."
      }
    ],
    "mode_b_note": "Discretionary candidates. Recorded client-side (localStorage).",
    "mode_c_note": "A/B comparison ledger. Verdict in Phase 3.",
    "bankruptcy_simulation": {
      "trades": <int>, "runs": <int>,
      "win_prob_used": <f>, "win_loss_ratio_used": <f>,
      "risk_grid": [
        {"risk_pct": <f>, "ror_mc": <f, 0..1>, "ror_kaufman": <f|null>}
      ],
      "balances_pct_basis": [300, 400, 500],
      "note": "% 空間で計算。残高違いは絶対額表示のみに影響。"
    },
    "notes": [
      "Hard caps in survival.risk_engine.HARD_CAPS (no learning).",
      "Stop loss / margin call / DD ceilings are fixed. Not adjusted by daily_update.",
      "Phase 1: no model learning, no regime auto-switch.",
      "Market environment visualization only. Not investment advice."
    ]
  }
}
```

### 4.1 候補抽出

- 全シンボル (`nikkei225/dow30/nasdaq100/sp500/fx`) から `edge_score` を算出。
- `edge_score >= 60` の上位 20 件を `candidates` に積む。
- うち `edge_score >= 70` 上位 3 件を `mode_a_positions` (Phase 1 仮想エントリ)。

### 4.2 取得不能 = placeholder

- `rsi/bb_pct/cci/atr/price` のいずれかが null のシンボルは `stretch=null`、
  `edge_score=null` を許す。`data_status="placeholder"` を維持。

---

## 5. SURVIVAL タブ (Agent A, 既定表示)

- タブ id: `survival`。`#tabs` の **先頭**。クリックなしで初期表示。
- 配置 (上から):
  1. **本日の一文** (risk-on/off/neutral, 1 単語 + 色) ＋ 1 行の根拠 (VIX/Fed/curve)。
  2. **自動リスク設定カード** (`per_trade_pct` / `max_concurrent` / DD 余力 (% baseline 100)
     / 維持率) — 全て自動算出値、人間入力なし。
  3. **候補リスト** (`edge_score` 降順, 上位 8 件)。各行に `direction` ヒント / pattern / exit %。
  4. **Mode B 1 タップ記録** (各候補に [採用] [見送り] ボタン、`localStorage` に保存)。
  5. **モンテカルロ破産ヒートマップ** (リスク% × 取引数; RoR 0..1 を色で)。
  6. **集計** (直近の的中率 / 平均 ROI / 簡易 Brier / パターン別勝率) - localStorage から計算。
  7. **パターン別利確テーブル** (現在値; 下振れは固定の薄色表示)。
- 全画面に `not investment advice / 環境可視化` を常時表示。

### 5.1 localStorage キー (公開リポに値を書かない)

- `hf_survival_log_v1`: 配列。各要素 = `{date, symbol, direction, mode("B"|"C"), action("taken"|"skipped"), outcome("win"|"loss"|"flat"|null), rr, pattern, memo}`
- `hf_survival_settings_v1`: ユーザのローカル既定 (任意, Phase 1 では未使用)。

### 5.2 アグリゲーション

クライアント側で以下を計算 (`survival_aggregate.js`):
- `hit_rate` = wins / (wins + losses)
- `avg_roi_pct` = mean(realized_pct)
- `brier` = mean( (predicted_prob - outcome01)^2 ); predicted_prob は edge_score/100 をそのまま
- `pattern_win_rates` = pattern key 別の wins / total

---

## 6. 既存 9 タブ構成 (Phase 1)

| # | tab_id | 既定 |
|---|---|---|
| 1 | **survival** | ◯ 既定 |
| 2 | nikkei225 | |
| 3 | dow30 | |
| 4 | nasdaq100 | |
| 5 | sp500 | |
| 6 | fx | |
| 7 | rates_vol | |
| 8 | pos_val | |
| 9 | moneyflow | |

- 旧 既定 `nikkei225` の active 初期状態を `survival` に振り替え。
- 既存タブの描画/データは無改変 (素材として残す)。

---

## 7. CI / テスト (Agent E)

- cron `0 15 * * *` (00:00 JST) を維持。
- pytest 追加:
  - `tests/test_risk_ceiling.py`: 任意の入力で `auto_risk()` の返り値が `PER_TRADE_PCT_MAX` を超えないこと、DD ≦ -15% で `dd_state == "stop"` 返却を保証。
  - `tests/test_pattern_table_invariants.py`: `daily_update` 前後で全セルの `stop_loss_pct` が不変、
    `take_profit_pct` は `[MIN_TP, MAX_TP]` にクランプされること。
  - `tests/test_survival_loop_schema.py`: `data.json.survival_loop` の必須キーと値域。
  - `tests/test_bankruptcy_simulator.py`: 期待値 0 の戦略で RoR ≈ 1.0、edge > 0 戦略で RoR < 1.0
    の不等式を確認。乱数は `random.seed` で固定。
- CI に pytest 追加。`fetch_signals.py` の単一 ticker 失敗で全体破綻しない。
- API キー無し。値が無い場合は `data_status="placeholder"` で value=null。

---

## 8. 受け入れ条件 (PR 本文へ転写)

1. 起動既定が SURVIVAL。最上部に本日の一文 (risk 色) + 自動リスク + 候補が 3 秒で読める。
2. `data.json.survival_loop` に 3 モードの仮想ポジション/edge_score/data_status。
3. リスク数値が人間入力ゼロで自動算出。`per_trade<=0.5%`, DD `-10%` 縮小 / `-15%` 停止 がコードで強制 + ユニットテストで証明。
4. 利確がパターン別テーブル、デイリーは上振れのみ微更新、損切り/追証/DD 天井は不変 (テスト保証)。
5. モンテカルロ破産シミュレータが複数残高シナリオで RoR を提示。残高手入力不要。
6. 結果ログが `localStorage`、的中率/ROI/Brier/パターン別勝率自動集計。公開リポに損益/残高無し。
7. リスクゲートが header に結線。`money_flow` が判断入力に使用。
8. cron `0 15 * * *`、pytest 緑、1 ticker 失敗で全体落ちず、API キー無し、捏造値無し。
9. 既存 8 タブ/検索/CSV/JA-EN/Dark/背景アニメ/SVG 回帰なし。
10. "not investment advice" 維持。執行助言テキスト無し。学習 / レジーム自動切替は未実装 (Phase 1 スコープ厳守)。
