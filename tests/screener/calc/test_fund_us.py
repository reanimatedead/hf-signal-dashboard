"""fund_us: 理論株価余地・F・魔法の公式の順位が計算でき、株式分割の前後で PBR が崩れない。"""
import copy
from screener.calc import fund_us, value

ASOF = "2026-06-30"


def rows(fx):
    out = []
    for t, info in fx["uni"].items():
        r = fund_us.screen_one(t, info, fx["facts"][t], fx["px"][t], ASOF, "2025-06-30", "2026-05-29")
        if r:
            out.append(r)
    return fund_us.rank(out)


def test_rows_and_f_score(fx):
    rs = rows(fx)
    assert len(rs) == 5
    for r in rs:
        assert r["F満点"] == 7 and r["F"] == 7           # サンプルは全項目が改善するように作ってある
        assert r["RI余地%"] is not None and r["PBR"] > 0


def test_magic_rank_excludes_financials(fx):
    rs = rows(fx)
    ranked = sorted([r for r in rs if r.get("魔法の公式順位")], key=lambda r: r["魔法の公式順位"])
    assert [r["魔法の公式順位"] for r in ranked] == [1, 2, 3, 4]
    assert all(not r["fin"] for r in ranked)
    assert "魔法の公式順位" not in next(r for r in rs if r["ticker"] == "EEE")


def test_magic_rank_hand():
    rs = [{"ey": 10, "roc": 1}, {"ey": 5, "roc": 30}, {"ey": 8, "roc": 20}]
    value.magic_rank(rs, "ey", "roc")
    # 順位和: 1+3=4, 3+1=4, 2+2=4 → 同点は安定ソートで元の順
    assert sorted(r["magic_rank"] for r in rs) == [1, 2, 3]


def test_pbr_stable_across_split(fx):
    """DDD は途中で 2:1 分割（株価は Yahoo と同じく分割調整後）。分割前に提出された株数は今の基準に直されるので、
    分割の前日と翌日で PBR は株価の動きの分しか変わらない（倍や半分に跳ねない）。"""
    p = fx["px"]["DDD"]; F = fx["facts"]["DDD"]
    i = p["d"].index(p["splits"][0][0])
    d0, d1 = p["d"][i - 1], p["d"][i + 1]
    a = fund_us.screen_one("DDD", fx["uni"]["DDD"], F, p, d0)
    b = fund_us.screen_one("DDD", fx["uni"]["DDD"], F, p, d1)
    pa = fund_us.price_at(p, d0, raw=True); pb = fund_us.price_at(p, d1, raw=True)
    assert abs((b["PBR"] / a["PBR"]) / (pb / pa) - 1) < 0.02
    assert 0.5 < b["PBR"] / a["PBR"] < 1.5


def test_fundamentals_point_in_time(fx):
    # 2025-02-15 提出の 10-K は、その日より前の asof では使えない（前期が最新になる）
    fd = fund_us.fundamentals(fx["facts"]["AAA"], "2025-01-31")
    assert fd["fy"] == "2023-12-31" and fd["sh"] > 0
    assert fund_us.fundamentals(fx["facts"]["AAA"], "2024-01-01") is None


def test_ri_ratio():
    assert abs(value.ri_ratio(0.08) - 1.0) < 1e-12           # ROE = 資本コスト → 理論PBR 1
    assert value.ri_ratio(0.20) > 1.0 > value.ri_ratio(0.02)
    assert value.ri_ratio(5.0) == value.ri_ratio(0.40)        # 上限で頭打ち
