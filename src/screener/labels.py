"""ローカル出力（local_report の HTML）用の 表示の言葉。コード → 日本語。

データ（行の dict・CSV・JSON）はコードだけを持つ。言葉にするのはローカルの描画の直前だけ
（公開画面の辞書は docs/assets/i18n/。ここは公開しないローカル出力専用の小さな辞書）。
"""

from __future__ import annotations

from typing import Any

# 列名（行の dict のキー）
COLUMNS = {
    "grade": "総合判定", "code": "コード", "company_name": "会社名", "market": "市場", "sector": "業種",
    "chart_signal": "チャート判定", "trend": "長期", "price": "株価", "fair_price": "理論株価",
    "upside_pct": "上値余地%", "PBR": "PBR", "F": "F", "f_max": "F満点", "magic_rank": "魔法の公式順位",
    "fin_tag": "財務判定", "mcap_oku_jpy": "時価総額(億円)", "one_off_note": "一時利益の目印",
    "one_off_reasons": "一時利益の理由", "value_quintile": "割安度(5分位)", "quality_candidate": "品質の候補",
    "ticker": "ティッカー", "name": "会社名", "idx": "指数",
}  # fmt: skip

# 値（コード）
VALUES = {
    # チャート判定（screener.calc.ind）
    "buy_strong": "強い買い", "buy": "買い", "neutral": "様子見", "sell": "売り", "sell_strong": "強い売り",
    "buy_long_oversold": "買い（長期の売られすぎ）",
    "sell_note": "空売りの根拠なし。新しく買わない・利益を確定する目安",
    "long_up": "長期は上向き", "long_down": "長期は下向き",
    # 財務判定（screener.japan.screen.tag / screener.us.make_value.tag）
    "long_candidate": "長期候補", "mid_candidate": "中期候補", "cheap_low_quality": "割安だが質に注意",
    "value_quality_top50": "割安×質 上位50",
    # 割安度（screener.japan.screen.value_quintile）
    "cheap_quintile": "割安5分の1", "middle": "中間", "expensive_quintile": "割高5分の1",
    # 一時利益の目印（screener.calc.value）
    "check_earnings_release": "決算短信で確認",
    "net_income_gt_op_income_1_3x": "純利益が営業利益の1.3倍超",
    "roe_fwd_gt_roe_act_2x": "予想ROEが実績ROEの2倍超",
}  # fmt: skip

# 総合判定 A/B/C の説明
GRADE_TEXT = {"A": "A 割安5分の1×買い", "B": "B どちらか一方", "C": "C 該当なし"}

SEP = "|"  # 複数コードの区切り（財務判定・一時利益の理由）


def col(key: str) -> str:
    return COLUMNS.get(key, key)


def value(v: Any) -> str:
    """セルの値を言葉にする。'a|b' のような複数コードは「・」でつなぐ。辞書に無い値はそのまま。"""
    if v is None:
        return ""
    s = str(v)
    if SEP in s:
        return "・".join(VALUES.get(p, p) for p in s.split(SEP))
    return VALUES.get(s, s)
