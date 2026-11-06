"""株数の選び方（fund_us.pick_shares）: 表紙の株数が古い・1クラス分だけのときは希薄化後の加重平均株数。"""

from screener.calc import fund_us


def _F(dei, dsh):
    return {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}},
        "us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": dsh}}},
    }


def _v(val, end, filed, form="10-Q"):
    return {"val": val, "end": end, "filed": filed, "form": form}


DSH = [_v(906_000_000, "2026-09-30", "2026-10-30")]


def test_stale_dei_uses_diluted():  # MA: 表紙の株数が 2010 年のまま
    F = _F([_v(122_530_193, "2010-10-27", "2010-11-02")], DSH)
    assert fund_us.pick_shares(F, "2026-11-06") == (906_000_000, "dsh")


def test_bogus_dei_uses_diluted():  # FOX: 表紙が 1 株
    F = _F([_v(1, "2026-08-01", "2026-08-05")], DSH)
    assert fund_us.pick_shares(F, "2026-11-06") == (906_000_000, "dsh")


def test_one_class_dei_uses_diluted():  # 表紙が1クラス分だけ（希薄化後の半分）
    F = _F([_v(450_000_000, "2026-10-20", "2026-10-30")], DSH)
    assert fund_us.pick_shares(F, "2026-11-06")[1] == "dsh"


def test_fresh_consistent_dei_kept_and_split_adjusted():
    F = _F([_v(14_500_000_000, "2026-10-17", "2026-10-31")], [_v(14_700_000_000, "2026-09-27", "2026-10-31")])
    assert fund_us.pick_shares(F, "2026-11-06") == (14_500_000_000, "dei")
    sp = [("2026-11-01", 2.0)]
    assert fund_us.pick_shares(F, "2026-11-06", sp) == (29_000_000_000, "dei")


def test_no_diluted_keeps_dei():
    F = _F([_v(100, "2010-01-01", "2010-02-01")], [])
    assert fund_us.pick_shares(F, "2026-11-06") == (100, "dei")


def test_dsh_unit_error_keeps_dei():  # MCD: dsh が百万単位（712.3）、WAT: dsh が 1000 倍
    F = _F([_v(707_641_531, "2026-10-20", "2026-10-30")], [_v(712.3, "2026-09-30", "2026-10-30")])
    assert fund_us.pick_shares(F, "2026-11-06") == (707_641_531, "dei")
    F = _F([_v(98_248_111, "2026-10-20", "2026-10-30")], [_v(90_041_000_000, "2026-09-30", "2026-10-30")])
    assert fund_us.pick_shares(F, "2026-11-06") == (98_248_111, "dei")


def test_implied_shares_decides():  # 純利益 ÷ 希薄化後 EPS に近い方
    F = _F([_v(450_000_000, "2026-10-20", "2026-10-30")], DSH)
    F["us-gaap"]["NetIncomeLoss"] = {
        "units": {
            "USD": [
                {
                    "val": 4.5e9,
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "filed": "2026-02-10",
                    "form": "10-K",
                    "fp": "FY",
                }
            ]
        }
    }
    F["us-gaap"]["EarningsPerShareDiluted"] = {
        "units": {
            "USD/shares": [
                {
                    "val": 10.0,
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "filed": "2026-02-10",
                    "form": "10-K",
                    "fp": "FY",
                }
            ]
        }
    }
    assert fund_us.pick_shares(F, "2026-11-06") == (450_000_000, "dei")


# ── 米国株の理論株価: 業種別 PER の中央値（fund_us.per_benchmarks / relative_value / rerate_month）──


def test_per_benchmarks_levels():
    pers = {f"S{i}": 10.0 + i for i in range(8)}  # SIC 35 に 8 社（中央値 13.5）
    pers.update({"T1": 40.0, "T2": 50.0})  # SIC 73 に 2 社 → 大分類 I にも足りない → 全体
    pers["L"] = -5.0  # 赤字は中央値に入れない
    sics = {**{f"S{i}": "3571" for i in range(8)}, "T1": "7372", "T2": "7370", "L": "3571"}
    bm = fund_us.per_benchmarks(pers, sics)
    assert bm["S0"] == (13.5, "sic2") and bm["L"] == (13.5, "sic2")
    assert bm["T1"][1] == "all" and bm["T1"][0] == 14.5  # 黒字 10 社の中央値


def test_relative_value_fair_and_upside():
    per_px = {f"S{i}": (20.0, 100.0) for i in range(8)}
    per_px["X"] = (10.0, 50.0)
    per_px["L"] = (None, 30.0)
    rv = fund_us.relative_value(per_px, {k: "2834" for k in per_px})
    assert rv["X"]["upside_pct"] == 100.0 and rv["X"]["fair_price"] == 100.0  # EPS 5 × 業種 PER 20
    assert rv["S0"]["upside_pct"] == 0.0
    assert rv["L"]["upside_pct"] is None and rv["L"]["fair_price"] is None


def test_rerate_month_keeps_pbr_per():
    vin = {f"S{i}": [-90.0, 3.0, 20.0, False] for i in range(8)}
    vin["X"] = [-95.0, 9.0, 40.0, True]
    out = fund_us.rerate_month(vin, {})
    assert out["X"] == [-50.0, 9.0, 40.0, True] and out["S0"][0] == 0.0
