"""screener.jquants: 回数制限（直近60秒で50回まで・スレッド安全）・キーの取り方・キーを出さない・V2 固定。"""

import io
import json
import threading
import urllib.error

import pytest

from screener import jquants as J


class FakeClock:
    """sleep で時間が進む時計（スレッドから呼ばれても一貫）。"""

    def __init__(self):
        self.t = 0.0
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return self.t

    def sleep(self, s):
        with self.lock:
            self.t += s


def max_in_window(ts, w=60.0):
    ts = sorted(ts)
    best = j = 0
    for i in range(len(ts)):
        while ts[i] - ts[j] >= w:
            j += 1
        best = max(best, i - j + 1)
    return best


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_120_calls_never_exceed_50_per_60s():
    c = FakeClock()
    rl = J.RateLimiter(50, 60.0, clock=c.now, sleep=c.sleep)
    ts = [rl.acquire() for _ in range(120)]
    assert len(ts) == 120
    assert max_in_window(ts) == 50  # 上限ちょうどまでは使う
    assert ts[-1] >= 120.0  # 120回には2分以上かかる


def test_rate_limit_thread_safe():
    c = FakeClock()
    rl = J.RateLimiter(50, 60.0, clock=c.now, sleep=c.sleep)
    ts, lock = [], threading.Lock()

    def worker():
        for _ in range(40):
            t = rl.acquire()
            with lock:
                ts.append(t)

    th = [threading.Thread(target=worker) for _ in range(3)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    assert len(ts) == 120
    assert max_in_window(ts) <= 50


def test_client_uses_limiter_and_v2_and_paginates():
    assert J.API_VERSION == "v2" and J.API_BASE == "https://api.jquants.com/v2"
    c = FakeClock()
    rl = J.RateLimiter(50, 60.0, clock=c.now, sleep=c.sleep)
    seen = []

    def opener(req, timeout):
        seen.append((req.full_url, req.headers.get("X-api-key")))
        page = 2 if "pagination_key" in req.full_url else 1
        d = {"data": [{"n": page}]}
        if page == 1:
            d["pagination_key"] = "p2"
        return Resp(json.dumps(d).encode())

    cl = J.Client(key="SECRET-KEY-123", limiter=rl, opener=opener, sleep=c.sleep)
    out = cl.get("equities/bars/daily", date="2026-01-05")
    assert out == [{"n": 1}, {"n": 2}]
    assert all(u.startswith("https://api.jquants.com/v2/equities/bars/daily?") for u, _ in seen)
    assert cl.calls == 2 and len(rl.calls) == 2
    assert "SECRET" not in repr(cl)


def test_http_error_result_has_no_key():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message":"bad"}'))

    rl = J.RateLimiter(50, 60, clock=lambda: 0, sleep=lambda s: None)
    cl = J.Client(key="SECRET-KEY-123", limiter=rl, opener=opener, sleep=lambda s: None)
    r = cl.get("fins/summary", date="2026-01-05")
    assert r["err"] == 403 and "SECRET" not in json.dumps(r)


def test_get_key_env_then_keychain():
    assert J.get_key("svc", env={"JQ": " abc \n"}) == "abc"
    calls = []

    class P:
        returncode = 0
        stdout = "fromkeychain\n"

    def runner(args, **kw):
        calls.append(args)
        return P()

    assert J.get_key("svc", env={}, runner=runner) == "fromkeychain"
    assert calls == [["security", "find-generic-password", "-s", "svc", "-w"]]
    assert J.DEFAULT_SERVICE == "screener-jquants"

    class N:
        returncode = 44
        stdout = ""

    with pytest.raises(J.KeyNotFound) as e:
        J.get_key("svc", env={}, runner=lambda a, **k: N())
    assert "svc" in str(e.value)


def test_missing_security_command_message_has_no_key():
    def runner(args, **kw):
        raise FileNotFoundError("security")

    with pytest.raises(J.KeyNotFound):
        J.get_key("svc", env={}, runner=runner)
