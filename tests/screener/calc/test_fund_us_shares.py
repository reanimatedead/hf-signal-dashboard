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


# ── 「要確認」（fund_us.value_check）: PER 2 未満・上値余地 +500% 超 ──


def test_value_check_rules():
    assert fund_us.value_check(0.008, 170299.0) == "per_lt_2"  # BRK-B: A 株の EPS × B 株の株価
    assert fund_us.value_check(3.1, 607.0) == "upside_gt_500"
    assert fund_us.value_check(8.8, 149.0) is None
    assert fund_us.value_check(None, None) is None


def test_relative_value_flags_and_excludes_from_median():
    per_px = {f"S{i}": (20.0, 100.0) for i in range(8)}
    per_px["BRKB"] = (0.008, 572.0)
    rv = fund_us.relative_value(per_px, {k: "6331" for k in per_px})
    assert rv["BRKB"]["value_check"] == "per_lt_2" and rv["BRKB"]["fair_price"] is None
    assert rv["BRKB"]["upside_pct"] is None and rv["S0"]["per_bench"] == 20.0  # 中央値に入れない
    rows = [
        {"ticker": t, "price": px, "per_raw": per, "PER": round(per, 1), "PBR": 1.0} for t, (per, px) in per_px.items()
    ]
    fund_us.apply_relative(rows, {k: "6331" for k in per_px})
    b = next(r for r in rows if r["ticker"] == "BRKB")
    assert b["PER"] is None and b["PBR"] is None and b["value_check_per"] == 0.0


def test_rerate_month_blanks_flagged():
    vin = {f"S{i}": [0.0, 3.0, 20.0, False] for i in range(8)}
    vin["ERIE"] = [0.0, 0.1, 0.001, False]
    out = fund_us.rerate_month(vin, {})
    assert out["ERIE"] == [None, None, None, False]


def test_score_rows_value_zero_for_flagged():
    from screener.calc import score

    rows = [{"symbol": f"S{i}", "upside_pct": float(i), "PBR": 5.0 - i, "PER": 14.0 - i} for i in range(5)]
    rows.append({"symbol": "X", "upside_pct": None, "PBR": None, "PER": None, "value_check": "per_lt_2"})
    score.score_rows(rows, None, ("value",), market="us")
    x = rows[-1]
    assert x["score_value"] == 0.0 and x["score"] == 0.0
    assert rows[4]["score_value"] == 35.0  # 要確認は順位の母集団に入らない（最上位は満点）


def test_shares_mismatch_is_over_20_percent_only():
    assert not fund_us.shares_mismatch(120, 100) and fund_us.shares_mismatch(121, 100)
    assert fund_us.shares_mismatch(79, 100) and not fund_us.shares_mismatch(100, None)
    per_px = {f"S{i}": (20.0, 100.0) for i in range(8)}
    per_px["X"] = (8.4, 422.0)
    rv = fund_us.relative_value(per_px, {k: "7389" for k in per_px}, mismatch={"X": True})
    assert rv["X"]["value_check"] == "shares_mismatch" and rv["X"]["fair_price"] is None


def test_old_share_count_alone_is_not_flagged():
    """株数が 400 日より古くても、純利益 ÷ EPS と合っていれば要確認にしない（BLK・HSY）。"""
    F = _F([_v(469_280_842, "2010-01-27", "2010-02-01")], [])
    assert fund_us.value_check(25.0, 10.0) is None
    assert fund_us.pick_shares_end(F, "2026-11-06")[2] == "2010-01-27"


def test_upside_over_150_keeps_values_but_zero_points():
    per_px = {f"S{i}": (20.0, 100.0) for i in range(8)}
    per_px["ONE"] = (5.0, 50.0)  # 余地 +300%: 一時的な利益の可能性
    per_px["OK"] = (10.0, 50.0)  # 余地 +100%
    sics = {k: "6331" for k in per_px}
    rv = fund_us.relative_value(per_px, sics)
    assert rv["ONE"]["value_check"] == "upside_gt_150" and rv["ONE"]["upside_pct"] == 300.0
    assert rv["ONE"]["fair_price"] == 200.0 and rv["OK"]["value_check"] is None
    rows = [{"ticker": t, "price": px, "per_raw": per, "PER": per, "PBR": 1.0} for t, (per, px) in per_px.items()]
    fund_us.apply_relative(rows, sics)
    one = next(r for r in rows if r["ticker"] == "ONE")
    assert one["PER"] == 5.0 and one["PBR"] == 1.0 and one["ri_upside_pct"] == 300.0  # 画面には出す
    assert fund_us.value_check(5.0, 150.0) is None and fund_us.value_check(5.0, 150.1) == "upside_gt_150"


def test_score_zero_for_upside_over_150_and_out_of_ranking():
    from screener.calc import score

    rows = [{"symbol": f"S{i}", "upside_pct": float(i), "PBR": 5.0 - i, "PER": 14.0 - i} for i in range(5)]
    rows.append({"symbol": "X", "upside_pct": 300.0, "PBR": 1.0, "PER": 5.0, "value_check": "upside_gt_150"})
    score.score_rows(rows, None, ("value",), market="us")
    assert rows[-1]["score_value"] == 0.0 and rows[-1]["upside_pct"] == 300.0
    assert rows[4]["score_value"] == 35.0  # 順位の母集団に入らない（最上位は満点）


def test_rerate_month_blanks_upside_over_150():
    vin = {f"S{i}": [0.0, 3.0, 20.0, False] for i in range(8)}
    vin["ONE"] = [0.0, 1.0, 5.0, True]
    out = fund_us.rerate_month(vin, {})
    assert out["ONE"] == [None, None, None, True] and out["S0"][0] == 0.0


V_DOC = """<xbrli:context id="t26"><xbrli:instant>2026-09-30</xbrli:instant></xbrli:context>
<xbrli:context id="t25"><xbrli:instant>2025-09-30</xbrli:instant></xbrli:context>
<xbrli:context id="a26"><xbrli:instant>2026-09-30</xbrli:instant>
<xbrldi:explicitMember d="c">us-gaap:CommonClassAMember</xbrldi:explicitMember></xbrli:context>
<ix:nonFraction contextRef="t25" name="v:SharesOutstandingAsConvertedBasis" scale="6">1,930</ix:nonFraction>
<ix:nonFraction contextRef="a26" name="v:SharesOutstandingAsConvertedBasis" scale="6">1,728</ix:nonFraction>
<ix:nonFraction contextRef="t26" name="v:SharesOutstandingAsConvertedBasis" scale="6">1,867</ix:nonFraction>"""


def test_v_uses_latest_as_converted_total():
    assert fund_us.listed_class_shares("V", V_DOC) == 1_867_000_000
    assert fund_us.listed_class_shares("V", "<html></html>") is None


# ── 株の種類の換算（fund_us.SHARE_CLASSES）: 表紙の種類別の株数を、上場している種類にそろえる ──

_AX = 'dimension="us-gaap:StatementClassOfStockAxis"'
COVER = f"""<xbrli:context id="cA"><xbrli:entity>
<xbrldi:explicitMember {_AX}>us-gaap:CommonClassAMember</xbrldi:explicitMember></xbrli:entity></xbrli:context>
<xbrli:context id="cB"><xbrli:entity>
<xbrldi:explicitMember {_AX}>us-gaap:CommonClassBMember</xbrldi:explicitMember></xbrli:entity></xbrli:context>
<ix:nonFraction contextRef="cA" name="dei:EntityCommonStockSharesOutstanding" scale="0">{{a}}</ix:nonFraction>
<ix:nonFraction name="dei:EntityCommonStockSharesOutstanding" contextRef="cB"><span>{{b}}</span></ix:nonFraction>
<ix:nonFraction contextRef="cA" name="us-gaap:Other">9</ix:nonFraction>"""


def test_cover_shares_to_listed_class_brk_and_erie():
    brk = fund_us.cover_class_shares(COVER.format(a="488,450", b="1,408,035,161"))
    assert brk == {"us-gaap:CommonClassAMember": 488_450, "us-gaap:CommonClassBMember": 1_408_035_161}
    assert fund_us.class_equiv_shares("BRK-B", brk) == 488_450 * 1500 + 1_408_035_161
    erie = fund_us.cover_class_shares(COVER.format(a="46,189,068", b="2,542"))
    assert fund_us.class_equiv_shares("ERIE", erie) == 46_189_068 + 2_542 * 2400


def test_class_equiv_needs_every_class_and_a_listed_ticker():
    assert fund_us.class_equiv_shares("BRK-B", {"us-gaap:CommonClassBMember": 5}) is None  # A 株が読めない
    assert fund_us.class_equiv_shares("AAPL", {"us-gaap:CommonClassAMember": 5}) is None


def test_sh_fix_aligns_per_with_listed_class_price():
    """BRK-B: 純利益 670 億ドル ÷ 換算株数 21.4 億。B 株の株価 571 ドルで PER 18 前後（修正前は 0.0）。"""
    fd = {
        "sh": 2_140_710_161,
        "ni": 66_968_000_000,
        "eq": 717_419_000_000,
        "ebit": 1,
        "debt": 0,
        "cash": 0,
        "cap": 1,
        "roe": 0.09,
    }
    m = fund_us.metrics(fd, 570.89)
    assert 18 < m["PER"] < 18.5 and 1.6 < m["PBR"] < 1.8
    assert fund_us.value_check(m["per_raw"], None) is None
