"""fetch_signals._build_money_flow を単体で呼んでも 3 地域分の契約を満たすか確認。

- ネットワーク失敗時は placeholder で必須キーを埋めること。
- 1 ティッカー失敗が全体破綻にならないこと (graceful degradation)。
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location(
        "fetch_signals", ROOT / "fetch_signals.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_money_flow_returns_three_regions():
    fs = _load()
    assert hasattr(fs, "_build_money_flow"), (
        "fetch_signals must expose _build_money_flow() (Agent B 担当)"
    )
    mf = fs._build_money_flow()
    assert isinstance(mf, dict)
    for region in ("us", "eu", "jp"):
        assert region in mf
        block = mf[region]
        assert block["region"] == region
        for k in ("cb_assets", "debt", "freshness_badge"):
            assert k in block, f"{region}.{k} missing"


def test_money_flow_graceful_degradation():
    fs = _load()
    mf = fs._build_money_flow()
    # 失敗系列があっても値が null になるだけで例外/欠落しない。
    for region in ("us", "eu", "jp"):
        block = mf[region]
        cb = block["cb_assets"]
        assert "value_usd_tn" in cb
        assert "data_status" in cb
        assert cb["data_status"] in {
            "live", "weekly", "monthly", "quarterly",
            "stale", "placeholder",
        }


def test_us_block_has_net_liquidity_components():
    fs = _load()
    mf = fs._build_money_flow()
    nl = mf["us"]["net_liquidity"]
    # net_liquidity がオブジェクトのときは components を伴う。null も許容。
    if nl is not None:
        assert "components" in nl
        for k in ("walcl", "tga", "rrp"):
            assert k in nl["components"]
