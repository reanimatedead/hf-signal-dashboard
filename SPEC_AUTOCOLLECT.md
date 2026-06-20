# SPEC_AUTOCOLLECT.md — 週末全自動データ収集機 (Phase 1.5)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> Phase 1 で完成した survival_loop の入力サンプルを「週末放置で月曜朝に貯まっている」状態を作る。
> Phase 2 (学習) / Phase 3 (勝敗判定) は **本フェーズで実装しない**。枠だけ用意する。

---

## 0. 大原則

- **人間の手作業ゼロ**: cron 駆動。push 後は完全自走。
- **keyless / 規約順守**: yfinance / FRED CSV / fiscaldata / CFTC COT / CoinGecko / MoF。
  robots / 利用規約に沿った User-Agent + 礼儀的レート制御。スクレイピング先のサーバ負荷に配慮。
- **捏造禁止**: 取得不能 = null / placeholder。collect_log に「どのソースが落ちたか」を残す。
- **耐障害性**: 1 ソース失敗で全体破綻させない (既存方針踏襲)。
- **冪等**: 同日 cron 再実行でも history が重複しない (上書きでなく "最新で正規化")。
- **GRC**: not investment advice 維持。個人損益/残高は config.local / localStorage のみ。
- **Phase 1 への回帰なし**: HARD_CAPS / survival_loop の動作・テストは触らない。
- **Phase 2/3 未実装**: 学習・勝敗判定ロジックは作らない。コメントで `TODO(phase-3)` 明記。

---

## 1. cron スケジュール (Agent A)

`.github/workflows/collect.yml` を **新規追加** (既存 `update_signals.yml` は触らない)。

| 名称 | cron (UTC) | 意図 |
|---|---|---|
| 金曜 0 時 JST | `0 15 * * 5` | 金曜 0:00 JST = 木曜 15:00 UTC … いや、JST=UTC+9 なので **JST 金曜 0:00 = UTC 木曜 15:00**。<br/>本仕様の「金土日 0 時 JST」を満たすには UTC で 木曜・金曜・土曜の 15:00 を打つ。<br/>そのため **cron は `0 15 * * 4,5,6`** とする。 |
| 月曜 3 時 JST | `0 18 * * 0` | 月曜 3:00 JST = 日曜 18:00 UTC = `0 18 * * 0` ✓ |

> 注: 要件「金土日 0 時 JST」を素直に解釈すると曜日は JST 基準で金土日。
> GitHub Actions の cron は UTC 基準で評価されるため、上の換算 (`* * 4,5,6` = 木〜土 UTC) を採用する。
> 既存 `update_signals.yml` (`0 15 * * *`) と同じ時刻に重ねないため、collect.yml は
> 平日には発火させない (`* * 4,5,6` + `* * 0`) — つまり **木〜日 UTC のみ**。

cron 表記まとめ:

```yaml
schedule:
  - cron: "0 15 * * 4,5,6"   # 木/金/土 UTC 15:00 = 金/土/日 JST 0:00
  - cron: "0 18 * * 0"        # 日 UTC 18:00 = 月 JST 3:00
```

`workflow_dispatch` で手動トリガも可能にする。

---

## 2. 履歴蓄積 (Agent B)

### 2.1 保存先

- ディレクトリ `data/history/` を作る (リポにコミット)。
- 日次スナップショット: `data/history/YYYY-MM-DD.json`
  - その日の `docs/data.json` の主要部分 + survival_loop の Mode A 仮想ポジ + risk_gate + auto_risk を抜粋。
  - 全件保存ではない (リポ肥大防止)。スナップショットのサイズは原則 < 200 KB。
- 追記ログ: `data/history/index.jsonl` (1 行 1 日、冪等管理用)。
- 収集ログ: `data/collect_log.jsonl` (実行ごとに 1 行追記)。

### 2.2 スナップショット スキーマ

```jsonc
{
  "date": "YYYY-MM-DD",          // JST 日付
  "as_of_utc": "<ISO>",          // 取得時刻 (UTC)
  "data_status_counts": {        // 各 markets の data_status 集計
    "live": <int>, "placeholder": <int>, "stale": <int>, ...
  },
  "money_flow_snapshot": {
    "us":  { "cb_assets": <cb_obj>, "debt": <debt_obj>, "freshness_badge": "..." },
    "eu":  {...}, "jp": {...}
  },
  "survival_loop": {
    "risk_gate": { "label": "...", "color": "...", "score": <int> },
    "auto_risk": { "per_trade_pct": <f>, "max_concurrent": <int>, ... },
    "mode_a_positions": [ <pos obj>... ],     // 機械A 当日の仮想ポジ
    "candidates_top": [
      // 上位 5 件のみ (履歴で全 20 件は重い)
      { "symbol": "...", "edge_score": <f>, "direction_hint": "...", "data_status": "..." }
    ]
  },
  "mode_b_intents": []           // 裁量Bは localStorage 主体だが、形だけ枠を残す (常に空配列で OK)
}
```

### 2.3 冪等 (同日再実行で重複しない)

- `data/history/YYYY-MM-DD.json` は **最新で正規化** (同日中の最後の cron 実行が勝つ)。
- `data/history/index.jsonl` は同日エントリを **1 行に正規化** (古い行は削除)。
- 再実行で diff が出ない場合は `git commit --allow-empty` をしない (workflow が "No changes" で抜ける)。

### 2.4 ファイル肥大の制限

- スナップショットは abridged。markets の生配列は載せない (= `data.json` を見れば取れる)。
- 古い `data/history/*.json` は **保持** (Phase 2/3 でサンプル不足を避けるため)。
  90 日経過で `data/history/archive/<year>/` へ移送する設計だけ書き残し、本 Phase では実装しない。

---

## 3. collect_log (Agent E)

`data/collect_log.jsonl` に 1 実行 = 1 行 jsonl。

```jsonc
{
  "run_at_utc": "<ISO>",
  "run_at_jst_date": "YYYY-MM-DD",
  "workflow": "collect" | "update_signals" | "local",
  "duration_sec": <f>,
  "sources": {
    "yfinance":           { "ok": <int>, "failed": <int>, "ratelimited": <int> },
    "fred":               { "ok": <int>, "failed": <int> },
    "fiscaldata":         { "ok": <int>, "failed": <int> },
    "cftc_cot":           { "ok": <int>, "failed": <int> },
    "coingecko":          { "ok": <int>, "failed": <int> },
    "mof_jgb":            { "ok": <int>, "failed": <int> }
  },
  "history_written": "data/history/YYYY-MM-DD.json",
  "history_size_kb": <f>,
  "git_changed": <bool>,
  "errors": [ "yfinance: HTTPError 429 ...", ... ]   // 最初の 5 件まで
}
```

- pytest がこの jsonl をパースして「失敗ソース項目が存在する」「git_changed が boolean」などを検証。

---

## 4. 取得堅牢化 (Agent C)

既存 `fetch_signals.py` の取得関数を破壊しない方針で、`collector/` モジュールを新設:

- `collector/__init__.py`
- `collector/runtime.py`: 共通 retry / timeout / log ヘルパ。
- `collector/snapshot.py`: 日次スナップショット書き出し + index.jsonl 冪等更新。
- `collector/log.py`: collect_log.jsonl 書き出し。
- `collector/cli.py`: `python -m collector.cli` で実行。fetch_signals.main() を呼んだあとに
  snapshot を取り、log を書き、git commit/push は workflow に任せる。

retry 共通ヘルパ:
- `retry(fn, attempts=3, backoff=(1.0, 2.0, 4.0))` 指数バックオフ。429/5xx でリトライ。
- User-Agent: `hf-signal-dashboard collector/1.0 (+https://github.com/reanimatedead/hf-signal-dashboard)`
- レートリミット: 同一ホストへ最低 0.4 秒間隔。
- 失敗ソース名は `collect_log.errors` に積む。

**fetch_signals.py 既存関数は無改変** (Phase 1 のテストが再現できる)。

---

## 5. Mode A/B 記録枠 (Agent D)

- Mode A (機械): すでに `survival_loop.mode_a_positions` として日次生成済。
  Phase 1.5 では history snapshot にそのまま転写するだけ。
- Mode B (裁量): localStorage(`hf_survival_log_v1`) 主体。
  history には **空 placeholder の `mode_b_intents: []` 配列** を残す。
  クライアント側から "intent" を opt-in で渡す API は Phase 3 で追加 (本フェーズでは枠のみ)。
- Mode C (比較): Phase 3 で実装。本フェーズではコメントで `TODO(phase-3)` を残す。

判定ロジック (勝/負/RR) は本フェーズで一切実装しない。snapshot の `mode_a_positions` は
「その日のスナップショット」であって、将来の Phase 3 で日付をまたいで損益が計算される。

---

## 6. CI / pytest (Agent E)

新規テスト:

| ファイル | 目的 |
|---|---|
| `tests/test_collector_idempotent.py` | snapshot を 2 回連続で書き、`data/history/X.json` と `index.jsonl` が重複しない。 |
| `tests/test_collector_schema.py` | snapshot / collect_log の必須キーと型。 |
| `tests/test_collector_resilience.py` | 1 source failure (mock で 例外) でも全体が落ちず、`collect_log.errors` に記録。 |

既存テスト (Phase 1) は **回帰させない**。82 → 82 + 新規。

workflow には pytest gate を追加するが、`update_signals.yml` と `collect.yml` で同じテスト群を使う。

---

## 7. 受け入れ条件 (PR 本文に転写)

1. `.github/workflows/collect.yml` に `0 15 * * 4,5,6` + `0 18 * * 0` の cron。
2. fetch ごとに `data/history/YYYY-MM-DD.json` が追記され、再実行で重複しない。
3. 1 ソース失敗で全体落ちず、`data/collect_log.jsonl` に失敗ソース記録。
4. 全 keyless、API キー無し、捏造値無し、robots/規約順守の UA + レート制御。
5. mode_a / mode_b 記録の「枠」が history に存在 (判定ロジックは未実装、TODO 明記)。
6. Phase 1 の survival_loop / HARD_CAPS / pattern_table が回帰しない。
7. 既存 9 タブ / 検索 / CSV / JA-EN / Dark / 背景 / SVG 回帰なし。not advice 維持。
