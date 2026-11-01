"""J-Quants API V2 クライアント（キー取得・回数制限・ページ送り）。

- キー: 環境変数 JQ → 無ければ macOS キーチェーン（security find-generic-password -s screener-jquants -w）。
  キーは画面・ログ・ファイル・例外メッセージに出さない（repr にも出さない）。
- 回数制限: 直近60秒で最大 50 回（スライディングウィンドウ・スレッド安全）。
  初回の一括取得（--full）も同じ制限を通る。時計と sleep は差し替え可能（テスト用）。
- API は V2 固定。
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

API_VERSION = "v2"
API_BASE = "https://api.jquants.com/" + API_VERSION
DEFAULT_SERVICE = "screener-jquants"


class RateLimiter:
    """直近 period 秒の呼び出し回数を max_calls 以下に保つ（スライディングウィンドウ）。"""

    def __init__(
        self,
        max_calls: int = 50,
        period: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_calls, self.period = int(max_calls), float(period)
        self.clock, self.sleep = clock, sleep
        self.calls: collections.deque[float] = collections.deque()
        self.lock = threading.Lock()

    def acquire(self) -> float:
        while True:
            with self.lock:
                now = self.clock()
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return now
                wait = self.period - (now - self.calls[0])
            self.sleep(max(wait, 0.001))


class KeyNotFound(RuntimeError):
    pass


Runner = Callable[..., Any]


def get_key(
    service: str = DEFAULT_SERVICE,
    env: Mapping[str, str] = os.environ,
    runner: Runner = subprocess.run,
) -> str:
    """キーを返す（表示しない）。見つからなければ KeyNotFound（メッセージにキーは含めない）。"""
    k = env.get("JQ")
    if k:
        return k.strip()
    try:
        r = runner(
            ["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        raise KeyNotFound("J-Quants キーが見つかりません（環境変数 JQ もキーチェーンも無し）") from None
    if r.returncode != 0 or not str(r.stdout).strip():
        raise KeyNotFound(f"J-Quants キーがキーチェーン（service={service}）にありません。install_macmini.sh で登録")
    return str(r.stdout).strip()


Opener = Callable[[urllib.request.Request, float], Any]


def _urlopen(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout)


class Client:
    def __init__(
        self,
        key: str | None = None,
        limiter: RateLimiter | None = None,
        opener: Opener | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rate_per_min: int = 50,
        service: str = DEFAULT_SERVICE,
    ) -> None:
        self._key = key
        self._service = service
        self.limiter = limiter or RateLimiter(rate_per_min, 60.0)
        self.opener: Opener = opener or _urlopen
        self.sleep = sleep
        self.calls = 0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"<jquants.Client calls={self.calls} key={'set' if self._key else 'unset'}>"

    def _k(self) -> str:
        if self._key is None:
            self._key = get_key(self._service)
        return self._key

    def _get(self, url: str) -> dict[str, Any]:
        self.limiter.acquire()
        with self._lock:
            self.calls += 1
        req = urllib.request.Request(url, headers={"x-api-key": self._k()})
        with self.opener(req, 60) as r:
            out: dict[str, Any] = json.loads(r.read())
            return out

    def get(self, path: str, **q: str) -> list[dict[str, Any]] | dict[str, Any]:
        """ページ送りして data を全部返す。失敗時は {"err": code, "body": 先頭200字}（キーは含まない）。"""
        out: list[dict[str, Any]] = []
        pk: str | None = None
        while True:
            qq = dict(q)
            if pk:
                qq["pagination_key"] = pk
            url = f"{API_BASE}/{path}?" + urllib.parse.urlencode(qq)
            d: dict[str, Any] | None = None
            for i in range(6):
                try:
                    d = self._get(url)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        self.sleep(15 * (i + 1))
                        continue
                    body = e.read()[:200].decode("utf-8", "replace") if hasattr(e, "read") else ""
                    return out if out else {"err": e.code, "body": body}
                except KeyNotFound:
                    raise
                except Exception:
                    self.sleep(5 * (i + 1))
            if d is None:
                return out if out else {"err": "retry", "body": "6回失敗"}
            out += d.get("data", [])
            pk = d.get("pagination_key")
            if not pk:
                return out


Getter = Callable[..., Any]

_DEFAULT: Client | None = None
_DLOCK = threading.Lock()


def default_client(rate_per_min: int = 50, service: str = DEFAULT_SERVICE) -> Client:
    """プロセス内で1つの回数制限を共有する（スレッドからも）。"""
    global _DEFAULT
    with _DLOCK:
        if _DEFAULT is None:
            _DEFAULT = Client(rate_per_min=rate_per_min, service=service)
        return _DEFAULT


def jq(path: str, **q: str) -> list[dict[str, Any]] | dict[str, Any]:
    return default_client().get(path, **q)
