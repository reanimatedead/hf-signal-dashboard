# SPEC_NOTIFY.md — 即時通知 + 改竄不能ログ (Phase 1.6, notify)

> 本ファイルは **実装より先にコミットされる** (spec-first)。
> 目的: 判定 (ENTRY/EXIT) の **その瞬間** に、Mac mini + ntfy.sh の **二経路** で通知。
> Web (Cloudflare Pages) は閲覧専用のまま、Mac mini が「通知ハブ + 改竄不能台帳」を持つ。
> Phase 2 (学習) / Phase 3 (勝敗判定 ≒ 損益計算) は **本フェーズで実装しない**。

---

## 0. 大原則 (硬い柱)

- **macOS / zsh 専用**。Windows は対象外。
- **全 keyless**。Gmail OAuth, ntfy auth, API key, secret 全て不要。
  ntfy.sh は無認証で publish できる。トピック名は推測困難な乱数文字列にし、
  リポに置かない (`config.local` のみ。`.gitignore` で除外済)。
- **二経路**: (A) Mac mini ローカル通知 (osascript) と (B) ntfy.sh への HTTP POST。
  どちらか落ちても片方届く。両方落ちた時は queue + リトライ。
- **改竄不能**: append-only。UPDATE / DELETE は実装段階で禁止。
  各行に prev_hash + payload → curr_hash の sha256 ハッシュチェーン。
  「後出しで ENTRY を消す」「EXIT を捏造する」を物理的に成立させない。
- **look-ahead 厳禁**: バー i 時点の判定は **バー 0..i-1** + **バー i (確定済み)** のみ参照。
  バー i+1 以降の情報を 1 bit も覗かない。テストで保証。
- **GRC**: 通知文面に「事実記録 / not investment advice」を必ず含める。
  執行助言 (買え/売れ) ではなく「自分が立てた判定を自分に通知している」位置づけ。
- **Phase 1 への回帰なし**: HARD_CAPS / survival_loop / pattern_table / autocollect
  は触らない。既存テスト (103) は緑のまま。

---

## 1. アーキテクチャ (Mac mini 主 + ntfy 保険)

```
                   docs/data.json (collector.cli が更新)
                              │
                              ▼
                   notify/triggers.evaluate(...)
                              │   ↓ look-ahead 厳禁
                              ▼
                    notify/chain.append(event)
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
       notify/bus.send_osascript     notify/bus.send_ntfy
         (Mac mini ローカル)            (ntfy.sh)
                  │                       │
                  ▼                       ▼
              macOS 通知 + 音           スマホ / 他機
```

- 起動形態: `scripts/notify_receiver.py` を launchd で常駐 (KeepAlive)。
- 周期: 既存 collector.cli の発火後にも呼び出せるが、本 Phase の receiver は
  60 秒ごとに `docs/data.json` を読み直し、新規シグナルを判定する独立ループ。
- Mac mini 停止時: ntfy.sh だけは届く (受信側スマホで気づける)。

---

## 2. notify/ パッケージ構成

| ファイル | 役割 |
|---|---|
| `notify/__init__.py` | 説明のみ |
| `notify/chain.py` | append-only 台帳 + ハッシュチェーン + 検証 + EXIT 欠損検知 |
| `notify/triggers.py` | look-ahead 無しの ENTRY/EXIT 判定 |
| `notify/bus.py` | osascript 経路 + ntfy 経路 + queue+retry |
| `notify/config.py` | `config.local` ローダ (不在時 = 通知無効、落とさない) |
| `notify/receiver.py` | 60 秒ループ。triggers→chain→bus を 1 サイクル |
| `scripts/notify_receiver.py` | launchd / 手動 起動用エントリ |
| `scripts/com.hf.notify.plist` | LaunchAgent 設定テンプレ |

---

## 3. 改竄不能ログ (Agent C, `notify/chain.py`)

### 3.1 ファイル

- 保存先: `data/local/notifications.jsonl` (1 行 1 イベント)。
  - **`data/local/` は `.gitignore` で除外**。個別判定記録を公開リポに出さない。
- 各行 = 1 イベント。append のみ。**ファイル切詰め / 行書き換え禁止**。

### 3.2 イベント payload

```jsonc
{
  "event_id": "<uuid4>",
  "ts_utc":   "<ISO>",
  "kind":     "ENTRY" | "EXIT_TP" | "EXIT_SL" | "EXIT_TIMEOUT",
  "symbol":   "...",
  "side":     "long" | "short",
  "bar_tf":   "4h" | "1d" | "1w",
  "bar_ts":   "<ISO of bar close>",
  "price":    <float>,
  "edge_score": <int|null>,    // ENTRY のみ
  "entry_ref": "<event_id|null>", // EXIT のみ ENTRY の event_id を必ず指す
  "pattern":  {"regime": "...", "distortion": "..."},
  "size_pct": <float<=0.5>,
  "exit_targets": {"take_profit_pct": <f>, "stop_loss_pct": <f<0>},
  "realized_pct": <float|null>, // EXIT のみ
  "notice":   "事実記録 / not investment advice",
  "prev_hash": "<hex64>",
  "curr_hash": "<hex64>"   // = sha256(prev_hash + canonical_json(payload-without-hash))
}
```

### 3.3 API

```python
chain = Chain(path)                  # load existing rows; verify integrity on open
chain.append(payload_without_hash)   # returns full row dict including curr_hash
chain.verify()                       # → (ok: bool, first_broken_index: int|None, reason: str|None)
chain.unmatched_entries()            # → list of ENTRY rows that have no EXIT_*
chain.find(event_id)                 # → row | None
```

### 3.4 不変条件 (テストで保証)

- **append-only**: `chain.append` 以外で行を変更しない。
- **改竄検知**: 任意の行の payload 1 文字でも書き換えれば `verify()` が False を返す。
- **挿入検知**: 中間に偽の行を挿入してハッシュ再計算しても、次行の `prev_hash` が
  整合せず `verify()` が False。
- **削除検知**: 行を抜くと次行の `prev_hash` が前々行のままになり verify 失敗。
- **EXIT 欠損検知**: `unmatched_entries()` が ENTRY のうち対応する EXIT_* が無いものを返す。
- **EXIT entry_ref 強制**: `kind` が EXIT_* の payload に `entry_ref` 必須。
  値が past ENTRY に対応しない場合は `ValueError`。

---

## 4. look-ahead 無し ENTRY/EXIT 判定 (Agent A, `notify/triggers.py`)

### 4.1 API

```python
triggers.evaluate(
    bars,             # list[Bar] 時系列で並んだバー (close で確定したものだけ)
    t_index,          # 評価する時点。bars[t_index] までしか参照しない
    state,            # 現在のオープンポジション辞書 ({symbol -> ENTRY event_id})
    edge_score_at_t,  # その時点の survival_loop.edge_score (= 過去バーから算出)
    pattern_table,    # survival.pattern_table.DEFAULT_PATTERN_TABLE
) -> list[event_payload]
```

### 4.2 ルール

- **ENTRY**: ポジ無し & `edge_score_at_t >= 70` → ENTRY (direction は edge_score 算出と同源)。
  バー i の close 価格を `price` に使用 (バー i は既に確定しているので OK)。
- **EXIT_TP**: ポジ有 & 該当バーの close が `entry.price * (1 + take_profit_pct/100)` を超え (long)
  / 下回り (short) → EXIT_TP。
- **EXIT_SL**: 同様に stop_loss_pct を割り込んだら EXIT_SL。
- **EXIT_TIMEOUT**: ポジ保有が `MAX_HOLD_BARS = 40` 本超えたら EXIT_TIMEOUT (RR=0)。
- **look-ahead 禁止**: 関数は `bars[t_index+1:]` を 1 度も読まない。
  テストで `bars[t_index+1:]` を NaN 改竄しても同じ結果が出ることを保証。

### 4.3 dual-mode

- 機械A (mode_a) = 自動でイベント生成 (chain.append)。
- 裁量B (mode_b) = 候補のみ通知 (chain には書かない、 bus 経由でスマホに「候補あり」)。

---

## 5. 通知 bus (Agent B, `notify/bus.py`)

### 5.1 経路

- `send_osascript(row)`: `osascript -e 'display notification "..." with title "..." sound name "Glass"'`
  - `subprocess.run` で 5 秒タイムアウト。失敗は queue に積む。
- `send_ntfy(row, topic)`: `urllib.request` で `https://ntfy.sh/{topic}` に POST。
  - Headers: `Title`, `Priority` (ENTRY=urgent=5, EXIT=high=4), `Tags`。
  - Body: `f"{kind} {symbol} {side} @ {price:.4f} edge={edge_score} | 事実記録 / not investment advice"`
  - 5 秒タイムアウト。429/5xx は queue 行き。
- 両方失敗 → row を `data/local/notify_queue.jsonl` に積み、次サイクルで `bus.flush()` が再送。

### 5.2 dedup (二重送信)

- 同じ `event_id` を 24 時間以内に二度送らない (seen set + jsonl)。
- 受信側 (Mac mini receiver) が同じ event_id を 2 回処理してもログには 1 行のみ。

### 5.3 config.local 不在時

- `notify.config.load()` が None を返す。`bus.send_*` は no-op (False を返す)。
- pytest はテストで「config 不在 → 落とさず False を返す」を保証。
- launchd ログには `notify disabled (no config.local)` を 1 度だけ出す。

---

## 6. config.local 形式 (リポ外)

`~/hf-signal-dashboard/config.local` (text JSON, .gitignore 済)。

```jsonc
{
  "initial_balance": 100,
  "currency": "JPY",
  "display_absolute": false,
  // Phase 1.6 notify additions
  "notify_enabled": true,
  "ntfy_topic": "hf-<random-string-32-chars>",  // 推測困難
  "mac_notify_sound": "Glass"
}
```

- `config.local.json.example` (公開) には Phase 1.6 のキーも例として追記する。
- 実ファイルは絶対にコミットしない。
- `notify_enabled=false` 又はキー不在で通知無効。

---

## 7. 可視化 (Agent D)

- `docs/assets/survival/notify_panel.js` に `#sv-notify` パネル描画ロジック。
- パネル位置: SURVIVAL タブ内、結果ログの直前。
- 取得元: `docs/data/notifications_public.jsonl` (chain.export_public() の出力)。
  個別 entry の payload から `price` を除いた **公開安全な抜粋** だけを出す。
  *個人の判定タイミング = 公開してOK*、*判定価格 = 個人情報なのでフロントに出さない*。
- 表示要素:
  - 時系列で ENTRY/EXIT ペア (symbol/side/edge_score/pattern/kind/ts)。
  - チェーン断裂時は赤バナーで「⚠ chain integrity check failed at index N」を最上部に。
  - 件数とハッシュ末尾を fingerprint として表示。

---

## 8. launchd 常駐 (Agent B)

`scripts/com.hf.notify.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.hf.notify</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/USER/hf-signal-dashboard/scripts/notify_receiver.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key>
  <string>/Users/USER/hf-signal-dashboard</string>
  <key>StandardOutPath</key>
  <string>/Users/USER/hf-signal-dashboard/data/local/notify.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/USER/hf-signal-dashboard/data/local/notify.err.log</string>
  <key>ThrottleInterval</key><integer>30</integer>
</dict>
</plist>
```

ロード手順 (README にも記載):

```sh
mkdir -p ~/Library/LaunchAgents
sed "s/USER/$USER/g" scripts/com.hf.notify.plist > ~/Library/LaunchAgents/com.hf.notify.plist
launchctl unload ~/Library/LaunchAgents/com.hf.notify.plist 2>/dev/null || true
launchctl load -w ~/Library/LaunchAgents/com.hf.notify.plist
launchctl list | grep com.hf.notify
```

確認:

```sh
osascript -e 'display notification "smoke test" with title "hf-notify"'  # Mac mini で 1 度実行
curl -d "smoke test" "https://ntfy.sh/$(grep ntfy_topic config.local | cut -d\" -f4)"  # ntfy 経由
```

---

## 9. CI / pytest (Agent E)

| ファイル | 目的 |
|---|---|
| `tests/test_notify_chain.py` | append-only / 改竄検知 / 挿入検知 / 削除検知 / EXIT 欠損検知 / dedup |
| `tests/test_notify_triggers.py` | look-ahead 厳禁 / ENTRY 閾値 / TP/SL/TIMEOUT 判定 |
| `tests/test_notify_bus.py` | osascript / ntfy 経路を **モック** で叩く + 失敗で queue + retry |
| `tests/test_notify_receiver.py` | 1 サイクル e2e (data.json → triggers → chain → bus 全モック) |
| `tests/test_notify_security.py` | リポに ntfy_topic / config.local 文字列が混入していないことを grep |

既存 Phase 1 / 1.5 のテスト (103) は **緑のまま**。

### 9.1 実通知の手動確認手順 (SPEC)

```sh
# Mac mini で 1 度だけ:
python3 -c "import notify.bus as b; b.smoke_local('hello from hf')"
python3 -c "import notify.bus as b; b.smoke_ntfy('hello via ntfy', topic_override='hf-XXX')"
```

成功すれば macOS 通知 + スマホ ntfy アプリにも届く。

---

## 10. 受け入れ条件 (PR 本文に転写)

1. ENTRY/EXIT の発火瞬間に Mac mini 通知 (osascript) + ntfy 送信 (モック e2e 緑、実通知手順記述)。
2. 全 keyless。Gmail/API キー不要。ntfy トピックは `config.local` のみ。
3. append-only + ハッシュチェーンで改竄検知 (pytest 緑)。
4. ENTRY に対応する EXIT 欠損を `unmatched_entries()` で列挙、UI で赤バナー。
5. look-ahead リーク無し (テストで `bars[t+1:]` 改竄不変)。
6. launchd で Mac mini 常駐 (`com.hf.notify.plist`)。Mac mini 落下時も ntfy 経由で届く。
7. 通知文面に「事実記録 / not investment advice」明記。
8. Phase 1 / HARD_CAPS / 既存タブ / autocollect 回帰なし。Phase 2/3 未実装。
