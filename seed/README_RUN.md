# README_RUN — 参照シードの動かし方 & 本番への引き渡し

このシードは **実際に動く最小実装**です。本番の A1〜A5 が拡張していく“土台”であり、配線・契約・アニメ・ハーネスが通ることをこのチャット側で実走確認済みです。

## 実走済みの証跡(このシード)
- `python3 pipeline/build_data.py` → `{"build":"ok","tiles_total":12,"live":2,"missing":10,"net_liquidity_status":"missing"}`
  - ライブ2 = BTC価格 / ステーブルコインペグ(CoinGecko)。TGAも実取得。
  - 残り = FRED_API_KEY 未設定のため **正直に missing**(捏造なし)。
- `python3 verify.py` → **PASS(10/10ゲート)** exit 0
- 軽量配線チェック(ブラウザ不要) → **PASS**(12タイル / basin_tilt合計=1)

## ローカルで動かす(M1 Mac)
```bash
cd seed
# 1) データ生成(FREDキーがあれば下行で export するとFRED系もライブに)
# export FRED_API_KEY=xxxxxxxx
python3 pipeline/build_data.py

# 2) 配信して開く(file:// だと data.json 取得がCORSで失敗するため必ずサーバ経由)
python3 -m http.server 8520 -d public
#   → ブラウザで http://localhost:8520  (お金の流れアニメ + タイル)

# 3) 自己点検ハーネス
python3 verify.py                       # データ/契約/単位/欠損/除外 など10ゲート
npm i puppeteer && node verify_render.mjs   # ブラウザ描画チェック(JSエラー0/タイル/アニメ/免責文言)
```

## このシードと5エージェントの対応
| シード成果物 | 担当エージェント | 本番での拡張 |
|---|---|---|
| `pipeline/build_data.py`(収集) | **A1** | ソース別並列フェッチ・`~/hf-data-store/` へ append-only |
| `pipeline/build_data.py`(計算部) | **A2** | ストア長期履歴で z 算定・全タイル配線・flow精緻化 |
| `verify.py` | **A3** | そのまま流用(SEED_MODE=False で `~/hf-data-store` を見る) |
| `public/index.html` `app.js` `flow.js` | **A4** | 器ラベル/タイル増・store_fallback 表示 |
| `verify_render.mjs` + 監査 | **A5** | 全体再実行 → ローカルcommit → push手前で停止 |

## 本番(MacBook の Claude Code)へ引き渡す
1. リポジトリに配置:
   ```
   ルート/ CLAUDE.md  BUILD_SPEC_v3.md  BUILD_SPEC_v2.md
          .claude/agents/a1-data-collector.md … a5-review-integrator.md
          seed/ (この参照実装。public/ pipeline/ verify.py verify_render.mjs)
   ```
2. `~/hf-data-store/` は **リポジトリ外**。`.gitignore` にストアと `seed/public/data.json`(生成物)を入れる。
3. Claude Code を**対話モードで起動**(`claude -p` は使わない)。`.claude/agents/*` 反映のため、配置後は**再起動** or `/agents`。
4. 必要なら `export FRED_API_KEY=...` と `export CLAUDE_CODE_SUBAGENT_MODEL="claude-sonnet-4-6"`。
5. CLAUDE.md の起動例で実行:
   ```
   CLAUDE.md と BUILD_SPEC_v3.md に従い、seed/ を土台に
   確認→A1→A2→A3(PASSまで)→A4→A5→ローカルcommit を実行。
   push 手前で停止し、verify.py と verify_render.mjs の実出力を添えて報告して。
   ```
6. **完成後にあなたが一括チェック**(受け入れ基準=BUILD_SPEC §8)。push はあなたの承認後。

## 注意
- これは相場「環境」の可視化であり **売買助言ではありません**。
- ストアはバックアップではない。重要履歴は別ドライブ複製を推奨。
- アニメの器を「日本株/金/銀/BTC」にする場合は、投入前に `flow.js` の LABELS/COLORS と `BUILD_SPEC_v2.md` §3 `basin_tilt` キーを差し替え。
