"""シグナル後 N 営業日の値動きを、全期間の平均（基準）と同じ方法で比べる。データは持たない。"""

import numpy as np

H = 20  # 何営業日後を見るか
GAP = 20  # 同じ銘柄の連続シグナルは20日に1回だけ数える
WARMUP = 288  # 指標が揃うまでの本数


def stats(v):
    v = np.asarray([t for t in v if t is not None and np.isfinite(t)], dtype=float)
    if not len(v):
        return {"n": 0, "mean": None, "median": None, "up_pct": None}
    return {
        "n": int(len(v)),
        "mean": round(float(v.mean()), 2),
        "median": round(float(np.median(v)), 2),
        "up_pct": round(float((v > 0).mean() * 100), 1),
    }


def event_returns(close, conds, h=H, gap=GAP, start=WARMUP, dates=None, since=None):
    """close: 終値配列, conds: {名前: bool配列}。戻り値 {"base":[...], 名前:[...]} （h日後騰落%）。
    since（YYYY-MM-DD）と dates を渡すと、その日以降のシグナルだけ数える（直近6か月の確認用）。"""
    C = np.asarray(close, dtype=float)
    out = {"base": []}
    last = {}
    for k in conds:
        out[k] = []
        last[k] = -(10**9)
    for i in range(start, len(C) - h):
        if since and dates is not None and dates[i] < since:
            continue
        if not (np.isfinite(C[i]) and np.isfinite(C[i + h]) and C[i] > 0):
            continue
        f = (C[i + h] / C[i] - 1) * 100
        out["base"].append(f)
        for k, cond in conds.items():
            if cond[i] and i - last[k] >= gap:
                last[k] = i
                out[k].append(f)
    return out


def merge(acc, part):
    for k, v in part.items():
        acc.setdefault(k, []).extend(v)
    return acc


def weakened(sig_stats, base_stats, min_n=5):
    """根拠が弱まったか: シグナル後の中央値が基準の中央値を下回る（件数が少なすぎるときは判定しない）。"""
    if (
        not sig_stats
        or sig_stats.get("n", 0) < min_n
        or sig_stats.get("median") is None
        or base_stats.get("median") is None
    ):
        return None
    return sig_stats["median"] < base_stats["median"]
