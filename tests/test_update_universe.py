"""tools/update_universe.py をオフラインで: 取得→±5%検査→更新/前週維持→changes.json。通信は差し替え。"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import update_universe as uu  # noqa: E402


def _html_table(rows, cols=("Symbol", "Security")):
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rows)
    return f"<html><body><table><tr>{head}</tr>{body}</table></body></html>"


def _fake_fetch(n_ndx=101, n_sp=503, n_dow=30, fail=()):
    def fetch(url):
        for k in fail:
            if uu.URLS[k] == url:
                raise OSError("offline")
        if url == uu.URLS["nasdaq100"]:
            return _html_table([(f"Ndx {i}", f"N{i:03d}") for i in range(n_ndx)], ("Company", "Ticker"))
        if url == uu.URLS["sp500"]:
            return _html_table([(f"S{i:03d}" if i else "BRK.B", f"Sp {i}") for i in range(n_sp)])
        if url == uu.URLS["dow30"]:
            return _html_table([(f"Dow {i}", "NYSE", f"D{i:02d}") for i in range(n_dow)], ("Company", "Exchange", "Symbol"))
        raise AssertionError(url)
    return fetch


BUILTIN = {"nikkei225": {f"{1000 + i}.T": "x" for i in range(225)}, "nasdaq100": {"OLD": "old"}, "dow30": {}, "sp500": {}}


def test_update_writes_files_and_changes(tmp_path):
    r = uu.update(fetch=_fake_fetch(), udir=tmp_path, builtin=BUILTIN, today="2026-11-02")
    assert r["bad"] == []
    ndx = json.loads((tmp_path / "nasdaq100.json").read_text())
    assert ndx["count"] == 101 and "N000" in ndx["members"]
    sp = json.loads((tmp_path / "sp500.json").read_text())
    assert "BRK-B" in sp["members"]                          # "." → Yahoo 形 "-"
    assert not (tmp_path / "nikkei225.json").exists()        # §19: 既定では取得しない
    assert r["results"]["nikkei225"]["status"] == "kept"
    ch = json.loads((tmp_path / "changes.json").read_text())
    e = next(x for x in ch["entries"] if x["name"] == "nasdaq100")
    assert e["removed"] == ["OLD"] and len(e["added"]) == 101


def test_out_of_range_keeps_previous_week(tmp_path):
    uu.update(fetch=_fake_fetch(), udir=tmp_path, builtin=BUILTIN, today="2026-11-02")
    before = (tmp_path / "nasdaq100.json").read_text()
    r = uu.update(fetch=_fake_fetch(n_ndx=60, fail=("dow30",)), udir=tmp_path, builtin=BUILTIN, today="2026-11-09")
    assert set(r["bad"]) == {"nasdaq100", "dow30"}
    assert (tmp_path / "nasdaq100.json").read_text() == before       # 前週のまま
    assert r["results"]["nasdaq100"]["fetched"] == 60
    ch = json.loads((tmp_path / "changes.json").read_text())
    assert ch["last_run"]["bad"] == r["bad"]
    assert not [x for x in ch["entries"] if x["date"] == "2026-11-09"]  # 変化なし → 追記しない


def test_nikkei_builtin_out_of_range_is_bad(tmp_path):
    b = dict(BUILTIN, nikkei225={"1000.T": "x"})
    r = uu.update(fetch=_fake_fetch(), udir=tmp_path, builtin=b, today="2026-11-02", names=("nikkei225",))
    assert r["bad"] == ["nikkei225"]


def test_github_output_and_issue_body(tmp_path, monkeypatch):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(uu, "UDIR", tmp_path / "u")
    monkeypatch.setattr(uu, "http_get", _fake_fetch(n_ndx=10))
    monkeypatch.setattr(uu, "builtin_lists", lambda: BUILTIN)
    body = tmp_path / "body.md"
    assert uu.main(["--issue-body", str(body)]) == 0
    assert "bad=nasdaq100" in out.read_text()
    assert "nasdaq100" in body.read_text()


def test_parse_table_handles_exchange_prefix_footnotes_and_multiindex():
    """2026-11: Wikipedia の Nasdaq-100 / Dow 30 が 0 件になった件の再発防止（形だけの架空 HTML）。"""
    dow = """<table><tr><th>Company</th><th>Exchange</th><th>Symbol[1]</th></tr>
      <tr><td>3M</td><td>NYSE</td><td>NYSE: MMM</td></tr>
      <tr><td>Apple</td><td>NASDAQ</td><td>NASDAQ: AAPL</td></tr></table>"""
    assert uu.parse_table(dow, sym_cols=("Symbol",), name_cols=("Company",)) == {"MMM": "3M", "AAPL": "Apple"}
    ndx = """<table><thead><tr><th colspan="2">Constituents</th></tr><tr><th>Ticker</th><th>Company</th></tr></thead>
      <tr><td>AAPL</td><td>Apple Inc.</td></tr><tr><td>BRK.B</td><td>Berkshire</td></tr></table>"""
    assert uu.parse_table(ndx) == {"AAPL": "Apple Inc.", "BRK-B": "Berkshire"}


def test_candidates_fall_through_to_first_source_within_tolerance():
    """本ページに表が無い（2026-11 の Wikipedia の実物）→ 次の候補へ。件数 ±5% に入った最初の出典を使う。"""
    nav_only = "<table><tr><th>vteList of NASDAQ-100 companies</th></tr><tr><td>Adobe ADP AMD</td></tr></table>"
    rows = "".join(f"<tr><td>T{i:03d}</td><td>Co {i}</td></tr>".replace("T", "Q") for i in range(101))
    good = "<table><tr><th>Ticker</th><th>Company</th></tr>" + rows + "</table>"
    pages = {uu.CANDIDATES["nasdaq100"][0][1]: nav_only, uu.CANDIDATES["nasdaq100"][1][1]: "{}",
             uu.CANDIDATES["nasdaq100"][2][1]: good}

    def fetch(url):
        return pages[url]
    d, src = uu.fetch_one("nasdaq100", fetch)
    assert len(d) == 101 and src == "wikipedia_index"


def test_nasdaq_api_parser_and_no_source_reason():
    api = json.dumps({"data": {"data": {"rows": [{"symbol": "AAPL", "companyName": "Apple Inc."},
                                                 {"symbol": "BRK.B", "companyName": "Berkshire"}]}}})
    assert uu.parse_nasdaq_api(api) == {"AAPL": "Apple Inc.", "BRK-B": "Berkshire"}

    def boom(url):
        raise OSError("blocked")
    d, src = uu.fetch_one("dow30", boom)
    assert d == {} and src.startswith("none") and "取得失敗" in src
