"""collector/ — 週末全自動データ収集機 (Phase 1.5).

SPEC_AUTOCOLLECT.md と一対。
- runtime: retry / timeout / User-Agent / rate-limit floor
- snapshot: data/history/YYYY-MM-DD.json 冪等書き込み + index.jsonl 正規化
- log: data/collect_log.jsonl 追記
- cli: `python -m collector.cli` で fetch_signals → snapshot → log を実行

判定ロジック (Phase 3) / 学習 (Phase 2) は本パッケージに **持ち込まない**。
"""
