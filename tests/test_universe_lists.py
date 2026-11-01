"""構成銘柄の内蔵一覧が全件（日経225=225±5%、Nasdaq-100=100±5%）で、形と重複が正しい。"""
import re

import fetch_signals as fs
from marketcalc.contracts import count_within


def test_nikkei225_full_count_and_shape():
    ok, msg = count_within("nikkei225", len(fs.NIKKEI225))
    assert ok, msg
    assert len(fs.NIKKEI225) == 225
    bad = [k for k in fs.NIKKEI225 if not re.fullmatch(r"\d{4}\.T", k)]
    assert not bad, bad
    assert "9613.T" not in fs.NIKKEI225          # NTT データは上場廃止


def test_nasdaq100_full_count_and_shape():
    ok, msg = count_within("nasdaq100", len(fs.NASDAQ100))
    assert ok, msg
    assert {"GOOG", "GOOGL"} <= set(fs.NASDAQ100)
    assert not {"ANSS", "EA"} & set(fs.NASDAQ100)   # 買収で上場廃止
    bad = [k for k in fs.NASDAQ100 if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,5}", k)]
    assert not bad, bad


def test_dow30_unchanged():
    assert len(fs.DOW30) == 30


def test_load_universe_prefers_file_within_tolerance(tmp_path):
    import json
    mem = {f"T{i:03d}": f"n{i}" for i in range(99)}
    (tmp_path / "nasdaq100.json").write_text(json.dumps({"members": mem}))
    d, src = fs.load_universe("nasdaq100", fs.NASDAQ100, udir=tmp_path)
    assert src == "file" and len(d) == 99
    # ±5% を外れたファイルは使わない（内蔵に戻す）
    (tmp_path / "nasdaq100.json").write_text(json.dumps({"members": dict(list(mem.items())[:50])}))
    d, src = fs.load_universe("nasdaq100", fs.NASDAQ100, udir=tmp_path)
    assert src == "builtin" and d == fs.NASDAQ100
    d, src = fs.load_universe("dow30", fs.DOW30, udir=tmp_path)      # ファイルが無い
    assert src == "builtin"
