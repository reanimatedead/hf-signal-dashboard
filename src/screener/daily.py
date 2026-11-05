"""毎日 19:00（launchd）に動く本体: python -m screener.daily

1. リポジトリ（config の repo_dir、既定 ~/hf-signal-dashboard）で git pull --ff-only。
   そのあと自分自身を起動し直す（os.execv で `uv run python -m screener.daily --pulled`）。
   こうしないと pull の前に読み込んだ古いコードのまま走り、pull した修正が次の日まで効かない。
   uv run で起動し直すので、uv.lock が変わっていれば依存もそろえ直される。
2. J-Quants 契約テスト（V2・日足 ≥3500 件・決算短信の列）
3. 差分を取得（日本株 J-Quants は直近3営業日を取り直す・米国株と FX・仮想通貨は Yahoo の日足）
4. 一覧（screen → signals）→ local_report（<data_dir>/out/ にだけ書く）
5. CCI ±200 の抜けを Mac mini の通知で1回出す（screener.alerts。既定は osascript。
   本文の最後に一覧の場所。ntfy には送らない）
6. 最後に <data_dir>/out/today.html「今日の要点」を作る（screener.today。ローカルだけ）
失敗したら ntfy に「失敗＋日付」を送って終了コード 1。
成功したら何も送らない。ただし月曜は最後に「週次 OK＋日付」を1回送る。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable
from typing import Any

from . import alerts, contract, local_report, notify
from . import config as config_mod
from . import today as today_page
from .config import Config
from .jquants import Getter, default_client

Runner = Callable[..., Any]
Exec = Callable[[str, list[str]], Any]


def git_pull(cfg: Config, runner: Runner = subprocess.run) -> None:
    r = runner(["git", "-C", str(cfg.repo_dir), "pull", "--ff-only"], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"git pull --ff-only が失敗（{cfg.repo_dir}）: {str(r.stderr).strip()[:300]}")


def reexec_argv(cfg: Config, args: list[str]) -> tuple[str, list[str]]:
    """pull したあとの起動し直し方。uv があれば uv run（依存もそろう）、無ければ同じ python。"""
    rest = ["-m", "screener.daily", "--pulled", *args]
    uv = shutil.which("uv")
    if uv:
        return uv, [uv, "run", "--project", str(cfg.repo_dir), "python", *rest]
    return sys.executable, [sys.executable, *rest]


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
    from . import fxcrypto

    print("fx/crypto", fxcrypto.fetch(cfg), flush=True)  # 取れなかった銘柄は前回のまま（止めない）


mac_notify: Callable[..., Any] = alerts.notify  # テストで差し替える


def pipeline(
    cfg: Config,
    today: dt.date,
    get: Getter | None = None,
    us_update: Callable[[Config, dt.date], None] = update_us,
) -> dict[str, Any]:
    """git pull と起動し直しは main が先に済ませている（ここは新しいコードで走る）。"""
    from .japan import fetch as jp_fetch
    from .japan import signals

    cfg.ensure_dirs()
    if get is None:
        get = default_client(int(cfg.get("jquants.rate_per_min", 50)), str(cfg.get("jquants.keychain_service"))).get
    print(contract.check(today, get), flush=True)
    print("japan fetch", jp_fetch.run(cfg, today, get=get), flush=True)
    us_update(cfg, today)
    doc = signals.run(cfg)
    c = local_report.write(cfg, doc)
    print("counts", json.dumps(c, ensure_ascii=False), flush=True)  # 件数だけ
    if doc.get("cci_alerts"):
        mac_notify(
            doc["cci_alerts"],
            local_report.alerts_html(cfg, doc),
            prefer=str(cfg.get("alerts.notifier", "osascript") or "osascript"),
        )
    print("today.html →", today_page.write(cfg, doc), flush=True)  # 最後に「今日の要点」（ローカルだけ）
    return c


def main(
    argv: list[str] | None = None,
    cfg: Config | None = None,
    today: dt.date | None = None,
    run: Callable[[Config, dt.date], Any] | None = None,
    poster: notify.Poster | None = None,
    runner: Runner = subprocess.run,
    execv: Exec = os.execv,
) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--today", help="基準日（既定: 今日 JST）")
    ap.add_argument("--pulled", action="store_true", help="git pull 済み（起動し直したあと。手で付けない）")
    args = sys.argv[1:] if argv is None else list(argv)
    a = ap.parse_args(args)
    today = today or (dt.date.fromisoformat(a.today) if a.today else config_mod.today_jst())
    send_kw: dict[str, Any] = {"poster": poster} if poster else {}
    try:
        cfg = cfg or config_mod.load()
        if not a.pulled:
            git_pull(cfg, runner)
            print("git pull --ff-only: OK → 新しいコードで起動し直す", flush=True)
            sys.stdout.flush()
            sys.stderr.flush()
            prog, new_argv = reexec_argv(cfg, [x for x in args if x != "--pulled"])
            execv(prog, new_argv)  # 戻らない（テストでは差し替え）
            return 0
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
