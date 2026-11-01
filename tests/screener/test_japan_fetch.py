"""screener.japan.fetch: 既定は今日だけ・--full は history_years 年分・一括取得も 50回/60秒 を超えない（通信なし）。"""

import datetime as dt
import io
import json

from screener import jquants as J
from screener.japan import fetch

from .test_jquants import FakeClock, max_in_window


def test_daily_delta_is_today_only(cfg):
    today = dt.date(2026, 11, 2)  # 月曜
    assert fetch.date_range(cfg, today) == ["2026-11-02"]
    full = fetch.date_range(cfg, today, full=True)  # テストの config は history_years = 1
    assert full[0] == "2025-11-03" and full[-1] == "2026-11-02" and len(full) == 261


def test_run_writes_files_with_fake_getter(cfg):
    calls = []

    def get(path, **q):
        calls.append((path, q.get("date")))
        if path == "equities/bars/daily":
            return [{"Code": "99990", "AdjH": 2.0, "AdjL": 1.0, "AdjC": 1.5, "Va": 10, "MktCap": 1.0}]
        if path == "fins/summary":
            return []
        return [{"Code": "99990", "CoName": "架空Z", "MktNm": "プライム"}]

    today = dt.date(2026, 11, 2)
    r = fetch.run(cfg, today, get=get)
    assert r["dates"] == 1 and r["fetched"] == 1 and r["err"] == 0
    assert json.loads(cfg.jp("daily", "2026-11-02.json").read_text()) == [["9999", 2.0, 1.0, 1.5, 10]]
    assert cfg.jp("bars_2026-11-02.json").exists() and cfg.jp("master_2026-11-02.json").exists()
    # 2回目は何も取り直さない（既にあるファイル）
    n = len(calls)
    fetch.fetch_daily(["2026-11-02"], cfg, get)
    assert len(calls) == n


def test_full_bulk_fetch_respects_rate_limit(cfg):
    """初回の一括取得（--full, スレッド3本）でも、直近60秒の呼び出しは 50 回以下。"""
    c = FakeClock()
    rl = J.RateLimiter(50, 60.0, clock=c.now, sleep=c.sleep)
    stamps = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        stamps.append(c.now())
        return R(json.dumps({"data": []}).encode())

    client = J.Client(key="K", limiter=rl, opener=opener, sleep=c.sleep)
    for d in list(cfg.jp("daily").glob("*.json")):  # 架空データの日足を作業コピーから外して全部取らせる
        d.rename(d.with_suffix(".bak"))
    fetch.run(cfg, dt.date(2026, 11, 2), full=True, get=client.get)
    assert len(stamps) > 400
    assert max_in_window(stamps) <= 50
