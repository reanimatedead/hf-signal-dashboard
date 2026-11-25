"""gamma 層の SPY 代替（CBOE が 403 のとき yfinance の SPY オプションを SPX 水準へ換算）の表示と判定。

- gamma.json の proxy="SPY" のときだけ、ガンマ欄に「SPY オプションからの推定（SPX 換算）」の注記を出す。
- snapshot.source="yfinance:SPY_proxy_scaled_to_SPX" は日英とも訳語で出す（内部名をそのまま出さない）。
- proxy="SPY" でも data_status="live" なら layer_fallback.gamma_ok は正常と判定する（前回値に戻さない）。
"""
import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import layer_fallback as lf  # noqa: E402

INDEX = ROOT / "docs" / "index.html"
DICT = ROOT / "docs" / "assets" / "i18n" / "dict.js"
I18N = ROOT / "docs" / "assets" / "i18n" / "i18n.js"
SRC = "yfinance:SPY_proxy_scaled_to_SPX"

EXPECTED = {
    "ja": {"note": "SPY オプションからの推定（SPX 換算）", "source": "yfinance（SPY オプション・SPX 換算）"},
    "en": {"note": "Estimated from SPY options (scaled to SPX)", "source": "yfinance (SPY options, scaled to SPX)"},
}


def _node(js):
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def _i18n_prelude(lang):
    return (
        "global.window=global;"
        "Object.defineProperty(globalThis,'navigator',"
        f"{{value:{{languages:[{json.dumps(lang)}]}},configurable:true}});"
        "global.localStorage={getItem:()=>null,setItem:()=>{}};"
        "global.document={readyState:'complete',documentElement:{},querySelectorAll:()=>[]};"
        f"require({json.dumps(str(DICT))});require({json.dumps(str(I18N))});"
    )


def test_gamma_ok_accepts_live_spy_proxy():
    g = {"as_of": "2026-11-25T22:00:00+00:00", "data_status": "live", "proxy": "SPY", "scale_ratio": 10.03,
         "snapshot": {"source": SRC}}
    assert lf.gamma_ok(g) is True


def test_gamma_ok_still_rejects_error_even_with_proxy():
    assert lf.gamma_ok({"data_status": "error", "proxy": "SPY"}) is False


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_proxy_source_code_is_translated(lang):
    out = _node(_i18n_prelude(lang) + f"process.stdout.write(I18.code('source',{json.dumps(SRC)}))")
    assert out == EXPECTED[lang]["source"]


def _proxy_note_js():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"^\s*(const proxyNote=.*;)\s*$", html, re.M)
    assert m, "renderGamma に proxyNote の行が無い"
    assert "proxyNote+" in html, "proxyNote がガンマ欄の出力に入っていない"
    return m.group(1)


@pytest.mark.parametrize("lang", ["ja", "en"])
@pytest.mark.parametrize("proxy,shown", [("SPY", True), (None, False), ("__absent__", False)])
def test_proxy_note_only_when_spy(lang, proxy, shown):
    g = {"data_status": "live"} if proxy == "__absent__" else {"data_status": "live", "proxy": proxy}
    js = (_i18n_prelude(lang) + "const T=I18.T;"
          f"const G={json.dumps(g)};{_proxy_note_js()}process.stdout.write(proxyNote)")
    out = _node(js)
    if shown:
        assert out == f'<div class="rel-disc">{EXPECTED[lang]["note"]}</div>'
    else:
        assert out == ""
