#!/usr/bin/env python3
"""tools/verify_live.py — 外形監視（公開サイトの実物を叩く）。

デプロイ後の「配信されているつもり」を外側から潰す。CI 内のゲート（health_gate /
contract test）は生成物を検査するが、**Pages に実際に届いているか**は別問題。
過去の 213h サイレント停止（上流 yfinance 起因で更新が静かに止まった）を
検知する目的で作られた。今回のバージョンは以下を追加している。

M1: HTTP 取得のリトライと 4xx/5xx 分岐
  5xx / タイムアウト / 接続エラー → RETRY_MAX 回リトライ、間隔 BACKOFF_SEC
  4xx（特に 404/403/410）→ 即 FAIL（リトライしない・ファイル消失は待っても直らない）
  429 (Rate Limited) はリトライ許容

M2: as_of 鮮度チェックを macro_v2 / relations / gamma に拡張
  data.json の meta.updated_at と同格で、3ファイルの top-level as_of を検査
  as_of フィールドが無い / パースできない → FAIL（黙って skip しない）
  タイムゾーンは全部 aware datetime。data.json は +09:00, 他は +00:00

M4: 補助層（soft layer）— 2026-11-25〜
  CBOE が公開エンドポイントを封鎖（Cloudflare 403）したため gamma.json は古いまま
  data_status="stale" で再掲されうる。毎回 exit 1 のオオカミ少年を避けるため、
  env VERIFY_SOFT_LAYERS（カンマ区切り、既定 "gamma.json"）に挙げた層は
  鮮度切れ / as_of 欠落・パース不能 / top-level data_status が stale・error でも
  fails に入れず `WARN ...` と `::warning::...` を印字するだけにする（exit 不変）。
  ただし 403/404/410（ファイル消失）は従来どおり硬い失敗（exit 2）。消失は隠さない。

exit code:
  0 = OK（補助層の WARN のみの場合も 0）
  1 = 一時的な失敗（5xx/接続系がリトライ後も回復せず、または主層の鮮度切れなど）
  2 = 硬い失敗（404/403/410 = ファイル消失/権限異常。Issue 即発火。補助層も同じ）

使い方:
    python3 tools/verify_live.py [BASE_URL]
    BASE_URL 既定 = env PAGES_BASE または https://reanimatedead.github.io/hf-signal-dashboard

生出力主義: 実測した HTTP コード・試行回数・鮮度・経過時間をそのまま印字する。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# 設定（1箇所にまとめる。マジックナンバーを散らさない）
# ─────────────────────────────────────────────

DEFAULT_BASE = os.environ.get(
    "PAGES_BASE", "https://reanimatedead.github.io/hf-signal-dashboard")

# 鮮度しきい値。全 4 ファイル 48h に統一する。
# 理由: パイプラインは 1 日 1 回同一バッチで全ファイルを生成する（実測:
# 2026-09-14 19:49-19:50 UTC / 2026-09-15 04:49 JST に 4 ファイル同時更新）。
# したがって同じしきい値でよい。48h は 1 日分の遅延バッファ（土日跨ぎや
# 上流障害の 1 サイクル欠損は許容、2 サイクル連続欠損は検知）。
STALE_H = float(os.environ.get("VERIFY_STALE_HOURS", "48"))
# key = path, value = (dict key path, freshness limit hours)
FRESHNESS_TARGETS = {
    "data.json":      (("meta", "updated_at"), STALE_H),
    "macro_v2.json":  (("as_of",),             STALE_H),
    "relations.json": (("as_of",),             STALE_H),
    "gamma.json":     (("as_of",),             STALE_H),
}

READY_MIN = float(os.environ.get("VERIFY_READY_MIN", "90"))

# HTTP リトライ
RETRY_MAX = 3                       # attempt 1..RETRY_MAX
BACKOFF_SEC = [2.0, 5.0, 10.0]      # 「i 番目の失敗後 → BACKOFF_SEC[i]」で待機
TIMEOUT = 20
UA = {"User-Agent": "hf-signal-dashboard verify_live (synthetic monitor)"}

# しきい値の正本は tools/gate_thresholds.py。CI で verify_live 側の env を
# 上書きしていないか cross-check。
try:
    from gate_thresholds import STALE_HOURS as _CANON_STALE_H  # type: ignore
    from gate_thresholds import READY_MIN_PCT as _CANON_READY_MIN  # type: ignore
    if abs(STALE_H - _CANON_STALE_H) > 1e-9 or abs(READY_MIN - _CANON_READY_MIN) > 1e-9:
        print(
            f"verify_live: WARN threshold mismatch verify_live=({STALE_H},{READY_MIN}) "
            f"gate_thresholds=({_CANON_STALE_H},{_CANON_READY_MIN})",
            file=sys.stderr,
        )
except Exception:  # noqa: BLE001
    pass

EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")

# 硬い失敗（Issue 即発火）を発生させる HTTP コード。ファイル消失・権限異常。
HARD_FAIL_STATUS = frozenset({403, 404, 410})

# 補助層の data_status で警告にする値。
SOFT_BAD_DATA_STATUS = ("stale", "error")


def soft_layers():
    """env VERIFY_SOFT_LAYERS（カンマ区切り、既定 "gamma.json"）。空文字なら補助層なし。
    import 時ではなく main() 内で読む（テスト・CI から env で切り替えられるように）。"""
    raw = os.environ.get("VERIFY_SOFT_LAYERS", "gamma.json")
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


# ─────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────

def _fetch(base, path):
    """1 発 GET。(status:int|None, body:bytes|None, err:str|None, elapsed_ms:int)。"""
    url = f"{base}/{path}" if path else base + "/"
    req = urllib.request.Request(url, headers=UA)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            return r.status, body, None, int((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}", int((time.monotonic() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}", int((time.monotonic() - t0) * 1000)


def get_with_retry(base, path):
    """5xx / timeout / connection error は最大 RETRY_MAX 回リトライ。
    4xx (HARD_FAIL_STATUS + それ以外の 4xx で 429 以外) は 1 回で即 return
    （リトライしない・ファイル消失は待っても直らない）。

    Returns (status, body, err, attempts, elapsed_ms, hard_fail:bool)
    """
    last_err = None
    last_status = None
    last_elapsed = 0
    for attempt in range(1, RETRY_MAX + 1):
        status, body, err, elapsed = _fetch(base, path)
        last_status, last_elapsed = status, elapsed
        # 成功
        if status == 200:
            return status, body, None, attempt, elapsed, False
        # ハード失敗 → リトライしない
        if status is not None and status in HARD_FAIL_STATUS:
            return status, body, err, attempt, elapsed, True
        # 4xx でも 429 は「レート制限」= 一時的とみなしリトライ許容。
        # それ以外の 4xx（400/401/405 等）は本物の異常 → ハード扱い。
        if status is not None and 400 <= status < 500 and status != 429:
            return status, body, err, attempt, elapsed, True
        # 5xx / 429 / タイムアウト / 接続系 → リトライ
        last_err = err
        if attempt < RETRY_MAX:
            wait = BACKOFF_SEC[min(attempt - 1, len(BACKOFF_SEC) - 1)]
            time.sleep(wait)
    return last_status, None, last_err, RETRY_MAX, last_elapsed, False


# ─────────────────────────────────────────────
# 鮮度
# ─────────────────────────────────────────────

def parse_ts(raw):
    """ISO 8601 文字列 → aware UTC datetime。失敗時 None。
    'Z' 終端を +00:00 に読み替える。naive の場合は UTC と解釈する。
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def dig(d, path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

def main():
    hard_fail = False
    fails = []
    warns = []          # 補助層（soft layer）の劣化。exit code には影響しない
    soft = soft_layers()
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")
    lines = [f"verify_live BASE={base}"]

    # 1) index.html
    st, _, err, att, ms, hard = get_with_retry(base, "")
    lines.append(f"  index.html      HTTP={st} (attempt {att}/{RETRY_MAX}, {ms}ms) {err or ''}".rstrip())
    if st != 200:
        fails.append(f"index.html HTTP={st}")
        if hard: hard_fail = True

    # 2) data.json — 本体（body が要る）
    st, body, err, att, ms, hard = get_with_retry(base, "data.json")
    lines.append(f"  data.json       HTTP={st} (attempt {att}/{RETRY_MAX}, {ms}ms) {err or ''}".rstrip())
    d = None
    if st != 200 or body is None:
        fails.append(f"data.json HTTP={st}")
        if hard: hard_fail = True
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
    # data.json 以外の 3 ファイルは 200 と鮮度の両方をチェック。
    other_bodies = {}
    for extra in ("relations.json", "gamma.json", "macro_v2.json"):
        st, body, err, att, ms, hard = get_with_retry(base, extra)
        lines.append(f"  {extra:15s} HTTP={st} (attempt {att}/{RETRY_MAX}, {ms}ms) {err or ''}".rstrip())
        if st != 200:
            fails.append(f"{extra} HTTP={st}")
            if hard: hard_fail = True
        elif body is not None:
            try:
                other_bodies[extra] = json.loads(body)
            except Exception as e:  # noqa: BLE001
                fails.append(f"{extra} parse: {e}")

    # 4) 鮮度チェック（4 ファイル）— M2 の本命
    #    補助層（soft）は鮮度切れ・as_of 欠落/パース不能・data_status 劣化を WARN に落とす（M4）
    now = datetime.now(timezone.utc)
    for path, (key_path, limit_h) in FRESHNESS_TARGETS.items():
        if path == "data.json":
            src = d
        else:
            src = other_bodies.get(path)
        if src is None:
            # HTTP 段階で既に落ちている場合はスキップ（fails 済み）
            continue
        is_soft = path in soft
        age_stale = False
        raw = dig(src, key_path)
        if raw is None:
            lines.append(f"  freshness {path:15s} MISSING {'.'.join(key_path)} (limit {limit_h}h)")
            if is_soft:
                warns.append(f"{path} freshness key {'.'.join(key_path)} missing (soft layer)")
            else:
                fails.append(f"{path} freshness key {'.'.join(key_path)} missing (silent-stop signature)")
                continue
        else:
            dt = parse_ts(raw)
            if dt is None:
                lines.append(f"  freshness {path:15s} UNPARSEABLE {raw!r} (limit {limit_h}h)")
                if is_soft:
                    warns.append(f"{path} freshness key {'.'.join(key_path)} unparseable: {raw!r} (soft layer)")
                else:
                    fails.append(f"{path} freshness key {'.'.join(key_path)} unparseable: {raw!r}")
                    continue
            else:
                age_h = (now - dt).total_seconds() / 3600
                lines.append(f"  freshness {path:15s} ts={raw} age={age_h:.1f}h (limit {limit_h}h)")
                if age_h > limit_h:
                    if is_soft:
                        age_stale = True
                        warns.append(f"{path} stale: {age_h:.0f}h (soft layer)")
                    else:
                        fails.append(f"{path} stale: {age_h:.1f}h > {limit_h}h")
        if is_soft and not age_stale and isinstance(src, dict):
            ds = src.get("data_status")
            if ds in SOFT_BAD_DATA_STATUS:
                warns.append(f"{path} data_status={ds} (soft layer)")

    print("\n".join(lines))
    for w in warns:
        print(f"WARN {w}")
        print(f"::warning::{w}")
    if fails:
        print(f"\nverify_live: FAIL ({len(fails)}) → " + "; ".join(fails))
        return 2 if hard_fail else 1
    print("\nverify_live: OK — 公開サイトは配信・鮮度・被覆すべて健全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
