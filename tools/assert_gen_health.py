#!/usr/bin/env python3
"""tools/assert_gen_health.py — 生成直後のハード assert（deploy.yml 内で実行）。

deploy.yml の full ジョブで fetch_signals.py → build_corr.py → 他 layer を
生成した"直後"に走らせ、以下の 2 条件のいずれかを満たさない場合は非ゼロ終了
してジョブ自体を赤くする。probe(verify_live) は外形監視で 2h 遅延・平均 4h
遅延なので、内側でも自壊させる方が事故発覚が早い（生成ジョブが緑のまま
Pages 側に古い/欠けたペイロードを配れる事を潰す）。

判定（両方満たさなければ FAIL）:
  1. meta.updated_at が現在から STALE_HOURS(既定 48h)以内
  2. 株式 4 タブ(nikkei225/dow30/nasdaq100/sp500)の chart_status=ready 率が
     READY_MIN_PCT(既定 90%)以上

しきい値は tools/gate_thresholds.py に集約されており、環境変数
VERIFY_STALE_HOURS / VERIFY_READY_MIN で上書き可能。

health_gate.py と重複しないのか?
  - health_gate.py は per-domain の観測 lag（us_rates>3d, jgb>5d 等）中心。
  - このスクリプトは "meta.updated_at 自体の新しさ" と "被覆率" のみに
    絞った最終ゲートで、health_gate と直交する追加安全網。生成が成功して
    updated_at がまともに更新されているか、被覆が急落していないかを見る。

使い方:
    python3 tools/assert_gen_health.py [path/to/data.json]
    既定パス = docs/data.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from gate_thresholds import READY_MIN_PCT, STALE_HOURS  # type: ignore

EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _ready_pct(markets: dict) -> tuple[float, dict, int]:
    per: dict[str, str] = {}
    total = ready = 0
    for tab in EQUITY_TABS:
        rows = markets.get(tab, []) or []
        r = sum(1 for x in rows if x.get("chart_status") == "ready")
        per[tab] = f"{r}/{len(rows)}"
        total += len(rows)
        ready += r
    pct = (ready / total * 100.0) if total else 0.0
    return pct, per, total


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/data.json")
    if not path.exists():
        print(f"assert_gen_health: FAIL — {path} does not exist")
        return 1

    data = _load(path)
    fails: list[str] = []
    lines = [f"assert_gen_health path={path}"]

    upd = (data.get("meta") or {}).get("updated_at")
    age_h = _age_hours(upd)
    lines.append(
        f"  freshness   updated_at={upd} age="
        f"{'?' if age_h is None else round(age_h, 2)}h (limit {STALE_HOURS}h)"
    )
    if age_h is None:
        fails.append("meta.updated_at missing/unparseable")
    elif age_h > STALE_HOURS:
        fails.append(f"stale generation: {age_h:.2f}h > {STALE_HOURS}h")

    markets = data.get("markets") or {}
    pct, per, total = _ready_pct(markets)
    lines.append(
        f"  completeness equity ready {pct:.2f}% {per} "
        f"(limit {READY_MIN_PCT}%)"
    )
    if total == 0:
        fails.append("equity markets empty (no rows across all 4 tabs)")
    elif pct < READY_MIN_PCT:
        fails.append(f"equity ready {pct:.2f}% < {READY_MIN_PCT}%")

    print("\n".join(lines))
    if fails:
        print(f"\nassert_gen_health: FAIL ({len(fails)}) → " + "; ".join(fails))
        return 1
    print("\nassert_gen_health: OK — freshness & completeness both above thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
