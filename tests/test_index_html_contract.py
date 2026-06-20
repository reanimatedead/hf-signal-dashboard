"""index.html が SPEC_MONEYFLOW §3-4 と SPEC_SURVIVAL §5-6 の構造を持つか静的検査。

- 9 タブ厳格 (survival 既定先頭)。
- 背景 canvas (#bg-fx) が body 直下に存在。
- 共有粒子モジュール (assets/lib/particles.js) を読み込む。
- お金の流れ pane に 3 地域分の canvas が宣言されている。
- SURVIVAL pane / risk gate / survival.js を持つ。
"""
import pathlib
import re

INDEX = pathlib.Path(__file__).resolve().parents[1] / "docs" / "index.html"
PARTICLES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "lib" / "particles.js"


def _read():
    return INDEX.read_text(encoding="utf-8")


def test_index_exists():
    assert INDEX.exists(), "docs/index.html must exist"


def test_exactly_nine_main_tabs():
    html = _read()
    tabs = re.findall(r'<button[^>]*class="tab(?:\s+active)?"[^>]*data-tab="([^"]+)"', html)
    assert len(tabs) == 9, f"expected 9 main tabs (incl. survival), found {len(tabs)}: {tabs}"
    expected = {
        "survival",
        "nikkei225", "dow30", "nasdaq100", "sp500",
        "fx", "rates_vol", "pos_val", "moneyflow",
    }
    assert set(tabs) == expected, f"unexpected tab set: {set(tabs) ^ expected}"


def test_survival_is_default_active_tab():
    html = _read()
    m = re.search(r'<button[^>]*class="tab\s+active"[^>]*data-tab="([^"]+)"', html)
    assert m, "no active tab marker found"
    assert m.group(1) == "survival", (
        f"default active tab must be 'survival' (SPEC §5), got '{m.group(1)}'"
    )


def test_survival_pane_present():
    html = _read()
    assert 'id="survival-pane"' in html, "SURVIVAL pane (#survival-pane) missing"
    assert 'id="sv-risk-gate"' in html, "risk-gate banner (#sv-risk-gate) missing"


def test_survival_js_module_referenced():
    html = _read()
    assert 'assets/survival/survival.js' in html, "survival.js module must be loaded"
    survival_js = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "survival" / "survival.js"
    assert survival_js.exists(), "docs/assets/survival/survival.js must exist"


def test_localstorage_log_key_used():
    html = _read()
    survival_js_path = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "survival" / "survival.js"
    js = survival_js_path.read_text(encoding="utf-8") if survival_js_path.exists() else ""
    # 公開リポに値は書かないが、キー文字列は前面 (html or js) に存在しないと結線できない。
    assert "hf_survival_log_v1" in (html + js), (
        "localStorage key hf_survival_log_v1 must be referenced in index.html or survival.js (SPEC §5.1)"
    )


def test_notify_panel_present():
    html = _read()
    assert 'id="sv-notify"' in html, "SURVIVAL notify panel (#sv-notify) missing"
    assert 'assets/survival/notify_panel.js' in html, "notify_panel.js script not loaded"
    p = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "survival" / "notify_panel.js"
    assert p.exists(), "docs/assets/survival/notify_panel.js must exist"


def test_notify_panel_uses_public_jsonl_path():
    p = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "survival" / "notify_panel.js"
    js = p.read_text(encoding="utf-8")
    # SPEC §7: 公開安全な抜粋を data/notifications_public.jsonl から
    assert "notifications_public.jsonl" in js, (
        "panel must read from data/notifications_public.jsonl (SPEC §7)"
    )


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
