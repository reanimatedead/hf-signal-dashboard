"""tests/test_about.py — 仕組み（About）タブと docs/about.json（src/screener/about.py・docs/assets/about/about.js）。

1. 画面に出す期間・しきい値は ind.P から自動で作られている（P を変えると表示も変わる・規則は ind.day_labels と一致）
2. about.json は必須のキーを全部持つ
3. about.json と画面に J-Quants 由来のキー・Mac mini の出力の値が出ない
画面は about.js の render(about) を node でそのまま呼んで、見える文字（タグを除いた文字）で調べる。
"""

from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screener import about  # noqa: E402
from screener.calc import ind  # noqa: E402

DOCS = ROOT / "docs"
NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))
META = {
    "updated_at": "2026-11-03T07:35:00+09:00",
    "stale_hours": 48.0,
    "counts": {"nikkei225": 226, "dow30": 31, "fx": 18},
    "universe": {
        "nikkei225": {"count": 225, "target": 225, "source_mode": "curated_full", "universe_source": "builtin",
                      "fetch_failures": []},
        "dow30": {"count": 29, "target": 30, "source_mode": "dynamic", "universe_source": "file",
                  "fetch_failures": ["XYZ"]},
    },
    "fallbacks": [],
    "nan_report": {"nikkei225": {"constituents": 225, "price_null": 0, "chart_unavailable": 0}},
}
STAT = {"n": 10, "mean": 1.0, "median": 0.5, "up_pct": 55.0}
VERIFY = {
    "generated_at": "2026-11-03T07:40:00+09:00", "as_of": "2026-11-02", "weakened": True,
    "weakened_items": ["us_union:chart:buy"],
    "method": {"horizon_days": 20, "recent_months": 6, "base": "same_symbol_all_days_h20_mean"},
    "markets": {"us": {"label": "us_union", "symbols": 513, "last_date": "2026-11-02",
                       "full": {"base": STAT, "chart": {"buy": STAT}, "composite": {"buy": STAT}},
                       "recent6m": {"since": "2026-05-02", "base": STAT, "chart": {"buy": STAT}},
                       "weakened": {"chart:buy": True}}},
}
# J-Quants 由来（Mac mini 版だけ）の列名。src/screener/labels.COLUMNS と local_report の列から。
JQ_KEYS = {"fair_price", "upside_pct", "grade", "value_quintile", "quality_candidate", "fin_tag", "PBR", "F",
           "f_max", "mcap_oku_jpy", "one_off_note", "one_off_reasons", "company_name", "magic_rank", "f_score"}


def _build(**kw):
    return about.build(META, VERIFY, NOW, commit={"sha": "0123456789abcdef", "source": "test"}, **kw)


def _render(a: dict, lang: str) -> str:
    """about.js の render を node で呼び、見える文字（タグを除く）を返す。"""
    js = """
global.window = global;
global.localStorage = { getItem: () => %(lang)s, setItem: () => {} };
global.document = { readyState: "complete", documentElement: {}, querySelectorAll: () => [], title: "" };
require(%(dict)s); require(%(i18n)s); require(%(about)s);
process.stdout.write(window.ABOUT.render(JSON.parse(require("fs").readFileSync(0, "utf8"))));
""" % {"lang": json.dumps(lang), "dict": json.dumps(str(DOCS / "assets/i18n/dict.js")),
       "i18n": json.dumps(str(DOCS / "assets/i18n/i18n.js")), "about": json.dumps(str(DOCS / "assets/about/about.js"))}
    out = subprocess.run(["node", "-e", js], input=json.dumps(a), capture_output=True, text=True, check=True).stdout
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", out)))


def _eval_rules(rules, x, p):
    """about.json の条件の並びを日ごとに評価する（上から最初に当てはまったもの・only_if_no_signal は最後）。"""
    cci = {p["cci_long"]: x["cciL"], p["cci_short"]: x["cciS"]}
    band = {p["bb_long"]: (x["mL"], x["sL"]), p["bb_short"]: (x["mS"], x["sS"])}
    ops = {">": np.greater, "<": np.less, ">=": np.greater_equal, "<=": np.less_equal}

    def ok(c, i):
        if c["ind"] == "cci":
            return bool(ops[c["op"]](cci[c["n"]][i], c["v"]))
        m, s = band[c["n"]]
        return bool(ops[c["op"]](x["c"][i], m[i] + c["k"] * s[i]))

    order = [r for r in rules if not r.get("only_if_no_signal")] + [r for r in rules if r.get("only_if_no_signal")]
    with np.errstate(invalid="ignore"):
        return [next((r["code"] for r in order if all(ok(c, i) for c in r["all"])), ind.LABELS[0])
                for i in range(len(x["c"]))]


# ── 1 ────────────────────────────────────────────────────────────────────
def test_about_periods_and_thresholds_come_from_ind_P(monkeypatch):
    a = _build()
    p = ind.P
    assert a["params"]["P"] == p
    assert a["params"]["cci_alert_level"] == ind.CCI_ALERT_LEVEL
    for lang in ("ja", "en"):
        t = _render(a, lang)
        for s in (f"CCI{p['cci_long']} > 0", f"CCI{p['cci_short']} < -{p['cci_th']}", f"CCI{p['cci_short']} > +{p['cci_th']}",
                  f"BB{p['bb_short']}", f"BB{p['bb_long']}", f"−{p['k2']:g}σ", f"−{p['k3']:g}σ", f"±{ind.CCI_ALERT_LEVEL}"):
            assert s in t, f"{lang}: {s!r} not shown"

    # 規則の並び（about.json）を評価すると ind.day_labels と同じ判定になる（規則のずれを止める）
    rng = np.random.default_rng(7)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 1500)))
    h, l = c * (1 + rng.uniform(0, 0.01, c.size)), c * (1 - rng.uniform(0, 0.01, c.size))
    x = ind.compute(h, l, c)
    want = list(ind.day_labels(x))
    assert len(set(want)) >= 4, "synthetic series should produce several labels"
    assert _eval_rules(a["rules"]["chart"], x, p) == want

    # P を変えると表示も変わる（数字を手で書いていない）
    odd = {"cci_long": 277, "cci_short": 41, "bb_long": 263, "bb_short": 37, "k2": 2.5, "k3": 3.5, "cci_th": 111}
    for k, v in odd.items():
        monkeypatch.setitem(ind.P, k, v)
    t = _render(_build(), "ja")
    for s in ("CCI277 > 0", "CCI41 < -111", "BB37 の −2.5σ", "BB37 の −3.5σ", "BB263 の −2.5σ", "±111"):
        assert s in t, f"changed P not reflected: {s!r}"
    assert "288" not in t and "CCI48" not in t, "old period still shown (hand-written number?)"


# ── 2 ────────────────────────────────────────────────────────────────────
REQUIRED = {
    "": ("schema", "generated_at", "commit", "params", "rules", "schedule", "verify", "meta", "tabs",
         "limitations", "disclaimer", "mac_mini"),
    "commit": ("sha",),
    "params": ("P", "cci_alert_level", "min_bars"),
    "rules": ("chart", "composite", "cci_events", "buy_type", "sell_type"),
    "schedule": ("crons", "next"),
    "verify": ("available", "weakened", "weakened_items", "markets"),
    "meta": ("available", "updated_at", "counts", "universe", "fallbacks"),
    "mac_mini": ("theory_price", "overall", "cci_notify"),
}


def _check_required(a):
    for path, keys in REQUIRED.items():
        node = a[path] if path else a
        missing = [k for k in keys if k not in node]
        assert not missing, f"about.json {path or '(top)'} missing {missing}"
    assert set(a["params"]["P"]) == set(ind.P)
    assert {"full", "corr_refresh"} <= set(a["schedule"]["crons"]) and a["schedule"]["next"]["full"]
    assert [r["code"] for r in a["rules"]["chart"]] and a["limitations"] and a["tabs"][-1] == "about"


def test_about_json_has_required_keys():
    a = _build()
    _check_required(a)
    assert a["verify"]["available"] and a["meta"]["available"]
    json.dumps(a, allow_nan=False)  # ブラウザの JSON.parse で読める
    f = DOCS / "about.json"  # deploy.yml では tools/build_about.py の後に回るので本物も確かめる
    if f.exists():
        _check_required(json.loads(f.read_text(encoding="utf-8")))


# ── 3 ────────────────────────────────────────────────────────────────────
def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def test_about_has_no_jquants_keys_or_mac_output(tmp_path, monkeypatch):
    # Mac mini の出力（架空・目印の値）を置き、設定もそこを指す。それでも about に出ないこと。
    data = tmp_path / "screener-data"
    (data / "out").mkdir(parents=True)
    marks = ("98765.4", "ZZ架空精機", "123.45", "ZQXJ")
    (data / "out" / "japan_list.csv").write_text(
        "grade,code,company_name,fair_price,upside_pct\nA,ZQXJ,ZZ架空精機,98765.4,123.45\n", encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[paths]\ndata_dir = "{data}"\n', encoding="utf-8")
    monkeypatch.setenv("SCREENER_CONFIG", str(cfg))

    targets = [_build()]
    f = DOCS / "about.json"
    if f.exists():
        targets.append(json.loads(f.read_text(encoding="utf-8")))
    for a in targets:
        bad = sorted(set(_keys(a)) & JQ_KEYS)
        assert not bad, f"J-Quants keys in about.json: {bad}"
        s = json.dumps(a, ensure_ascii=False)
        for lang in ("ja", "en"):
            t = _render(a, lang)
            for m in marks:
                assert m not in s and m not in t, f"Mac mini output value {m!r} leaked"
            for k in JQ_KEYS - {"F", "PBR", "grade"}:   # 短い語は文の中に普通に出る（キーは上で調べた）
                assert k not in t, f"{lang}: J-Quants key {k!r} shown"
    src = (DOCS / "assets" / "about" / "about.js").read_text(encoding="utf-8")
    assert not [k for k in JQ_KEYS if re.search(rf"\b{re.escape(k)}\b", src) and len(k) > 2]

