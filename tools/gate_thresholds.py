#!/usr/bin/env python3
"""tools/gate_thresholds.py — 更新パイプラインのしきい値正本。

verify_live.py / health_gate.py / assert_gen_health.py が共有する数値定数を
一箇所に集約する。個別スクリプト内での重複定義は撤廃し、ここが唯一の正本。

環境変数で上書き可能（CI からの一時的な緩和/厳格化のため）。値の意味:

    STALE_HOURS  ... data.json の meta.updated_at が古いと判定するしきい値[h]
                     verify_live.py の外形検査、assert_gen_health.py の生成
                     直後チェック、いずれも同じ値を参照する。
    READY_MIN_PCT ... 株式4タブ(nikkei225/dow30/nasdaq100/sp500)の
                     chart_status=ready 率の下限[%]。90 未満で FAIL。
                     health_gate / verify_live / assert_gen_health 共通。

環境変数名:
    VERIFY_STALE_HOURS   (既存の verify_live.py が使ってきた名前を継続)
    VERIFY_READY_MIN     (同上)

2026-08-19 追加: 8/11 の deploy スタックで data.json が 213h 古くなった際、
各スクリプトが独自に "48" / "90" をハードコードしていた事を受けて集約した。
"""
from __future__ import annotations

import os


def _f(env_name: str, default: float) -> float:
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


STALE_HOURS: float = _f("VERIFY_STALE_HOURS", 48.0)
READY_MIN_PCT: float = _f("VERIFY_READY_MIN", 90.0)


__all__ = ["STALE_HOURS", "READY_MIN_PCT"]
