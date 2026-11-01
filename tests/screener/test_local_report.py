"""screener.local_report: 日本株の一覧は <data_dir>/out/ にだけ書く・counts.json（前回の件数とずれ%）。"""

import json

import pytest

from screener import local_report
from screener.japan import signals


def test_writes_only_under_out(cfg):
    doc = signals.run(cfg)
    before = {p for p in cfg.data_dir.rglob("*") if p.is_file()}
    c = local_report.write(cfg, doc)
    after = {p for p in cfg.data_dir.rglob("*") if p.is_file()}
    new = after - before
    assert new and all(cfg.out_dir in p.parents for p in new)
    assert {p.name for p in new} == {
        "japan_list.csv",
        "japan_list.html",
        "us_list.csv",
        "verify_local.json",
        "counts.json",
    }
    assert not any(cfg.repo_dir.rglob("*"))  # リポジトリには何も書かない
    assert c["japan_rows"] == 5 and c["us_rows"] == 3 and "previous" not in c
    html = (cfg.out_dir / "japan_list.html").read_text()
    assert "決算短信で確認" in html and "<script" not in html  # 言葉は描画時に付ける
    assert "<th>コード</th>" in html and "check_earnings_release" not in html
    csv = (cfg.out_dir / "japan_list.csv").read_text(encoding="utf-8-sig")
    assert csv.splitlines()[0].startswith("code,") and len(csv.splitlines()) == 6


def test_counts_keeps_previous_and_diff(cfg):
    doc = signals.run(cfg)
    local_report.write(cfg, doc)
    doc["jp"] = doc["jp"][:4]
    c = local_report.write(cfg, doc)
    assert c["previous"]["japan_rows"] == 5 and c["japan_rows"] == 4 and c["japan_diff_pct"] == -20.0
    assert json.loads((cfg.out_dir / "counts.json").read_text())["japan_rows"] == 4


def test_refuses_out_inside_repo(cfg):
    cfg.data_dir = cfg.repo_dir / "screener-data"
    with pytest.raises(RuntimeError):
        local_report.write(cfg, {"jp": [], "us": []})
