# HF Signal Scanner Pro 📊

Bloomberg-style trading signal dashboard.  
**日経225 + Dow30 + Nasdaq100 + S&P500 + FX** の全シグナルを毎日08:00 JSTに自動更新。

---

## 🏗 アーキテクチャ

```
GitHub (Private Repo)
  └── GitHub Actions (毎日 23:00 UTC = 08:00 JST)
        └── Python + yfinance → data.json を生成
              └── docs/ にコミット → Cloudflare Pages が配信
```

- **データソース**: Yahoo Finance (yfinance) — 無料・APIキー不要
- **ホスティング**: Cloudflare Pages (無料・Private リポジトリ対応)
- **実行環境**: GitHub Actions (無料枠 2000分/月で充分)

---

## 🚀 セットアップ手順

### 1. リポジトリ作成

```bash
git clone https://github.com/あなたのユーザー名/hf-signal-dashboard.git
cd hf-signal-dashboard

# ファイルを全部コピー後
git add -A
git commit -m "initial commit"
git push origin main
```

### 2. ローカルテスト (任意)

```bash
# Python 環境構築
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

pip install -r requirements.txt

# シグナル生成テスト (10〜20分かかります)
python fetch_signals.py

# ブラウザで確認
cd docs && python -m http.server 8080
# → http://localhost:8080 を開く
```

### 3. GitHub Actions の確認

1. GitHub → リポジトリ → **Actions** タブを開く
2. "Daily Signal Update" ワークフローが表示されていることを確認
3. **Run workflow** ボタンで手動実行してテスト
4. 成功すると `docs/data.json` が自動コミットされる

### 4. Cloudflare Pages でデプロイ (無料)

> Private GitHub リポジトリを無料でホスティングできる推奨方法

1. [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create**
2. **Connect to Git** → GitHub アカウントを連携
3. Private リポジトリを選択
4. ビルド設定:
   - **Framework preset**: `None`
   - **Build command**: *(空欄)*
   - **Build output directory**: `docs`
5. **Save and Deploy**

デプロイ後、`https://あなたのプロジェクト名.pages.dev` でアクセス可能。

### 5. (代替) Vercel でデプロイ

1. [Vercel](https://vercel.com) → **Add New Project** → GitHub 連携
2. リポジトリを選択
3. **Root Directory**: `docs`
4. **Framework Preset**: `Other`
5. Deploy

---

## ⚙️ カスタマイズ

### 日経225 銘柄を追加・変更する

`fetch_signals.py` の `NIKKEI225` 辞書を編集:

```python
NIKKEI225 = {
    "9984.T": "SoftBank Group",
    "7203.T": "Toyota Motor",
    # → 追加したい銘柄を "証券コード.T": "会社名" 形式で追記
    "4755.T": "楽天グループ",
}
```

### 更新時刻を変更する

`.github/workflows/update_signals.yml` の cron を変更:

```yaml
# 例: 毎日 07:00 JST = 22:00 UTC
- cron: "0 22 * * *"

# 例: 平日のみ 08:00 JST
- cron: "0 23 * * 1-5"
```

### FX ペアを追加する

```python
FX_PAIRS = {
    "USDJPY=X": "USD/JPY",
    # 追加例:
    "BTCUSD=X": "BTC/USD (Bitcoin)",
    "ETHUSD=X": "ETH/USD (Ethereum)",
}
```

---

## 📊 シグナル計算ロジック

| インジケーター | 配点 | 説明 |
|---|---|---|
| RSI(14) | 0-25 | RSI≤30で満点（売られすぎ = 買いチャンス） |
| MACD Histogram | 0-25 | プラス圏で加点 |
| EMA Trend | 0-25 | 価格>EMA20>EMA50>EMA200で満点 |
| Bollinger %B | 0-25 | ロワーバンド付近で満点 |

**合計スコア (0-100) → シグナル判定:**

| スコア | 株式シグナル | FX シグナル |
|---|---|---|
| 78〜100 | 🟢🟢 STRONG BUY | 🟢🟢 STRONG LONG |
| 63〜77 | 🟢 BUY | 🟢 LONG |
| 43〜62 | ⚪ HOLD | ⚪ NEUTRAL |
| 28〜42 | 🟡 WATCH | 🔴 SHORT |
| 0〜27 | 🔴 AVOID | 🔴🔴 STRONG SHORT |

> **注意**: 本ツールは情報提供のみを目的としています。投資判断はご自身の責任で行ってください。

---

## 🗂 ファイル構成

```
hf-signal-dashboard/
├── .github/
│   └── workflows/
│       └── update_signals.yml   # 自動実行スケジュール
├── docs/
│   ├── index.html               # ダッシュボード UI
│   └── data.json                # 生成済みシグナルデータ (自動更新)
├── fetch_signals.py             # シグナル生成スクリプト
├── requirements.txt             # Python 依存関係
└── README.md                    # このファイル
```

---

## 🔧 トラブルシューティング

**Actions が失敗する場合:**
- `pip install` エラー → `requirements.txt` のバージョンを確認
- `yfinance` タイムアウト → Yahoo Finance のレート制限。再実行で解決することが多い

**シグナルが表示されない場合:**
- `docs/data.json` が空 or placeholder のまま → Actions を手動実行
- CORS エラー → ローカルでは `python -m http.server` で確認（直接ファイルを開かない）

**銘柄データが取得できない場合:**
- `.T` サフィックスが正しいか確認 (日本株は `7203.T` 形式)
- 上場廃止や合併でティッカーが変わった可能性あり
