"""毎日 19:00（launchd）に動く本体: python -m screener.daily

1. リポジトリ（config の repo_dir、既定 ~/hf-signal-dashboard）で git pull --ff-only
2. J-Quants 契約テスト（V2・日足 ≥3500 件・決算短信の列）
3. 今日の差分を取得（日本株 J-Quants・米国株 Yahoo の株価）
4. 一覧（screen → signals）→ local_report（<data_dir>/out/ にだけ書く）
失敗したら ntfy に「失敗＋日付」を送って終了コード 1。
成功したら何も送らない。ただし月曜は最後に「週次 OK＋日付」を1回送る。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import traceback
from collections.abc import Callable
from typing import Any

from . import config as config_mod
from . import contract, local_report, notify
from .config import Config
from .jquants import Getter, default_client

Runner = Callable[..., Any]


def git_pull(cfg: Config, runner: Runner = subprocess.run) -> None:
    r = runner(["git", "-C", str(cfg.repo_dir), "pull", "--ff-only"], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"git pull --ff-only が失敗（{cfg.repo_dir}）: {str(r.stderr).strip()[:300]}")


def update_us(cfg: Config, today: dt.date) -> None:
    from .us import fetch as us_fetch

    p = cfg.us("universe.json")
    if not p.exists():
        rec = us_fetch.update_universe(cfg)
        if not rec["ok"]:
            raise RuntimeError("米国の構成銘柄の件数が想定から外れています: " + " / ".join(rec["messages"]))
    tickers = list(json.loads(p.read_text()))
    if today.weekday() == 0 or not any(cfg.us("facts").glob("*.json")):
        got, err = us_fetch.fetch_edgar(cfg, tickers)
        if err > len(tickers) * 0.1:
            raise RuntimeError(f"EDGAR の決算が {err}/{len(tickers)} 件取れない")
    got, err = us_fetch.fetch_prices(cfg, tickers)
    if err > len(tickers) * 0.1:
        raise RuntimeError(f"米国株の株価が {err}/{len(tickers)} 件取れない")


def pipeline(
    cfg: Config,
    today: dt.date,
    get: Getter | None = None,
    runner: Runner = subprocess.run,
    us_update: Callable[[Config, dt.date], None] = update_us,
) -> dict[str, Any]:
    from .japan import fetch as jp_fetch
    from .japan import signals

    cfg.ensure_dirs()
    git_pull(cfg, runner)
    if get is None:
        get = default_client(int(cfg.get("jquants.rate_per_min", 50)), str(cfg.get("jquants.keychain_service"))).get
    print(contract.check(today, get), flush=True)
    print("japan fetch", jp_fetch.run(cfg, today, get=get), flush=True)
    us_update(cfg, today)
    doc = signals.run(cfg)
    c = local_report.write(cfg, doc)
    print("counts", json.dumps(c, ensure_ascii=False), flush=True)  # 件数だけ
    return c


def main(
    argv: list[str] | None = None,
    cfg: Config | None = None,
    today: dt.date | None = None,
    run: Callable[[Config, dt.date], Any] | None = None,
    poster: notify.Poster | None = None,
) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--today", help="基準日（既定: 今日 JST）")
    a = ap.parse_args(argv)
    today = today or (dt.date.fromisoformat(a.today) if a.today else config_mod.today_jst())
    send_kw: dict[str, Any] = {"poster": poster} if poster else {}
    try:
        cfg = cfg or config_mod.load()
        (run or pipeline)(cfg, today)
    except Exception:
        traceback.print_exc()
        notify.send(cfg if cfg is not None else config_mod.fallback(), "失敗", today, **send_kw)
        return 1
    if today.weekday() == 0:
        notify.send(cfg, "週次 OK", today, **send_kw)
    else:
        print("ntfy: 送信なし HTTP -（成功・月曜以外は送らない）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
