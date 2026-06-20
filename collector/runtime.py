"""collector.runtime — 取得堅牢化の共通ヘルパ (SPEC_AUTOCOLLECT §4).

- USER_AGENT: 規約順守の自己申告 UA
- MIN_REQUEST_INTERVAL_SEC: 同一ホストへのレート制御の床
- retry(): 指数バックオフ + 429/5xx を含む例外で再試行
- HostRateLimiter: 連続呼出間の最小間隔を強制

keyless。robots / 規約順守。
"""

from __future__ import annotations

import time
import random
import threading
from typing import Callable, Iterable, TypeVar

USER_AGENT = (
    "hf-signal-dashboard collector/1.5 "
    "(+https://github.com/reanimatedead/hf-signal-dashboard)"
)
MIN_REQUEST_INTERVAL_SEC = 0.4

T = TypeVar("T")


def retry(fn: Callable[[], T], attempts: int = 3,
          base_backoff: float = 1.0, jitter: float = 0.25) -> T:
    """Run `fn` up to `attempts` times. On exception, sleep base_backoff * 2**(i)
    seconds (with jitter), then retry. Re-raises the last exception.
    """
    last_exc = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if i + 1 >= attempts:
                break
            delay = base_backoff * (2 ** i) + random.uniform(0, jitter)
            if delay > 0:
                time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry exhausted without exception (unreachable)")


class HostRateLimiter:
    """Per-host minimum interval gatekeeper. Thread-safe."""

    def __init__(self, min_interval_sec: float = MIN_REQUEST_INTERVAL_SEC):
        self.min_interval = max(0.0, float(min_interval_sec))
        self._last = {}    # host -> monotonic timestamp
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            prev = self._last.get(host, 0.0)
            delta = now - prev
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last[host] = time.monotonic()


# Global limiter shared across the collector run (singleton).
_LIMITER = HostRateLimiter()


def rate_limit(host: str) -> None:
    _LIMITER.wait(host)


def default_headers() -> dict:
    return {"User-Agent": USER_AGENT,
            "Accept": "application/json, text/csv, text/plain;q=0.5, */*;q=0.1"}
