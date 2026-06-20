"""SPEC_MONEYFLOW.md §1, §6 を裏取りする契約テスト。

- このテストは実装より先にコミットされる (spec-first)。
- 実装中にテストを書き換えて契約をねじ曲げない。
- 失敗時は実装側を直すこと。
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_JSON = ROOT / "docs" / "data.json"

ALLOWED_STATUS = {
    "live", "weekly", "monthly", "quarterly", "stale",
    "placeholder", "auto_mof", "manual_csv",
}
ALLOWED_BADGE = {"daily", "weekly", "monthly", "quarterly", "stale"}
REQUIRED_REGION_KEYS = {
    "region", "cb_assets", "tga", "rrp", "net_liquidity",
    "debt", "freshness_badge",
}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@pytest.fixture(scope="module")
def data():
    if not DATA_JSON.exists():
        pytest.skip(f"{DATA_JSON} not generated yet; run fetch_signals.py")
    with DATA_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def mf(data):
    assert "money_flow" in data, "data.json must expose top-level 'money_flow'"
    return data["money_flow"]


def test_money_flow_top_level_has_as_of(mf):
    assert "as_of" in mf
    assert isinstance(mf["as_of"], str) and len(mf["as_of"]) >= 10


def test_money_flow_has_all_three_regions(mf):
    for region in ("us", "eu", "jp"):
        assert region in mf, f"money_flow.{region} missing"


@pytest.mark.parametrize("region", ["us", "eu", "jp"])
def test_region_block_required_keys(mf, region):
    block = mf[region]
    missing = REQUIRED_REGION_KEYS - set(block.keys())
    assert not missing, f"money_flow.{region} missing keys: {missing}"
    assert block["region"] == region


@pytest.mark.parametrize("region", ["us", "eu", "jp"])
def test_cb_assets_contract(mf, region):
    cb = mf[region]["cb_assets"]
    for k in ("label", "value_usd_tn", "unit", "as_of", "lag_days", "data_status", "source"):
        assert k in cb, f"{region}.cb_assets.{k} missing"
    assert cb["data_status"] in ALLOWED_STATUS
    assert cb["unit"] in {"USD_TN", "EUR_TN", "JPY_TN"}
    if cb["data_status"] != "placeholder":
        assert isinstance(cb["lag_days"], int)
        assert ISO_DATE.match(str(cb["as_of"])), cb["as_of"]


@pytest.mark.parametrize("region", ["us", "eu", "jp"])
def test_debt_contract(mf, region):
    d = mf[region]["debt"]
    for k in ("label", "value_local_tn", "unit", "as_of", "lag_days", "data_status", "source"):
        assert k in d, f"{region}.debt.{k} missing"
    assert d["data_status"] in ALLOWED_STATUS


def test_us_specific_series_present(mf):
    us = mf["us"]
    # US だけ tga/rrp/net_liquidity を持つ。null や placeholder で許容。
    for k in ("tga", "rrp", "net_liquidity"):
        assert k in us, f"money_flow.us.{k} required"


def test_eu_jp_specific_series_are_null(mf):
    for region in ("eu", "jp"):
        block = mf[region]
        for k in ("tga", "rrp", "net_liquidity"):
            assert block.get(k) is None, (
                f"money_flow.{region}.{k} must be null (TGA/RRP/net_liquidity are US-only)"
            )


def test_us_debt_has_change_prev_day(mf):
    d = mf["us"]["debt"]
    assert "change_prev_day" in d, "US debt must expose change_prev_day"


@pytest.mark.parametrize("region", ["eu", "jp"])
def test_eu_jp_debt_no_daily_delta(mf, region):
    d = mf[region]["debt"]
    # 日次差はだしてはいけない (quarterly/yearly のため)。null 必須。
    assert d.get("change_prev_day") is None, (
        f"money_flow.{region}.debt.change_prev_day must be null"
    )


@pytest.mark.parametrize("region", ["us", "eu", "jp"])
def test_freshness_badge_valid(mf, region):
    badge = mf[region]["freshness_badge"]
    assert badge in ALLOWED_BADGE, f"{region}.freshness_badge={badge}"


def test_no_fabricated_values(mf):
    """data_status=placeholder の系列の value_* は必ず null (捏造禁止)。"""
    for region in ("us", "eu", "jp"):
        block = mf[region]
        for series_key in ("cb_assets", "debt"):
            s = block[series_key]
            if s.get("data_status") == "placeholder":
                for v in ("value_usd_tn", "value_local_tn"):
                    if v in s:
                        assert s[v] is None, (
                            f"{region}.{series_key}.{v} must be null when placeholder"
                        )
