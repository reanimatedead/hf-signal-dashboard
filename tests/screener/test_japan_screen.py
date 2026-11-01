"""screener.japan.screen: 理論株価・F・魔法の公式・分割前後の PBR・一時利益の目印（架空データ）。"""

import json

import pytest

from screener.calc.value import RI, ri_ratio
from screener.dates import jp_anchor_dates
from screener.japan import screen


@pytest.fixture
def rows(cfg):
    return {r["code"]: r for r in screen.screen(*jp_anchor_dates(cfg), cfg=cfg)}


def _fy(cfg, code):
    fy = screen.load_fy(cfg, "2099-01-01")[code]
    return [fy[k] for k in sorted(fy)]


def _bars(cfg, d):
    return json.loads(cfg.jp(f"bars_{d}.json").read_text())


def test_theory_price(cfg, rows):
    a = jp_anchor_dates(cfg)
    bar = {b["Code"]: b for b in _bars(cfg, a[1])}["10010"]
    pre, cur = _fy(cfg, "10010")
    roe_fwd = float(cur["NxFEPS"]) / float(cur["BPS"])
    pbr = bar["MktCap"] * 1e6 / float(cur["ShEq"])
    want = bar["AdjC"] * ri_ratio(roe_fwd, RI) / pbr
    r = rows["1001"]
    assert r["fair_price"] == round(want)
    assert r["upside_pct"] == round(100 * (want / bar["AdjC"] - 1), 1)
    assert r["fair_pbr"] == round(ri_ratio(roe_fwd, RI), 2)


def test_f_score(rows):
    assert (rows["1001"]["F"], rows["1001"]["f_max"]) == (8, 8)  # 架空A は全項目が改善する形
    assert rows["1005"]["f_max"] < 8  # 金融は営業利益・売上が空欄 → 数えない


def test_magic_formula_rank(rows):
    nf = [r for r in rows.values() if not r["financial"]]
    assert sorted(r["magic_rank"] for r in nf) == list(range(1, len(nf) + 1))
    assert "magic_rank" not in rows["1005"]  # 金融は順位を付けない
    ey = {c: r["earnings_yield_pct"] for c, r in rows.items() if not r["financial"]}
    roa = {c: r["roa_op_pct"] for c, r in rows.items() if not r["financial"]}
    score = {
        c: sorted(ey.values(), reverse=True).index(ey[c]) + sorted(roa.values(), reverse=True).index(roa[c]) for c in ey
    }
    assert rows[min(score, key=score.get)]["magic_rank"] == 1


def test_pbr_stable_across_split(cfg):
    """1:2 の株式分割の前後で、株価が半分になっても PBR（時価総額÷自己資本）と上値余地%は変わらない。"""
    a = jp_anchor_dates(cfg)
    bars = _bars(cfg, a[1])
    pre = [dict(b) for b in bars]
    post = [dict(b) for b in bars]
    for b in pre:
        if b["Code"] == "10030":
            b["AdjC"] = b["C"] = round(b["AdjC"] * 2, 2)  # 分割前: 株価2倍・株数半分 → 時価総額は同じ
    cfg.jp("bars_2099-01-05.json").write_text(json.dumps(pre))
    cfg.jp("bars_2099-01-06.json").write_text(json.dumps(post))
    rb = {r["code"]: r for r in screen.screen(a[0], "2099-01-05", a[2], a[3], a[4], cfg=cfg)}["1003"]
    ra = {r["code"]: r for r in screen.screen(a[0], "2099-01-06", a[2], a[3], a[4], cfg=cfg)}["1003"]
    assert rb["price"] == pytest.approx(2 * ra["price"], rel=1e-3)
    assert rb["PBR"] == ra["PBR"] and rb["upside_pct"] == ra["upside_pct"]
    cur = _fy(cfg, "10030")[-1]
    naive = rb["price"] / float(cur["BPS"])  # 分割前の株価 ÷ 分割後の BPS（ずれる計算）
    assert naive == pytest.approx(2 * ra["PBR"], rel=0.02)


def test_one_off_flag(rows):
    r = rows["1003"]  # 純利益 > 営業利益×1.3
    assert r["one_off_flag"] is True
    assert r["one_off_note"] == "check_earnings_release"
    assert "net_income_gt_op_income_1_3x" in r["one_off_reasons"]
    assert rows["1001"]["one_off_flag"] is False and rows["1001"]["one_off_note"] == ""


def test_quarterly_and_future_disclosures_ignored(cfg):
    fy = screen.load_fy(cfg, "2026-05-14")  # 2026-05-14 の開示は「その日より前」ではない
    assert sorted(fy["10010"]) == ["2025-03-31"]
    fy = screen.load_fy(cfg, "2099-01-01")
    assert all(r["DocType"].startswith("FY") for d in fy.values() for r in d.values())
