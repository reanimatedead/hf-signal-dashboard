"""screener.japan.fetch: 既定は今日だけ・--full は history_years 年分・一括取得も 50回/60秒 を超えない（通信なし）。"""

import datetime as dt
import io
import json

from screener import jquants as J
from screener.japan import fetch

from .test_jquants import FakeClock, max_in_window


def test_daily_delta_is_recent_3_business_days(cfg):
    today = dt.date(2026, 11, 2)  # 月曜 → 前の木・金と今日
    assert fetch.date_range(cfg, today) == ["2026-10-29", "2026-10-30", "2026-11-02"]
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
    assert r["dates"] == 3 and r["fetched"] == 3 and r["err"] == 0
    assert json.loads(cfg.jp("daily", "2026-11-02.json").read_text()) == [["9999", 2.0, 1.0, 1.5, 10]]
    assert cfg.jp("bars_2026-11-02.json").exists() and cfg.jp("master_2026-11-02.json").exists()
    # refresh に入っていない日は、既にあるファイルを取り直さない
    n = len(calls)
    fetch.fetch_daily(["2026-11-02"], cfg, get)
    assert len(calls) == n


def test_recent_days_are_refetched_and_empty_today_is_not_saved(cfg):
    """取引時間前に保存された空の日・19:00 以降に出た決算を、翌日以降の実行で取り直す（直近3営業日）。"""
    today = dt.date(2026, 11, 4)  # 水曜 → 11-02, 11-03, 11-04
    old = "2026-10-27"
    cfg.jp("daily").mkdir(parents=True, exist_ok=True)
    cfg.jp("fins").mkdir(parents=True, exist_ok=True)
    for d in ("2026-11-02", "2026-11-03", old):
        cfg.jp("daily", f"{d}.json").write_text("[]")  # 前の実行で空のまま保存された日
        cfg.jp("fins", f"{d}.json").write_text("[]")
    calls = []
    bar = {"Code": "99990", "AdjH": 2.0, "AdjL": 1.0, "AdjC": 1.5, "Va": 10, "MktCap": 1.0}

    def get(path, **q):
        d = q.get("date")
        calls.append((path, d))
        if path == "equities/bars/daily":
            return [] if d == "2026-11-04" else [bar]  # 今日はまだ空（取引時間前）
        if path == "fins/summary":
            return [] if d == "2026-11-04" else [{"Code": "99990", "DiscDate": d}]
        return [{"Code": "99990", "CoName": "架空Z", "MktNm": "プライム"}]

    r = fetch.run(cfg, today, get=get)
    assert r["err"] == 0 and r["fins_err"] == 0
    for d in ("2026-11-02", "2026-11-03"):  # 空だった日・決算が後から出た日を取り直した
        assert json.loads(cfg.jp("daily", f"{d}.json").read_text()) == [["9999", 2.0, 1.0, 1.5, 10]]
        assert json.loads(cfg.jp("fins", f"{d}.json").read_text()) == [{"Code": "99990", "DiscDate": d}]
    assert not cfg.jp("daily", "2026-11-04.json").exists()  # 今日の空は保存しない
    assert not cfg.jp("fins", "2026-11-04.json").exists()
    assert ("equities/bars/daily", old) not in calls and (
        "fins/summary",
        old,
    ) not in calls  # 3営業日より前は取り直さない
    assert json.loads(cfg.jp("daily", f"{old}.json").read_text()) == []


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
