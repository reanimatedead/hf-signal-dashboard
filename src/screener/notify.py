"""ntfy 通知。本文は「OK / 失敗 / 週次 OK」と日付だけ（例: "screener 2026-11-02 OK"）。株のデータは送らない。

トピックは install_macmini.sh が作るランダムな文字列（~/.config/screener/config.toml の [ntfy] topic）。
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import urllib.request
from collections.abc import Callable
from typing import Any

from .config import Config

STATUSES = ("OK", "失敗", "週次 OK")
BODY_RE = re.compile(r"^screener \d{4}-\d{2}-\d{2} (OK|失敗|週次 OK)$")
Poster = Callable[[str, bytes], Any]


def body(status: str, day: dt.date) -> str:
    if status not in STATUSES:
        raise ValueError(f"status は {STATUSES} のどれか")
    text = f"screener {day.isoformat()} {status}"
    assert BODY_RE.match(text)
    return text


def _post(url: str, data: bytes) -> Any:
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "text/plain; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def send(cfg: Config, status: str, day: dt.date, poster: Poster = _post) -> bool:
    """送れたら True。トピックが無い・送れないときは False（例外にしない。本処理の結果を変えない）。"""
    topic = cfg.ntfy_topic
    if not topic:
        print("ntfy: トピックが設定されていません（install_macmini.sh）", file=sys.stderr)
        return False
    try:
        poster(f"{cfg.ntfy_server}/{topic}", body(status, day).encode("utf-8"))
        return True
    except Exception as e:  # 通知の失敗で本処理を変えない
        print(f"ntfy: 送れませんでした（{type(e).__name__}）", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    """python -m screener.notify test → 「OK＋今日の日付」を1回送る（install_macmini.sh の試し送信）。"""
    from . import config as config_mod

    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["test"]:
        print("usage: python -m screener.notify test", file=sys.stderr)
        return 2
    return 0 if send(config_mod.load(), "OK", config_mod.today_jst()) else 1


if __name__ == "__main__":
    sys.exit(main())
