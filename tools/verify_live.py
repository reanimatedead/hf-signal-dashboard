#!/usr/bin/env python3
"""tools/verify_live.py — 外形監視（公開サイトの実物を叩く）。

デプロイ後の「配信されているつもり」を外側から潰す。CI 内のゲート（health_gate /
contract test）は生成物を検査するが、**Pages に実際に届いているか**は別問題。
今回 `data.json` が 404 のまま復旧しなかったのを、内部テストは検知できなかった。
このスクリプトは公開 URL を直接 GET し、届いていなければ **exit 1** で落として
`monitor.yml` 経由で通知を出す（人間が気づく前にアラートを鳴らす）。

判定（いずれか NG で exit 1）:
  - `<base>/` (index.html) が HTTP 200
  - `<base>/data.json` が HTTP 200 かつ JSON parse 可能
  - data.json に markets/summary/money_flow/survival_loop が存在
  - meta.updated_at が STALE_H 時間以内（既定 48h）
  - 株式4タブの chart_status=ready 率 >= READY_MIN%（既定 90%）
  - `<base>/relations.json` / `<base>/gamma.json` / `<base>/macro_v2.json` が HTTP 200

使い方:
    python3 tools/verify_live.py [BASE_URL]
    BASE_URL 既定 = env PAGES_BASE または https://reanimatedead.github.io/hf-signal-dashboard

生出力主義: 実測した HTTP コード・鮮度・ready 率をそのまま印字する。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE = os.environ.get(
    "PAGES_BASE", "https://reanimatedead.github.io/hf-signal-dashboard")
BASE = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")

STALE_H = float(os.environ.get("VERIFY_STALE_HOURS", "48"))
READY_MIN = float(os.environ.get("VERIFY_READY_MIN", "90"))
EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")
UA = {"User-Agent": "hf-signal-dashboard verify_live (synthetic monitor)"}
TIMEOUT = 20


def _get(path):
    """(status:int|None, body:bytes|None, err:str|None)。"""
    url = f"{BASE}/{path}" if path else BASE + "/"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(), None
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"


def main():
    fails = []
    lines = [f"verify_live BASE={BASE}"]

    # 1) index.html
    st, _, err = _get("")
    lines.append(f"  index.html      HTTP={st} {err or ''}".rstrip())
    if st != 200:
        fails.append(f"index.html HTTP={st}")

    # 2) data.json — 本体
    st, body, err = _get("data.json")
    lines.append(f"  data.json       HTTP={st} {err or ''}".rstrip())
    if st != 200 or body is None:
        fails.append(f"data.json HTTP={st}")
    else:
        try:
            d = json.loads(body)
        except Exception as e:  # noqa: BLE001
            fails.append(f"data.json parse: {e}")
            d = None
        if d is not None:
            missing = [k for k in ("markets", "summary", "money_flow", "survival_loop")
                       if k not in d]
            if missing:
                fails.append(f"data.json missing keys: {missing}")

            # 鮮度
            upd = (d.get("meta") or {}).get("updated_at")
            age_h = None
            if upd:
                try:
                    dt = datetime.fromisoformat(str(upd).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                except Exception:  # noqa: BLE001
                    age_h = None
            lines.append(f"  freshness       updated_at={upd} age={age_h if age_h is None else round(age_h,1)}h "
                         f"(limit {STALE_H}h)")
            if age_h is None:
                fails.append("data.json meta.updated_at missing/unparseable")
            elif age_h > STALE_H:
                fails.append(f"data.json stale: {age_h:.1f}h > {STALE_H}h")

            # 株式 ready 率
            m = d.get("markets") or {}
            tot = rdy = 0
            per = {}
            for tab in EQUITY_TABS:
                rows = m.get(tab, [])
                r = sum(1 for x in rows if x.get("chart_status") == "ready")
                per[tab] = f"{r}/{len(rows)}"
                tot += len(rows)
                rdy += r
            pct = (rdy / tot * 100) if tot else 0.0
            lines.append(f"  equity ready    {pct:.1f}% {per} (limit {READY_MIN}%)")
            if tot and pct < READY_MIN:
                fails.append(f"equity ready {pct:.1f}% < {READY_MIN}%")

            # 件数の意味を混同させない（DATA_CONTRACT §20）: 上の "r/len(rows)" は
            # ready 数 / 行数（^index proxy 込み）。構成銘柄数の正は meta.universe。
            # S&P500 は複数株式クラス（GOOGL/GOOG・FOX/FOXA・NWS/NWSA）で 500 社 >500
            # 銘柄になるため count=503 は正常（異常ではない）。表示のみ・判定は不変。
            sp = ((d.get("meta") or {}).get("universe") or {}).get("sp500") or {}
            if sp:
                lines.append(f"  sp500 universe  count={sp.get('count')}"
                             f"/target={sp.get('target')} (構成銘柄のみ・^GSPC除外; "
                             f"複数株式クラスにより >500 は正常)")

    # 3) 派生層の到達性
    for extra in ("relations.json", "gamma.json", "macro_v2.json"):
        st, _, err = _get(extra)
        lines.append(f"  {extra:15s} HTTP={st} {err or ''}".rstrip())
        if st != 200:
            fails.append(f"{extra} HTTP={st}")

    print("\n".join(lines))
    if fails:
        print(f"\nverify_live: FAIL ({len(fails)}) → " + "; ".join(fails))
        return 1
    print("\nverify_live: OK — 公開サイトは配信・鮮度・被覆すべて健全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
