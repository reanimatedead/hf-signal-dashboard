"""規約（ADR-002）: 日本株の PER・PBR・理論株価・スコアの割安の点は J-Quants 由来なので公開しない。
公開の日本株のスコアはチャートの点だけ。米国株・ETF の売買スコアと検証の段階別成績は公開に出る。"""
import json
import pathlib

import pytest

from marketcalc import score

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"
JP_FORBIDDEN = ("PER", "PBR", "per_fwd", "per_act", "fair_price", "upside_pct", "fair_pbr", "roe_act_pct", "roe_fwd_pct",
                "div_yield_fwd_pct", "equity_ratio_pct", "turnover_20d", "next_earnings", "value_quintile", "grade")


@pytest.fixture(scope="module")
def preview(tmp_path_factory):
    from tools import build_preview

    out = tmp_path_factory.mktemp("preview_score") / "site"
    build_preview.build(out)
    return out


def _jp_public_ok(d, v):
    rows = [r for r in d["markets"]["nikkei225"] if not str(r.get("symbol", "")).startswith("^")]
    assert rows
    for r in rows:
        bad = [k for k in JP_FORBIDDEN if r.get(k) is not None]
        assert not bad, f"{r['symbol']}: J-Quants 由来の項目が公開に出ている {bad}"
        assert r.get("score_value") is None and r.get("score_quality") is None and r.get("score_penalty") is None
        if r.get("score") is not None:
            assert r["score"] == r["score_chart"]          # 公開の日本株はチャートの点だけ
    t = (v.get("score_tiers") or {}).get("nikkei225")
    assert t and t["parts"] == list(score.CHART_ONLY)


def test_preview_public_japan_is_chart_only(preview):
    d = json.loads((preview / "data.json").read_text())
    v = json.loads((preview / "verify.json").read_text())
    _jp_public_ok(d, v)
    us = [r for r in d["markets"]["nasdaq100"] if not r["symbol"].startswith("^")]
    assert any(r.get("score_value") is not None and r.get("PER") is not None for r in us)
    etf = {r["symbol"]: r for r in d["markets"]["etf"]}
    assert etf["1357.T"]["etf_kind"] == "inverse" and etf["1357.T"]["score"] is None
    assert etf["1306.T"]["score"] is not None
    assert set(v["score_tiers"]) == {"nikkei225", "us", "etf"}
    for t in v["score_tiers"].values():
        assert set(t["full"]) == {"base", *score.TIER_KEYS} and "recent6m" in t
    assert v["etf"]["symbols"]["1357.T"]["scored"] is False and "chart" in v["etf"]["symbols"]["1306.T"]
    a = json.loads((preview / "about.json").read_text())
    assert a["rules"]["score"]["weights"] == score.W               # 配分は1か所から自動で出る
    assert "etf" in a["tabs"]


def test_live_data_json_japan_is_chart_only():
    p, vp = DOCS / "data.json", DOCS / "verify.json"
    if not p.exists() or not vp.exists():
        pytest.skip("docs/data.json・docs/verify.json が無い（生成後の full ジョブで確かめる）")
    d = json.loads(p.read_text())
    if "etf" not in d.get("markets", {}):
        pytest.skip("古い data.json（ETF・スコアの無い版）")
    _jp_public_ok(d, json.loads(vp.read_text()))
