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


def day_labels(x, p=P):
    """日ごとの判定コード（画面の判定・検証の両方がこれだけを使う。規則はここ1か所）。
    シグナル（buy_strong/buy/neutral/sell/sell_strong）が基本。長期の売られすぎ（BB288 -2σ 以下）は
    シグナルが 0 の日だけ buy_long_oversold にする（売りと同じ日は売り、買いと同じ日は買いのまま）。"""
    s = signals(x, p)
    lab = np.array([LABELS[int(v)] for v in s], dtype=object)
    lab[long_oversold(x, p) & (s == 0)] = LONG_OVERSOLD_LABEL
    return lab


def is_buy_type(label):
    """買い系の判定コードか（買い / 強い買い / 買い（長期の売られすぎ））。"""
    return (label or "") in BUY_LABELS


def buy_type_days(x, p=P):
    """買い系の日の bool 配列（day_labels と同じ規則）。"""
    return np.isin(day_labels(x, p), BUY_LABELS)


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
    label = str(day_labels(x, p)[i])
    lo = bool(long_oversold(x, p)[i])
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
    rc = cci200_recent(x)
    return {
        "cci200_signal": rc["code"] if rc and rc["bars_ago"] == 0 else None,
        "cci200_recent": rc,
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
    for code, arr in cci200_days(x).items():  # ◆ 買い（CCI −200）/ ◆ 売り目安（CCI +200）
        out["marks"] += [
            {"i": i - a, "type": code, "code": 1 if code == CCI200_BUY else -1} for i in range(a, n) if arr[i]
        ]
    out["index_map"] = np.flatnonzero(x["ok"]).tolist()[a:]
    return out


BUY_LABELS = (LABELS[2], LABELS[1], LONG_OVERSOLD_LABEL)  # 買い系（画面の「買い判定一覧」・検証の弱まり判定に使う）
SELL_LABELS = (LABELS[-1], LABELS[-2])


def label_conditions(x, p=P):
    """判定コードごとの日次 bool 配列（検証用）。day_labels と同じ規則。"""
    lab = day_labels(x, p)
    return {k: lab == k for k in (LABELS[2], LABELS[1], LONG_OVERSOLD_LABEL, LABELS[-1], LABELS[-2])}


# ── CCI ±200 の抜け（通知と検証の両方がこれだけを使う。規則はここ1か所）──────────────────
CCI_ALERT_LEVEL = 200  # ±200
SPIKE_Q = 0.99  # 「一斉に割れ」: 過去1年の日々の件数の上位1%を超えた日
SPIKE_LOOKBACK = 245  # 過去1年 ≒ 245 営業日
SPIKE_MIN_DAYS = 120  # これより短い履歴では「一斉に割れ」を判定しない
SPIKE_MIN_FRAC = (
    0.015  # 「一斉に割れ」の最低件数 = その市場の銘柄数の 1.5%（日本株 約3,600 → 54件、米国株 約520 → 8件）
)
CCI_EVENTS = ("both_down", "cci48_down", "cci288_down", "both_up", "cci48_up", "cci288_up")
NOTIFY_EVENTS = ("both_down", "cci48_down", "cci288_down")  # +200 を上に抜けたものは通知しない（一覧には残す）


def _crossed(now, prev):
    """前の日は条件を満たさず、その日に満たした（=「抜けた」日）。最初の日は数えない。"""
    out = now & ~np.concatenate([[True], prev[:-1]])
    return out


def cci_events(x, level=CCI_ALERT_LEVEL):
    """日ごとの CCI ±level の「抜け」（bool 配列）。
    both_down: CCI48 と CCI288 の両方が −level 以下に「そろった」日（前の日はそろっていない）
    cci48_down / cci288_down: それぞれが −level を下に抜けた日
    both_up / cci48_up / cci288_up: 同じ規則で +level を上に抜けた日（通知はしない）"""
    S, L = x["cciS"], x["cciL"]
    with np.errstate(invalid="ignore"):
        sd, ld, su, lu = S <= -level, L <= -level, S >= level, L >= level
    return {
        "both_down": _crossed(sd & ld, sd & ld),
        "cci48_down": _crossed(sd, sd),
        "cci288_down": _crossed(ld, ld),
        "both_up": _crossed(su & lu, su & lu),
        "cci48_up": _crossed(su, su),
        "cci288_up": _crossed(lu, lu),
    }


# ── CCI ±200 の売買判定（2026-11 追加。既存の買い・売りの規則 signals / day_labels は変えない）──────────
# buy_cci200:  CCI48 と CCI288 の両方が −200 以下に「そろった」最初の日（cci_events の both_down と同じ日）
# sell_cci200: CCI48 と CCI288 の両方が +200 以上に「そろった」最初の日（cci_events の both_up と同じ日）
#              売り目安 = 利益確定・新しく買わない（空売りの根拠ではない）
CCI200_BUY = "buy_cci200"
CCI200_SELL = "sell_cci200"
CCI200_LABELS = (CCI200_BUY, CCI200_SELL)
CCI200_RECENT_BARS = 10  # 一覧・判断カードに「n 日前」として出す範囲（営業日）


def cci200_days(x, level=CCI_ALERT_LEVEL):
    """{buy_cci200: bool配列, sell_cci200: bool配列}（画面・通知・検証が同じこれを使う）。"""
    ev = cci_events(x, level)
    return {CCI200_BUY: ev["both_down"], CCI200_SELL: ev["both_up"]}


def cci200_recent(x, within=CCI200_RECENT_BARS):
    """直近 within 本の中で最後に出た CCI ±200 の判定 {"code", "bars_ago"}（0 = 最新日）。無ければ None。"""
    d = cci200_days(x)
    n = len(x["c"])
    best = None
    for code, arr in d.items():
        idx = np.flatnonzero(arr[max(0, n - within - 1) :])
        if len(idx):
            i = max(0, n - within - 1) + int(idx[-1])
            if best is None or i > best[1]:
                best = (code, i)
    return None if best is None else {"code": best[0], "bars_ago": n - 1 - best[1]}


def daily_event_counts(xs, key="both_down"):
    """{銘柄: (x, 日付)} → (日付, その抜けの件数, その日に日足がある銘柄の数)。0 件の日も含む。"""
    import collections

    cnt = collections.Counter()
    active = collections.Counter()
    for x, ds in xs.values():
        active.update(ds)
        for i in np.flatnonzero(cci_events(x)[key]):
            cnt[ds[i]] += 1
    dates = sorted(active)
    return dates, [cnt.get(d, 0) for d in dates], [active[d] for d in dates]


def spike_threshold(past_counts, q=SPIKE_Q, min_days=SPIKE_MIN_DAYS):
    """過去の日々の both_down 件数（0 の日も含む）の上位 (1-q)。履歴が短いときは None。"""
    v = np.asarray(past_counts, dtype=float)
    if len(v) < min_days:
        return None
    return float(np.quantile(v, q))


def spike_line(past_counts, n_universe, q=SPIKE_Q, min_days=SPIKE_MIN_DAYS, frac=SPIKE_MIN_FRAC):
    """「一斉に割れ」の線 = 過去1年の上位1% と その市場の銘柄数の 1.5% の大きい方。履歴が短いときは None。"""
    t = spike_threshold(past_counts, q, min_days)
    if t is None:
        return None
    return max(t, frac * n_universe)


def is_spike(count, line):
    """その日の件数が線を「超えた」（等しいだけでは違う）。線が無い（履歴が短い）日は判定しない。"""
    return line is not None and count > 0 and count > line


def spike_days(dates, counts, n_universe, lookback=SPIKE_LOOKBACK, q=SPIKE_Q, min_days=SPIKE_MIN_DAYS):
    """各日について、その日より前の lookback 日の件数とその日の銘柄数で線を引き、超えた日の集合。
    n_universe は日ごとの銘柄数（その日に日足がある銘柄の数）の配列。検証で「暴落の日」を除く用。"""
    out = set()
    for i, d in enumerate(dates):
        line = spike_line(counts[max(0, i - lookback) : i], n_universe[i], q, min_days)
        if is_spike(counts[i], line):
            out.add(d)
    return out
