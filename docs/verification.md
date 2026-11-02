# 検証の記録（何を・どう確かめたか）

この文書に **J-Quants の値（株価・決算・理論株価・件数など）は書かない**（ADR-002）。
日本株の検証は Mac mini のローカルでだけ行い、結果は `<data_dir>/out/` に残す（公開しない）。
ここに書くのは方法と、架空データ・公開データ（Yahoo）での確認だけ。

## 1. 自動テスト（架空データ・通信なし・キーなし）

`uv run pytest -q`（ci.yml）と `python3 -m pytest tests/ -q`（deploy.yml）で回る。2026-11-01 時点の件数:

| ファイル | 件数 | 内容 |
|---|---|---|
| tests/screener/calc/test_ind.py | 11 | CCI・BB（母標準偏差）・売買判定・長期の売られすぎ（売りと同じ日は売り・規則は ind.day_labels の1か所）・chart_series |
| tests/screener/calc/test_fund_us.py | 6 | EDGAR 形の決算から F・魔法の公式・残余利益 |
| tests/screener/calc/test_value_events_contracts.py | 4 | 理論PBR・一時利益の目印・イベントスタディ・契約判定 |
| tests/screener/test_jquants.py | 6 | 120 回で直近60秒 50 回以下・3スレッドでも 50 回以下（偽の時計）・V2・ページ送り・キーを出さない |
| tests/screener/test_japan_fetch.py | 3 | 既定は今日だけ・--full は年数分・一括取得でも 50回/60秒以下 |
| tests/screener/test_japan_screen.py | 6 | 理論株価・F・魔法の公式・分割前後で PBR 不変・「決算短信で確認」・四半期/未来の開示を使わない |
| tests/screener/test_japan_signals.py | 6 | 総合判定 A = 割安5分の1 × 買い系 の規則・割安5分の1の母集団と境界・**A の銘柄はすべて上値余地が割安5分の1の境界以上**・A の定義そのものの検証（verify_local.json の jp.grade_A）・**バックテスト（with_chart）と画面が同じ関数を呼び、同じ件数・成績になる**・バックテストが動く |
| tests/screener/test_us.py | 3 | 決算を1社ずつ読む・判定・株価の付け足しと分割検知 |
| tests/screener/test_local_report.py | 3 | 書くのは `<data_dir>/out/` だけ（japan_list.html と同じ形の us_list.html も）・counts.json（前回とずれ%）・リポジトリ内は拒否 |
| tests/screener/test_notify.py | 4 | 本文が `^screener \d{4}-\d{2}-\d{2} (OK\|失敗\|週次 OK)$` だけ・送信結果（HTTP コード）を1行ログに出す |
| tests/screener/test_daily.py | 8 | 失敗→「失敗」と終了コード1・成功は無通知・月曜は「週次 OK」・ntfy の結果を1行ログ・git pull --ff-only・契約テスト不合格で止まる・全段 |
| tests/screener/test_config.py | 3 | 既定 ~/screener-data・config.toml で変更・リポジトリ内は拒否 |
| tests/screener/test_install_script.py | 7 | キーをファイル/ログに書く行が無い・~/hf-signal-dashboard の main・Obsidian のパスが無い・bash -n・shellcheck |
| tests/test_data_json_gate.py | 4 | 生成物が無い→skip、REQUIRE_DATA_JSON=1→fail |

- 日本株は架空の J-Quants 形データ（架空5銘柄×400営業日・通期決算2期・1:2 の株式分割・一時利益）を
  `tests/screener/fixtures/make_fixtures.py` がテスト時に一時ディレクトリへ作る（決まった乱数で毎回同じ）。
- 米国株・公開ダッシュボードの式は架空の Yahoo/EDGAR 形データ（`tests/screener/calc/fixtures/`）。
- 生成物（docs/data.json・charts・macro_v2・relations・gamma）が要る既存の 35 件は marker `needs_data_json`。
  オフラインでは skip（理由を表示）、deploy.yml full の「Data tests」で生成後にスキップ禁止で回る。

## 2. 公開データ（Yahoo）での判定の検証（docs/verify.json・検証タブ）

`pipeline/build_verify.py`（式は `screener.calc.events` / `screener.calc.ind`）:
- 判定が出た日の終値 → **20 営業日後**の騰落率。
- 同じ銘柄の連続した判定は **20 日に1回**だけ数える。
- 基準 = 同じ銘柄・同じ期間の全営業日の 20 日後騰落率（全期間の平均）。指標が揃うまでの 288 本は数えない。
- 全期間と直近 6 か月を出し、直近で「買い系の判定後の中央値 < 基準の中央値」なら weakened（件数 5 未満は判定しない）。
- 判定の規則は自動では変えない（表示だけ）。

## 3. 日本株（ローカルだけ）

- 方法は 2 と同じ（`screener.japan.signals.verify`、`screener.japan.backtest_tech`）。財務判定は
  `screener.japan.backtest_value`（1年後の騰落・余地の5分位、割安度×チャート判定の20営業日後）。
- 結果は `<data_dir>/out/verify_local.json` と `<data_dir>/out/verify/YYYY-MM/` にだけ書く。ここには写さない。
- 本物のデータでの確認は Mac mini の初回実行時（README の手順: counts.json の件数のずれ ±5%）。
