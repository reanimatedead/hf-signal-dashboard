"""CCI と ボリンジャーバンド、売買判定（日足）。入力は numpy 配列のみ（データは持たない）。"""

import numpy as np

P = {"cci_long": 288, "cci_short": 48, "bb_long": 288, "bb_short": 48, "k2": 2.0, "k3": 3.0, "cci_th": 100}
MIN_BARS = 300  # 判定を出すのに必要な最低本数（288 + 余裕）

# 判定はコード（表示の言葉は描画側の辞書: 公開画面は docs/assets/i18n、ローカルは screener.labels）。
LABELS = {2: "buy_strong", 1: "buy", 0: "neutral", -1: "sell", -2: "sell_strong"}
LONG_OVERSOLD_LABEL = "buy_long_oversold"
SELL_NOTE = "sell_note"  # 売り系の補足（空売りの根拠ではない）のコード
TREND = {True: "long_up", False: "long_down"}


def sma(x, n):
    x = np.asarray(x, dtype=float)
    s = np.full_like(x, np.nan)
    if len(x) < n:
        return s
    c = np.cumsum(np.insert(x, 0, 0.0))
    s[n - 1 :] = (c[n:] - c[:-n]) / n
    return s


def rolling_std(x, n):
    """母標準偏差（ddof=0）。"""
    x = np.asarray(x, dtype=float)
    m = sma(x, n)
    m2 = sma(x * x, n)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def bb(c, n):
    return sma(c, n), rolling_std(c, n)


def cci(h, l, c, n):
    h, l, c = (np.asarray(v, dtype=float) for v in (h, l, c))
    tp = (h + l + c) / 3
    m = sma(tp, n)
    md = np.full_like(tp, np.nan)
    for i in range(n - 1, len(tp)):
        w = tp[i - n + 1 : i + 1]
        md[i] = np.mean(np.abs(w - m[i]))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (tp - m) / (0.015 * md)


def compute(h, l, c, p=P):
    h, l, c = (np.asarray(v, dtype=float) for v in (h, l, c))
    ok = ~np.isnan(c)
    h, l, c = h[ok], l[ok], c[ok]
    h = np.where(np.isnan(h), c, h)
    l = np.where(np.isnan(l), c, l)
    mS, sS = bb(c, p["bb_short"])
    mL, sL = bb(c, p["bb_long"])
    return {
        "ok": ok,
        "h": h,
        "l": l,
        "c": c,
        "cciL": cci(h, l, c, p["cci_long"]),
        "cciS": cci(h, l, c, p["cci_short"]),
        "mS": mS,
        "sS": sS,
        "mL": mL,
        "sL": sL,
    }


def signals(x, p=P):
    """+1=買い（長期上向きの押し目）、+2=強い買い（-3σ）、-1=売り（長期下向きの戻り）、-2=強い売り（+3σ）、0=なし

    買い:  CCI288 > 0 かつ 終値 <= BB48 -2σ かつ CCI48 < -100
    売り:  CCI288 < 0 かつ 終値 >= BB48 +2σ かつ CCI48 > +100
    """
    c, cL, cS, mS, sS = x["c"], x["cciL"], x["cciS"], x["mS"], x["sS"]
    s = np.zeros(len(c), dtype=int)
    with np.errstate(invalid="ignore"):
        buy = (cL > 0) & (c <= mS - p["k2"] * sS) & (cS < -p["cci_th"])
        sell = (cL < 0) & (c >= mS + p["k2"] * sS) & (cS > p["cci_th"])
        s[buy] = 1
        s[buy & (c <= mS - p["k3"] * sS)] = 2
        s[sell] = -1
        s[sell & (c >= mS + p["k3"] * sS)] = -2
    return s


def long_oversold(x, p=P):
    """BB288 の −2σ 以下（長期の売られすぎ）。"""
    with np.errstate(invalid="ignore"):
        return x["c"] <= x["mL"] - p["k2"] * x["sL"]


def _r(v, nd):
    v = float(v)
    return None if not np.isfinite(v) else round(v, nd)


def judge(x, p=P, i=None):
    """i 日目（既定は最新日）の状態をコードで返す（言葉にするのは描画側）。"""
    i = len(x["c"]) - 1 if i is None else i
    c, mS, sS, mL, sL = x["c"][i], x["mS"][i], x["sS"][i], x["mL"][i], x["sL"][i]
    zS = (c - mS) / sS if sS else np.nan
    zL = (c - mL) / sL if sL else np.nan
    s = int(signals(x, p)[i])
    trend = TREND[bool(x["cciL"][i] > 0)]
    label = LABELS[s]
    lo = bool(long_oversold(x, p)[i])
    if lo and s >= 0:
        label = LONG_OVERSOLD_LABEL if s == 0 else label
    return {
        "label": label,
        "signal": s,
        "long_oversold": lo,
        "trend": trend,
        "zS": _r(zS, 2),
        "zL": _r(zL, 2),
        "cciL": _r(x["cciL"][i], 0),
        "cciS": _r(x["cciS"][i], 0),
    }


def summary(h, l, c, p=P):
    """公開ダッシュボード用の列（chart_signal / cci288 / cci48 / bb48_z / bb288_z）。
    本数不足なら None を返す（作らない・ごまかさない）。"""
    c = np.asarray(c, dtype=float)
    if np.sum(~np.isnan(c)) < MIN_BARS:
        return None
    x = compute(h, l, c, p)
    j = judge(x, p)
    return {
        "chart_signal": j["label"],
        "chart_signal_code": j["signal"],
        "long_oversold": j["long_oversold"],
        "trend": j["trend"],
        "cci288": j["cciL"],
        "cci48": j["cciS"],
        "bb48_z": j["zS"],
        "bb288_z": j["zL"],
    }


def chart_series(h, l, c, p=P, tail=None, nd=4):
    """銘柄詳細チャート用の系列（終値・BB48/288 ±2σ/±3σ・CCI48/288・判定の印）。
    nd は価格系列の小数桁（容量を抑えるため呼ぶ側が株価の桁に合わせて渡す）。"""
    x = compute(h, l, c, p)
    s = signals(x, p)
    lo = long_oversold(x, p)
    n = len(x["c"])
    a = 0 if not tail else max(0, n - tail)

    def arr(v, nd=nd):
        return [None if not np.isfinite(t) else round(float(t), nd) for t in v[a:]]

    out = {"close": arr(x["c"]), "cci48": arr(x["cciS"], 1), "cci288": arr(x["cciL"], 1)}
    for k, (m, sd) in (("bb48", (x["mS"], x["sS"])), ("bb288", (x["mL"], x["sL"]))):
        out[k] = {
            "mid": arr(m),
            "p2": arr(m + 2 * sd),
            "m2": arr(m - 2 * sd),
            "p3": arr(m + 3 * sd),
            "m3": arr(m - 3 * sd),
        }
    out["marks"] = [
        {"i": i - a, "type": ("buy" if s[i] > 0 else "sell"), "code": int(s[i])} for i in range(a, n) if s[i] != 0
    ]
    out["marks"] += [{"i": i - a, "type": "long_oversold", "code": 1} for i in range(a, n) if lo[i] and s[i] == 0]
    out["index_map"] = np.flatnonzero(x["ok"]).tolist()[a:]
    return out


BUY_LABELS = (LABELS[2], LABELS[1], LONG_OVERSOLD_LABEL)  # 買い系（画面の「買い判定一覧」・検証の弱まり判定に使う）
SELL_LABELS = (LABELS[-1], LABELS[-2])


def label_conditions(x, p=P):
    """判定コードごとの日次 bool 配列（検証用）。judge() の最新日のコードと同じ規則:
    buy_strong / buy / buy_long_oversold（シグナル0 かつ BB288 -2σ 以下）/ sell / sell_strong。"""
    s = signals(x, p)
    lo = long_oversold(x, p)
    return {
        LABELS[2]: s == 2,
        LABELS[1]: s == 1,
        LONG_OVERSOLD_LABEL: lo & (s == 0),
        LABELS[-1]: s == -1,
        LABELS[-2]: s == -2,
    }
