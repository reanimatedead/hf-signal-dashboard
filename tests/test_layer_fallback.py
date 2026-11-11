"""tools/layer_fallback.py — 層（relations の地域・macro_v2・gamma）ごとの切り分け。

2026-11-10/11（#296・#298）: ECB の 10 年金利 API が 504 を返して relations.eu.series が 0 件になり、
データ試験で full ジョブ全体が止まった（米国・日本・他の全タブも 11/9 のまま）。
ここでは「1 つの層が欠けても他の層は更新・公開し、欠けた層は前回の正常なデータを使って
その層の更新時刻と『古いデータ』の印を付ける。全部が 0 件など欠けたまま公開しかねない時だけ止める」を確かめる。
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import layer_fallback as lf  # noqa: E402

NOW = datetime(2026, 11, 11, 22, 40, tzinfo=timezone.utc)
PREV_AT = (NOW - timedelta(days=2)).isoformat()


def _series(n, tag):
    return [{"date": f"d{i:03d}", "equity": float(i), "nominal": 1.0, "src": tag} for i in range(n)]


def _relations(as_of, n_us=260, n_eu=260, n_jp=260, tag="new"):
    def reg(n):
        return {"data_status": "live" if n else "error", "series": _series(n, tag), "source": "x"}
    return {
        "as_of": as_of,
        "align": "inner_join",
        "balance": {"regime": {"r_120d": -0.2, "tag": tag}, "beta": {}, "rebalance": {}},
        "regions": {"us": reg(n_us), "eu": reg(n_eu), "jp": reg(n_jp)},
    }


def _macro(as_of, live=True, tag="new"):
    return {"as_of": as_of, "series": ({"DGS10": {"data_status": "live", "tag": tag}} if live else {})}


def _gamma(as_of, status="live", tag="new"):
    return {"as_of": as_of, "data_status": status, "tag": tag}


def _fresh(**kw):
    return {
        "relations": kw.get("relations", _relations(NOW.isoformat())),
        "macro_v2": kw.get("macro_v2", _macro(NOW.isoformat())),
        "gamma": kw.get("gamma", _gamma(NOW.isoformat())),
    }


def _prev():
    return {
        "relations": _relations(PREV_AT, tag="old"),
        "macro_v2": _macro(PREV_AT, tag="old"),
        "gamma": _gamma(PREV_AT, tag="old"),
    }


# ── 欧州だけ 0 件 ─────────────────────────────────────────────────────────
def test_eu_only_empty_others_updated_eu_uses_previous_and_is_marked_stale():
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_eu=0)), _prev(), NOW)
    assert rep.errors == []
    assert rep.stale == ["relations.eu"]
    regs = out["relations"]["regions"]
    # 他の層は今回の値（更新されている）
    for k in ("us", "jp"):
        assert regs[k]["series"][0]["src"] == "new"
        assert regs[k]["stale"] is False
        assert regs[k]["as_of"] == NOW.isoformat()
    assert out["relations"]["balance"]["regime"]["tag"] == "new"
    assert out["macro_v2"]["series"]["DGS10"]["tag"] == "new"
    assert out["gamma"]["tag"] == "new"
    # 欧州は前回の正常なデータ＋古い印＋その層の更新時刻（前回の時刻）
    eu = regs["eu"]
    assert eu["series"][0]["src"] == "old" and len(eu["series"]) == 260
    assert eu["data_status"] == "live"
    assert eu["stale"] is True
    assert eu["as_of"] == PREV_AT
    assert eu["stale_reason"] == "fetch_failed_previous_kept"


def test_all_regions_empty_stops_even_if_previous_exists():
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), 0, 0, 0)), _prev(), NOW)
    assert rep.errors, "全部が 0 件なら止める（前回データで全部を置き換えて公開しない）"
    assert any("relations" in e for e in rep.errors)


def test_missing_layer_without_previous_stops():
    prev = _prev()
    prev["relations"] = None   # 公開サイトから前回分が取れない
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_eu=0)), prev, NOW)
    assert rep.errors and any("relations.eu" in e for e in rep.errors)


def test_previous_region_that_was_itself_broken_is_not_used():
    prev = _prev()
    prev["relations"]["regions"]["eu"]["series"] = []
    prev["relations"]["regions"]["eu"]["data_status"] = "error"
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_eu=0)), prev, NOW)
    assert rep.errors and any("relations.eu" in e for e in rep.errors)


def test_carried_stale_region_keeps_its_original_timestamp():
    """2 日続けて欧州が欠けたとき、表示する更新時刻は最後に本当に取れた時刻のまま（前回の公開時刻にしない）。"""
    older = (NOW - timedelta(days=5)).isoformat()
    prev = _prev()
    prev["relations"]["regions"]["eu"].update({"stale": True, "as_of": older})
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_eu=0)), prev, NOW)
    assert rep.stale == ["relations.eu"]
    assert out["relations"]["regions"]["eu"]["as_of"] == older


def test_us_missing_also_carries_previous_balance():
    """regime / beta / rebalance は米国の系列から作るので、米国が欠けたら前回の balance も一緒に使う。"""
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_us=0)), _prev(), NOW)
    assert rep.stale == ["relations.us"]
    bal = out["relations"]["balance"]
    assert bal["regime"]["tag"] == "old"
    assert bal["stale"] is True and bal["as_of"] == PREV_AT


def test_whole_file_layers_fall_back_independently():
    fresh = _fresh(macro_v2=_macro(NOW.isoformat(), live=False), gamma=_gamma(NOW.isoformat(), "error"))
    out, rep = lf.apply(fresh, _prev(), NOW)
    assert rep.errors == []
    assert sorted(rep.stale) == ["gamma", "macro_v2"]
    assert out["macro_v2"]["series"]["DGS10"]["tag"] == "old"
    assert out["macro_v2"]["stale"] is True and out["macro_v2"]["as_of"] == PREV_AT
    assert out["gamma"]["tag"] == "old" and out["gamma"]["stale"] is True
    # relations は今回のまま
    assert out["relations"]["regions"]["eu"]["series"][0]["src"] == "new"


def test_all_fresh_marks_every_unit_not_stale():
    out, rep = lf.apply(_fresh(), _prev(), NOW)
    assert rep.errors == [] and rep.stale == []
    for k in ("us", "eu", "jp"):
        assert out["relations"]["regions"][k]["stale"] is False
    assert out["macro_v2"]["stale"] is False and out["gamma"]["stale"] is False


# ── CLI（deploy.yml から呼ぶ形）─────────────────────────────────────────────
def _write(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in files.items():
        (d / f"{name}.json").write_text(json.dumps(obj), encoding="utf-8")


def test_cli_eu_only_publishes_and_reports_stale_for_notification(tmp_path, monkeypatch):
    docs, prev = tmp_path / "docs", tmp_path / "prev"
    _write(docs, _fresh(relations=_relations(NOW.isoformat(), n_eu=0)))
    _write(prev, _prev())
    gh_out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    rc = lf.main(["--docs", str(docs), "--prev-dir", str(prev)])
    assert rc == 0
    rel = json.loads((docs / "relations.json").read_text(encoding="utf-8"))
    assert rel["regions"]["eu"]["stale"] is True
    assert len(rel["regions"]["eu"]["series"]) >= 200   # データ試験（200 件以上）も通る
    assert "stale=relations.eu" in gh_out.read_text(encoding="utf-8")


def test_cli_all_empty_exits_nonzero_and_leaves_no_partial_publish(tmp_path, monkeypatch):
    docs, prev = tmp_path / "docs", tmp_path / "prev"
    _write(docs, _fresh(relations=_relations(NOW.isoformat(), 0, 0, 0)))
    _write(prev, _prev())
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_out"))
    assert lf.main(["--docs", str(docs), "--prev-dir", str(prev)]) == 1


# ── 画面とワークフローの配線 ───────────────────────────────────────────────
def test_screen_shows_layer_time_and_stale_badge_in_ja_and_en():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    d = (ROOT / "docs" / "assets" / "i18n" / "dict.js").read_text(encoding="utf-8")
    assert "rel.stale_badge" in html and "rel.layer_as_of" in html
    for key in ("rel.stale_badge", "rel.layer_as_of"):
        assert len(re.findall(rf'"{re.escape(key)}"\s*:', d)) == 2, f"{key} は ja / en の両方に要る"
    assert "古いデータ" in d and "Stale data" in d


def test_deploy_runs_fallback_before_data_tests_and_notifies_once_on_stale():
    y = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    full = y.split("corr_refresh:\n    if:")[0]
    i_fb = full.find("tools/layer_fallback.py")
    i_dt = full.find("Data tests")
    assert 0 < i_fb < i_dt, "前回データでの差し替えはデータ試験より前"
    assert "steps.layers.outputs.stale" in full, "差し替えて公開したときの ntfy 通知がない"
    i_deploy = full.find("uses: actions/deploy-pages")
    i_note = full.find("steps.layers.outputs.stale")
    assert i_note > i_deploy, "通知は公開が成功した後に 1 回"


# ── 取得元（ECB 10 年金利）の取り直し ──────────────────────────────────────────
class _Resp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Server Error")


_CSV = "TIME_PERIOD,OBS_VALUE\n2026-11-06,3.28\n2026-11-09,3.27\n"


def _patch_ecb(monkeypatch, codes):
    sys.path.insert(0, str(ROOT / "pipeline"))
    import corr_sources as cs
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        c = codes[min(len(calls) - 1, len(codes) - 1)]
        return _Resp(c, _CSV if c == 200 else "")

    monkeypatch.setattr(cs.requests, "get", fake_get)
    monkeypatch.setattr(cs, "ECB_RETRY_WAITS", (0, 0))
    return cs, calls


def test_ecb_eu10y_retries_after_504_and_returns_data(monkeypatch):
    cs, calls = _patch_ecb(monkeypatch, [504, 504, 200])
    out = cs.fetch_ecb_eu10y()
    assert out == {"2026-11-06": 3.28, "2026-11-09": 3.27}
    assert len(calls) == 3


def test_ecb_eu10y_gives_up_with_none_when_504_persists(monkeypatch):
    cs, calls = _patch_ecb(monkeypatch, [504])
    assert cs.fetch_ecb_eu10y() is None
    assert len(calls) == 3


def test_gamma_error_without_previous_publishes_as_before_with_warning():
    """gamma / macro_v2 は従来、欠けても止めていなかった（画面は「取得に失敗」）。前回分も無ければそのまま公開。"""
    prev = _prev()
    prev["gamma"] = None
    out, rep = lf.apply(_fresh(gamma=_gamma(NOW.isoformat(), "error")), prev, NOW)
    assert rep.errors == [] and rep.stale == []
    assert out["gamma"]["data_status"] == "error" and out["gamma"]["stale"] is False
    assert any("gamma" in w for w in rep.warnings)


def test_us_stale_balance_has_reason_code():
    out, rep = lf.apply(_fresh(relations=_relations(NOW.isoformat(), n_us=0)), _prev(), NOW)
    assert out["relations"]["balance"]["stale_reason"] == "fetch_failed_previous_kept"


# ── 古いデータの層は売買の点数・判定に入らない（2026-11-11 確認・再発防止）────────────
def test_layers_that_can_be_stale_are_not_read_by_score_or_judgment_code():
    """relations / macro_v2 / gamma（前回データに差し替わりうる層）は画面の表示専用。
    売買スコア（src/screener）・チャート判定と data.json の生成（fetch_signals.py）・リスクゲート（survival/）が
    これらのファイルを読み始めたら、古い層を計算から外す仕組みが要るので、ここで止める。"""
    pat = re.compile(r"(relations|macro_v2|gamma)\.json")
    roots = [ROOT / "src" / "screener", ROOT / "survival", ROOT / "fetch_signals.py"]
    hits = []
    for r in roots:
        for p in ([r] if r.is_file() else r.rglob("*.py")):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not hits, "古くなりうる層を計算側が読んでいる:\n" + "\n".join(hits)
