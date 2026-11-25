"""pipeline/build_gamma.py: 元データの優先順（ローカルアーカイブ → CBOE → yfinance SPY）と SPY 換算。

2026-11-25: cdn.cboe.com が cdn-api.cboe.com に転送され、Cloudflare が 403 を返すようになった（全クライアント）。
ネットワークは使わない（合成の fixture と monkeypatch だけ）。
"""
import datetime as dt
import gzip
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build_gamma as bg  # noqa: E402

FX = json.loads((ROOT / "tests" / "fixtures" / "gamma_spy_chain_sample.json").read_text())
TODAY = dt.date.fromisoformat(FX["today"])
NOW = dt.datetime(2026, 11, 24, 21, 0, tzinfo=dt.timezone.utc)


class FakeTicker:
    calls = []

    def __init__(self, sym, extra_exps=()):
        self.sym = sym
        self._extra = list(extra_exps)

    def history(self, period="5d"):
        px = {"SPY": FX["spy_close"], "^GSPC": FX["spx_close"], "^VIX": 15.25, "^VIX3M": 17.5, "^SKEW": 140.1}
        if self.sym not in px:
            raise RuntimeError("no data")
        return pd.DataFrame({"Close": [px[self.sym] * 0.99, px[self.sym]]})

    @property
    def options(self):
        return tuple(sorted(list(FX["expirations"]) + self._extra))

    def option_chain(self, e):
        FakeTicker.calls.append(e)
        x = FX["expirations"].get(e, {"calls": [], "puts": []})
        cols = ["strike", "openInterest", "impliedVolatility", "volume"]
        return SimpleNamespace(calls=pd.DataFrame(x["calls"], columns=cols), puts=pd.DataFrame(x["puts"], columns=cols))


def fake_yf(no_spx=False, extra_exps=()):
    def ticker(sym):
        if no_spx and sym == "^GSPC":
            return SimpleNamespace(history=lambda period="5d": pd.DataFrame({"Close": []}))
        return FakeTicker(sym, extra_exps)

    return SimpleNamespace(Ticker=ticker)


def yf_loader(**kw):
    return lambda: bg.load_chain_yf(yf_mod=fake_yf(**kw), today=TODAY, now=NOW)


def cboe_403():
    raise urllib.error.HTTPError(bg.CHAIN_LIVE, 403, "Forbidden", {}, None)


@pytest.fixture
def out(tmp_path, monkeypatch):
    p = tmp_path / "gamma.json"
    monkeypatch.setattr(bg, "OUT", p)
    monkeypatch.setattr(bg, "DATA_JSON", tmp_path / "no-data.json")
    FakeTicker.calls = []
    return p


def run(out, tmp_path, **kw):
    kw.setdefault("chain_dir", str(tmp_path / "no-archive"))
    kw.setdefault("cboe", cboe_403)
    kw.setdefault("yf_loader", yf_loader())
    kw.setdefault("csv", lambda name: None)
    kw.setdefault("yf_close", lambda sym: None)
    assert bg.main(**kw) == 0
    return json.loads(out.read_text())


def test_spy_proxy_gives_live_payload_on_spx_scale(out, tmp_path):
    p = run(out, tmp_path, yf_close=lambda s: {"^VIX": 15.0, "^VIX3M": 16.5, "^SKEW": 140.0}[s])
    assert p["data_status"] == "live" and p["proxy"] == "SPY" and p["scale_ratio"] == 10.0
    assert p["snapshot"]["source"] == "yfinance:SPY_proxy_scaled_to_SPX"
    assert p["spot"] == 6000.0  # SPY 600 × 10
    assert p["gamma_walls"] and all(5400 <= w["strike"] <= 6600 for w in p["gamma_walls"])
    assert p["zero_gamma"] is not None and 5100 <= p["zero_gamma"] <= 6900
    assert p["gex_oi"] is not None and p["flip_vs_spot"] in ("below_flip_amplifying", "above_flip_dampening")
    # fixture の 5 満期のうち 2027-03-19 は 115 日先なので取らない（60 日以内だけ）→ 4 満期。
    # 各満期 (25+1) 行 × 2 のうち、OI 0 と IV 0 の行は除く
    assert p["n_contracts_oi"] == 4 * 25 * 2
    assert len(FakeTicker.calls) == 4 and "2027-03-19" not in FakeTicker.calls  # 満期1本につき1回
    # 変えないキーは全部残る（追加は proxy と scale_ratio だけ）
    keep = {"as_of", "snapshot", "data_status", "spot", "n_contracts_oi", "gex_oi", "gex_oi_bn", "zero_gamma",
            "flip_vs_spot", "gamma_walls", "gex_volume_0dte", "gex_volume_0dte_bn", "gex_volume_0dte_status",
            "gex_volume_0dte_reason", "n_0dte_volume", "n_0dte_contracts", "vol_structure", "assumption", "note",
            "reading", "zero_dte_note", "coverage", "coverage_note", "disclaimer"}
    assert set(p) == keep | {"proxy", "scale_ratio"}
    assert p["vol_structure"]["vix"] == 15.0 and p["vol_structure"]["term_state"] == "contango"


def test_expiry_filter_60_days_and_max_12():
    far = ["2027-06-18"]  # 60 日より先は取らない
    many = [(TODAY + dt.timedelta(days=d)).isoformat() for d in range(1, 30, 2)]  # 15 本
    FakeTicker.calls = []
    c = bg.load_chain_yf(yf_mod=fake_yf(extra_exps=far + many), today=TODAY, now=NOW)
    assert len(FakeTicker.calls) == 12 and "2027-06-18" not in FakeTicker.calls
    assert c["proxy"] == "SPY" and c["recs"]


def test_time_budget_stops_fetching():
    ticks = iter([0, 0, 50, 95, 200, 300, 400])
    FakeTicker.calls = []
    bg.load_chain_yf(yf_mod=fake_yf(), today=TODAY, now=NOW, clock=lambda: next(ticks), budget_s=90)
    assert len(FakeTicker.calls) == 2  # 90 秒を超えたら残りの満期は取らない


def test_ratio_defaults_to_10_when_spx_missing(capsys):
    c = bg.load_chain_yf(yf_mod=fake_yf(no_spx=True), today=TODAY, now=NOW)
    assert c["scale_ratio"] == 10.0 and "scale_ratio_note" in capsys.readouterr().out


def test_dollar_gex_is_scale_invariant_with_contract_conversion():
    """S と K を10倍、gamma を1/10、建玉を1/10（SPX 換算の枚数）→ ドル建て GEX は同じ。
    建玉を換算しないと 10 倍になる（gamma×S² は S に比例するため）。"""
    S = 600.0
    recs = [(cp, float(k), 30 / 365, 0.2, bg.bs_gamma(S, k, 30 / 365, 0.2), 1000.0 if cp == "C" else 600.0, 10.0, TODAY)
            for k in range(540, 665, 5) for cp in ("C", "P")]  # コールとプットの建玉を変える（同じだと GEX が 0）
    assert bg.gex_at(recs, S) > 0
    r = 10.0
    scaled = [(cp, K * r, T, iv, g / r, oi / r, v / r, e) for cp, K, T, iv, g, oi, v, e in recs]
    a, b = bg.gex_at(recs, S), bg.gex_at(scaled, S * r)
    assert abs(a - b) <= 1e-9 * max(abs(a), 1.0)
    wa = sum(v for _, v in bg.gamma_walls(recs, S, bucket=2.5, top=999))
    wb = sum(v for _, v in bg.gamma_walls(scaled, S * r, bucket=25, top=999))
    assert abs(wa - wb) <= 1e-9 * max(abs(wa), 1.0)
    unconverted = [(cp, K * r, T, iv, g / r, oi, v, e) for cp, K, T, iv, g, oi, v, e in recs]
    assert abs(bg.gex_at(unconverted, S * r) / a - r) < 1e-9


def test_bs_gamma_matches_scipy_free_formula():
    g = bg.bs_gamma(100.0, 100.0, 0.25, 0.2, r=0.0)
    # ATM: d1 = 0.05 → pdf(0.05)/(100·0.2·0.5)
    import math

    assert abs(g - math.exp(-0.5 * 0.05**2) / math.sqrt(2 * math.pi) / 10.0) < 1e-12
    assert bg.bs_gamma(100.0, 100.0, 0.25, 0.0) == 0.0


def test_cboe_403_falls_back_to_yfinance(out, tmp_path):
    p = run(out, tmp_path, cboe=cboe_403)
    assert p["data_status"] == "live" and p["proxy"] == "SPY"


def test_all_sources_fail_gives_error_payload_and_no_exception(out, tmp_path):
    def yf_boom():
        raise RuntimeError("yahoo down")

    p = run(out, tmp_path, cboe=cboe_403, yf_loader=yf_boom)
    assert p["data_status"] == "error" and p["note"] == "chain_unavailable_degraded"
    assert "proxy" not in p  # error payload は変えない


def _cboe_chain(spot=6000.0):
    opts = []
    for k in range(5400, 6650, 50):
        for cp in ("C", "P"):
            opts.append({"option": f"SPXW261219{cp}{k * 1000:08d}", "open_interest": 100, "iv": 0.2,
                         "gamma": 0.001, "volume": 5})
    return {"timestamp": "2026-11-24 16:15:00", "data": {"close": spot, "options": opts}}


def test_cboe_live_still_used_first_when_it_works(out, tmp_path):
    p = run(out, tmp_path, cboe=lambda: (_cboe_chain(), "live:cboe-api"))
    assert p["snapshot"]["source"] == "live:cboe-api" and p["proxy"] is None and p["scale_ratio"] is None
    assert p["data_status"] == "live" and p["spot"] == 6000.0


def _write_archive(d, day):
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"SPX-{day.isoformat()}.json.gz", "wt") as f:
        json.dump(_cboe_chain(), f)


def test_archive_older_than_4_days_is_ignored(tmp_path, capsys):
    d = tmp_path / "chains"
    _write_archive(d, TODAY - dt.timedelta(days=5))
    assert bg.load_chain_archive(TODAY, str(d)) is None
    assert "5 days old" in capsys.readouterr().out
    _write_archive(d, TODAY - dt.timedelta(days=3))
    got = bg.load_chain_archive(TODAY, str(d))
    assert got is not None and got[1] == f"local:SPX-{(TODAY - dt.timedelta(days=3)).isoformat()}.json.gz"


def test_old_archive_falls_through_to_next_source(out, tmp_path):
    d = tmp_path / "chains"
    _write_archive(d, NOW.date() - dt.timedelta(days=5))
    p = run(out, tmp_path, chain_dir=str(d))
    assert p["proxy"] == "SPY"  # 古いアーカイブ → CBOE 403 → yfinance


def test_vol_structure_falls_back_to_yfinance_then_null():
    v = bg.vol_inputs(csv=lambda n: None, yf_close=lambda s: {"^VIX": 15.0, "^VIX3M": 16.0, "^SKEW": 139.0}[s])
    assert v == {"vix": 15.0, "vix3m": 16.0, "skew": 139.0}
    v = bg.vol_inputs(csv=lambda n: 20.0 if n == "VIX_History.csv" else None, yf_close=lambda s: None)
    assert v == {"vix": 20.0, "vix3m": None, "skew": None}  # CSV が取れた分は CSV、両方だめなら None
    assert bg._yf_index_close("^VIX", yf_mod=fake_yf()) == 15.25


def test_vol_structure_null_in_payload_when_both_fail(out, tmp_path):
    p = run(out, tmp_path)
    vs = p["vol_structure"]
    assert vs["vix"] is None and vs["vix3m"] is None and vs["skew"] is None and vs["term_state"] == "unknown"


def test_no_cloudflare_workaround_strings():
    src = (ROOT / "pipeline" / "build_gamma.py").read_text(encoding="utf-8")
    for bad in ("Referer", "Origin", "cf_clearance", "Mozilla/5.0"):
        assert bad not in src, bad
