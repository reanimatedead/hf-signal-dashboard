"""backtest/ — Walk-Forward 予測精度ハーネス (Phase 1.7).

SPEC_BACKTEST.md と一対。
- walk_forward: anchored / rolling 分割 + purge + embargo + look-ahead 監視 list
- simulator: 1 fold の仮想取引 (slip / fee / HARD_CAPS / 同時保有上限)
- metrics: hit_rate / Brier 分解 / 較正曲線 / bootstrap CI / N<30 保留
- cli: e2e (仮装 or 実履歴) で結果 JSON 出力

Phase 2 (学習) / Phase 3 (勝敗判定) は本パッケージに持ち込まない。
"""
