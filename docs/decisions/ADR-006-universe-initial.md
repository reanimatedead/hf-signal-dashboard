# ADR-006 構成銘柄の初期値は知識ベース（日経225は §19 の権利判断により自動取得しない）

- 状態: 採用（2026-11）
- 関連: DATA_CONTRACT §19・§21

## 決定
- 指数の構成銘柄は、`fetch_signals.py` 内蔵の一覧（2026-11 時点の知識による初期値）を出発点にする。
- S&P500・NASDAQ100・DOW30 は週次（universe.yml・`tools/update_universe.py`）で取り直し、件数が想定 ±5%
  （`screener.calc.contracts.count_within`）に入るときだけ `data/universe/*.json` を更新する。外れたら前週のまま。
- 日経225 は §19 の権利判断を維持し、既定では機械取得しない（内蔵一覧の件数検査だけ）。
  リポジトリ変数 `NIKKEI_DYNAMIC=true` のときだけ取得する（判断を変えるのはオーナー）。
- Mac mini の米国株（`screener.us.fetch --universe`）は、リポジトリの `data/universe/*.json` を優先して使う。

## 結果
- 初期値は古くなりうるので、件数のずれは契約テストで検知し、表示に出典（file / builtin / web）を残す。
