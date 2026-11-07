"""ローカル出力（local_report の HTML）用の 表示の言葉。コード → 日本語。

データ（行の dict・CSV・JSON）はコードだけを持つ。言葉にするのはローカルの描画の直前だけ
（公開画面の辞書は docs/assets/i18n/。ここは公開しないローカル出力専用の小さな辞書）。
"""

from __future__ import annotations

from typing import Any

# 列名（行の dict のキー）
COLUMNS = {
    "grade": "総合判定", "code": "コード", "company_name": "会社名", "market": "市場", "sector": "業種",
    "value_check": "要確認", "chart_signal": "チャート判定", "trend": "長期", "price": "株価", "fair_price": "理論株価",
    "upside_pct": "上値余地%", "PBR": "PBR", "F": "F", "f_max": "F満点", "magic_rank": "魔法の公式順位",
    "fin_tag": "財務判定", "mcap_oku_jpy": "時価総額(億円)", "one_off_note": "一時利益の目印",
    "one_off_reasons": "一時利益の理由", "value_quintile": "割安度(5分位)", "quality_candidate": "品質の候補",
    "ticker": "ティッカー", "name": "会社名", "idx": "指数",
    "cci48": "CCI48", "cci288": "CCI288", "watch": "ウォッチ",
    "both_down": "両方 −200 割れ", "cci48_down": "CCI48 −200 割れ", "cci288_down": "CCI288 −200 割れ",
    "both_up": "両方 +200 超え", "cci48_up": "CCI48 +200 超え", "cci288_up": "CCI288 +200 超え",
    "score": "スコア", "score_tier": "段階(5=上)", "score_value": "割安の点", "score_chart": "チャートの点",
    "score_penalty": "減点", "score_penalties": "減点の理由", "score_quality": "質の点(未検証)",
    "score_sell": "売りの点(利確目安)", "score_note": "スコアの注記", "per_fwd": "予想PER", "per_act": "実績PER",
    "PER": "PER", "roe_act_pct": "ROE%(実績)", "roe_pct": "ROE%", "div_yield_fwd_pct": "配当利回り%(予想)",
    "div_yield_pct": "配当利回り%", "equity_ratio_pct": "自己資本比率%", "turnover_20d": "売買代金(20日平均)",
    "next_earnings": "次の決算(推定)", "etf_kind": "種類", "cci200_signal": "CCI ±200 の判定(本日)",
    "bb48_z": "BB48 の位置(σ)", "bb288_z": "BB288 の位置(σ)",
}  # fmt: skip

# 値（コード）
VALUES = {
    # チャート判定（screener.calc.ind）
    "buy_strong": "強い買い", "buy": "買い", "neutral": "様子見", "sell": "売り", "sell_strong": "強い売り",
    "buy_long_oversold": "買い（長期の売られすぎ）",
    "buy_cci200": "買い（CCI −200）",
    "sell_cci200": "売り目安（CCI +200）：利益確定・新しく買わない（空売りの根拠ではない）",
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
    # 売買スコア（screener.calc.score）
    "one_off": "一時的な利益", "earnings_soon": "決算まで5営業日以内", "low_turnover": "売買代金が下位10%",
    "not_scored_inverse": "inverse（物差しの対象外）", "no_inputs": "材料なし",
    # 要確認（screener.calc.fund_us.value_check）
    "shares_mismatch": "株数が純利益÷EPS と 20% 超ずれる", "per_lt_2": "PER が 2 未満",
    "upside_gt_500": "上値余地が +500% 超", "upside_gt_150": "要確認（一時的な利益の可能性）",
    # ETF の種類（screener.calc.assets.etf_kind）
    "index": "指数", "leveraged": "レバレッジ", "inverse": "インバース", "unknown": "不明",
}  # fmt: skip

# 「根拠が弱まっています」の項目（verify_local.json の weakened_items: "<市場>:<chart|score>:<コード>"）
WEAK_MARKET = {"jp": "日本株", "us": "米国株", "etf": "ETF"}
WEAK_CODE = {"buy": "買い", "long_oversold": "買い（長期の売られすぎ）", "tier5": "スコア最上位の段階"}


def weak_item(x: str) -> str:
    p = str(x).split(":")
    if len(p) < 3:
        return str(x)
    return f"{WEAK_MARKET.get(p[0], p[0])} {WEAK_CODE.get(p[2], p[2])}"


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
