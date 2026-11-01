"""残余利益モデル（理論PBR）・F スコア集計・一時的な利益の目印。データは持たない。"""

RI = {"r": 0.08, "years": 10, "roe_cap": 0.40, "payout_keep": 0.5}
ONE_OFF_NOTE = "決算短信で確認"


def ri_ratio(roe, p=RI):
    """理論PBR（1株純資産を1としたときの理論株価）。ROE は年数をかけて資本コストへ収束させる。"""
    r, n = p["r"], p["years"]
    roe = max(min(roe, p["roe_cap"]), -0.5)
    v, b = 1.0, 1.0
    for t in range(1, n + 1):
        roe_t = roe + (r - roe) * (t / n)
        v += (roe_t - r) * b / (1 + r) ** t
        b *= 1 + roe_t * p["payout_keep"]
    return v


class FScore:
    """None（判定できない項目）は満点にも数えない。"""

    def __init__(self):
        self.score = 0
        self.max = 0

    def chk(self, cond):
        if cond is None:
            return
        self.max += 1
        self.score += 1 if cond else 0


def one_off_flag(net_income=None, op_income=None, roe_fwd=None, roe_act=None):
    """一時的な利益の目印（AI の代わり）。
    条件: 純利益 > 営業利益 × 1.3  または  予想ROE > 実績ROE × 2
    （営業利益・実績ROE が正のときだけ判定。符号が逆のときは比率に意味がない）"""
    reasons = []
    if net_income is not None and op_income is not None and op_income > 0 and net_income > op_income * 1.3:
        reasons.append("純利益が営業利益の1.3倍超")
    if roe_fwd is not None and roe_act is not None and roe_act > 0 and roe_fwd > roe_act * 2:
        reasons.append("予想ROEが実績ROEの2倍超")
    return {"flag": bool(reasons), "reasons": reasons, "note": ONE_OFF_NOTE if reasons else ""}


def magic_rank(rows, ey_key, roc_key, skip=lambda r: False, out_key="magic_rank"):
    """魔法の公式: 益回りの順位 + 資本利益率の順位 の合計で並べ直した順位（1=最良）。rows を書き換える。"""
    nf = [r for r in rows if not skip(r) and r.get(ey_key) is not None and r.get(roc_key) is not None]
    rk = {}
    for k in (ey_key, roc_key):
        for i, r in enumerate(sorted(nf, key=lambda r: -r[k]), 1):
            rk.setdefault(id(r), 0)
            rk[id(r)] += i
    for i, r in enumerate(sorted(nf, key=lambda r: rk[id(r)]), 1):
        r[out_key] = i
    return rows
