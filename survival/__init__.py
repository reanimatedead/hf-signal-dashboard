"""survival/ — Phase 1 生存ループ実装.

SPEC_SURVIVAL.md と一対。
- risk_engine: 固定天井 + 逆ボラ Kelly。 学習しない。
- pattern_table: パターン別利確テーブル。 上振れのみ可変、下振れ固定。
- bankruptcy: モンテカルロ Risk of Ruin と Kaufman 閉形式。
- edge_score: stretch / positioning_fuel / vol_context / edge_score 計算。
- survival_loop: data.json.survival_loop ブロック生成。
"""
