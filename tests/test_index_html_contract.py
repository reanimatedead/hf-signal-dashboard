"""index.html が SPEC_MONEYFLOW §3, §4 の構造を持つか静的検査。

- 8 タブ厳格 (旧 11 タブ構成を残さない)。
- 背景 canvas (#bg-fx) が body 直下に存在。
- 共有粒子モジュール (assets/lib/particles.js) を読み込む。
- お金の流れ pane に 3 地域分の canvas が宣言されている。
"""
import pathlib
import re

INDEX = pathlib.Path(__file__).resolve().parents[1] / "docs" / "index.html"
PARTICLES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "lib" / "particles.js"


def _read():
    return INDEX.read_text(encoding="utf-8")


def test_index_exists():
    assert INDEX.exists(), "docs/index.html must exist"


def test_exactly_eight_main_tabs():
    html = _read()
    # main tab buttons are `<button class="tab" ...>` (active variant allowed)
    tabs = re.findall(r'<button[^>]*class="tab(?:\s+active)?"[^>]*data-tab="([^"]+)"', html)
    assert len(tabs) == 8, f"expected 8 main tabs, found {len(tabs)}: {tabs}"
    expected = {
        "nikkei225", "dow30", "nasdaq100", "sp500",
        "fx", "rates_vol", "pos_val", "moneyflow",
    }
    assert set(tabs) == expected, f"unexpected tab set: {set(tabs) ^ expected}"


def test_no_legacy_independent_tabs():
    html = _read()
    legacy = ["sw('rates'", "sw('volatility'", "sw('imm'", "sw('crypto'", "sw('valuation'"]
    for l in legacy:
        assert l not in html, f"legacy tab call '{l}' must be removed"


def test_background_canvas_present():
    html = _read()
    assert 'id="bg-fx"' in html, "background canvas #bg-fx must be present"
    assert 'aria-hidden="true"' in html
    assert 'pointer-events:none' in html or 'pointer-events: none' in html


def test_shared_particles_module_referenced():
    html = _read()
    assert 'assets/lib/particles.js' in html, (
        "shared particle engine must be referenced from index.html"
    )
    assert PARTICLES.exists(), "docs/assets/lib/particles.js must exist"


def test_money_flow_three_region_canvases():
    html = _read()
    for region in ("us", "eu", "jp"):
        assert f'id="mf-cv-{region}"' in html, (
            f"money flow region canvas #mf-cv-{region} missing"
        )


def test_bg_mode_toggle_present():
    html = _read()
    assert 'id="bgbtn"' in html, "background mode toggle button (#bgbtn) must be present"


def test_localstorage_keys_used():
    html = _read()
    assert 'hf_bg_mode' in html
    assert 'hf_theme' in html
