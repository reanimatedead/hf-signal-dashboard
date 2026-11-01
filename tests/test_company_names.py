"""会社名の表示（docs/assets/signal/names.js）— 取得元が違っても同じ形に揃える（表示の時だけ）。

- 末尾の株式の種類の説明（Common Stock / Class A Common Stock / Capital Stock / Ordinary Shares /
  American Depositary Shares / Common Shares / (Class A) / CL A など）を外す。"Inc." などは残す。
- 社数: 名前を揃えた上で同じ会社を 1 社と数える（Nasdaq 100 の GOOG/GOOGL → 101 銘柄・100 社）。
- 会社名を出す所（表・米国の買い判定一覧・銘柄詳細の見出し・SURVIVAL）は、この関数を通す（r.name をそのまま出さない）。
"""
import json
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = ROOT / "docs" / "assets" / "signal" / "names.js"


def _node(expr):
    js = "global.window={};require(%s);process.stdout.write(JSON.stringify(%s))" % (json.dumps(str(NAMES)), expr)
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


CASES = {
    "Alphabet Inc. Class A Common Stock": "Alphabet Inc.",
    "Alphabet Inc. Class C Capital Stock": "Alphabet Inc.",
    "Alphabet Inc. (Class C)": "Alphabet Inc.",
    "ALPHABET INC CL A": "ALPHABET INC",
    "Apple Inc. Common Stock": "Apple Inc.",
    "Airbnb, Inc. Class A Common Stock": "Airbnb, Inc.",
    "Arm Holdings plc American Depositary Shares": "Arm Holdings plc",
    "Linde plc Ordinary Shares": "Linde plc",
    "Nebius Group N.V. Class A Ordinary Shares": "Nebius Group N.V.",
    "Thomson Reuters Corporation Common Shares": "Thomson Reuters Corporation",
    "Strategy Inc Common Stock Class A": "Strategy Inc",
    "Copart, Inc. (DE) Common Stock": "Copart, Inc.",
    "Seagate Technology Holdings PLC Ordinary Shares (Ireland)": "Seagate Technology Holdings PLC",
    "Fox Corporation (Class B)": "Fox Corporation",
    "VISA INC CLASS A SHARES": "VISA INC",
    # 種類の説明ではないものは変えない
    "Walt Disney Company (The)": "Walt Disney Company (The)",
    "Capital One": "Capital One",
    "トヨタ自動車": "トヨタ自動車",
    "": "",
}


def test_company_name_strips_share_class_descriptors():
    got = _node("Object.fromEntries(%s.map((n)=>[n, window.NAMES.companyName(n)]))" % json.dumps(list(CASES)))
    assert got == CASES


def test_company_count_collapses_dual_share_classes():
    rows = [{"symbol": "GOOGL", "name": "Alphabet Inc. Class A Common Stock"},
            {"symbol": "GOOG", "name": "Alphabet Inc. Class C Capital Stock"},
            {"symbol": "FOXA", "name": "Fox Corporation (Class A)"},
            {"symbol": "FOX", "name": "Fox Corporation (Class B)"},
            {"symbol": "AAPL", "name": "Apple Inc. Common Stock"},
            {"symbol": "X"}, {"symbol": "Y"}]
    got = _node("window.NAMES.companyCount(%s)" % json.dumps(rows))
    assert got == {"symbols": 7, "companies": 5, "shared": [["GOOG", "GOOGL"], ["FOX", "FOXA"]]}


def test_universe_nasdaq100_is_101_symbols_100_companies():
    members = json.loads((ROOT / "data" / "universe" / "nasdaq100.json").read_text(encoding="utf-8"))["members"]
    if len(members) != 101 or not {"GOOG", "GOOGL"} <= set(members):
        pytest.skip("構成が変わった週は数の確認だけ飛ばす（関数の確認は上のテスト）")
    rows = [{"symbol": s, "name": n} for s, n in members.items()]
    got = _node("window.NAMES.companyCount(%s)" % json.dumps(rows))
    assert (got["symbols"], got["companies"], got["shared"]) == (101, 100, [["GOOG", "GOOGL"]])


def test_every_rendered_company_name_goes_through_company_name():
    files = [ROOT / "docs" / "index.html", *sorted((ROOT / "docs" / "assets").rglob("*.js"))]
    raw = re.compile(r"esc\w*\(\s*(?:r|c|p|row)\.name\b")
    bad = [f"{f.relative_to(ROOT)}: {m.group(0)}" for f in files for m in raw.finditer(f.read_text(encoding="utf-8"))]
    assert not bad, bad
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert html.index('src="assets/signal/names.js"') < html.index('src="assets/signal/signal_ui.js"')
