"""仕組み（About）タブと docs/about.json の中身を、コードと生成物から組み立てる（数字・規則を手で書かない）。

- 期間・しきい値・σ: screener.calc.ind.P と CCI ±200 の定数
- 判定の規則: ind.signals / long_oversold / day_labels と同じ形を、P の値から条件の並びとして出す
  （tests/test_about.py がこの並びを評価して ind.day_labels と一致することを確かめる）
- 総合スコア: screener.calc.composite.rules()
- 売買スコア（割安・質・チャート・減点・売りの点と5段階）: screener.calc.score.rules()（配分 W はそこ1か所）
- 更新の時刻: deploy.yml の cron（screener.calc.schedule。画面の「次回」と同じ関数）
- 検証の成績・「根拠が弱まっています」: docs/verify.json
- 取得元・件数・取得失敗・最終更新: docs/data.json の meta
説明の文（各タブの目的・指標の読み方・限界・免責）は画面の辞書（docs/assets/i18n/dict.js）だけにある。ここはコードだけ。
Mac mini 版（J-Quants 由来）は定義だけを出す。J-Quants 由来の数字・銘柄名・成績は読まないし出さない（ADR-002）。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import alerts
from .calc import assets, composite, fund_us, ind, schedule, score, value
from .japan import screen

SCHEMA = "about/1"
ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = ROOT / "docs" / "index.html"
REQUIRED_KEYS = (
    "schema",
    "generated_at",
    "commit",
    "params",
    "rules",
    "schedule",
    "verify",
    "meta",
    "tabs",
    "limitations",
    "disclaimer",
    "mac_mini",
)
LIMITATIONS = ("no_costs_taxes", "survivorship", "unofficial_sources", "close_only")
DISCLAIMER = "not_advice"
# 東証の市場区分（screener.japan.screen の値）→ コード（言葉は辞書の code.tse_market.*）
TSE_MARKET = {"プライム": "prime", "スタンダード": "standard", "グロース": "growth"}
_TAB = re.compile(r'<button[^>]*class="tab(?:\s+active)?"[^>]*data-tab="([^"]+)"')


# ── 判定の規則（P から組み立てる）──────────────────────────────────────
def _cci(n: int, op: str, v: float) -> dict[str, Any]:
    return {"ind": "cci", "n": n, "op": op, "v": v}


def _band(n: int, op: str, k: float) -> dict[str, Any]:
    """終値 op BB(n) の ±kσ（k は符号つき: −2 は −2σ）。"""
    return {"ind": "close_vs_bb", "n": n, "op": op, "k": k}


def chart_rules(p: dict[str, Any] = ind.P) -> list[dict[str, Any]]:
    """チャート判定（強い買い〜強い売り・長期の売られすぎ）の条件。all = すべて満たす。
    上から順に最初に当てはまったもの（強い方が先）。only_if_no_signal: 買い・売りのどちらも出ていない日だけ
    （ind.day_labels の規則）。tests/test_about.py がこの並びを評価して ind.day_labels と一致することを確かめる。"""
    buy = [_cci(p["cci_long"], ">", 0), _band(p["bb_short"], "<=", -p["k2"]), _cci(p["cci_short"], "<", -p["cci_th"])]
    sell = [_cci(p["cci_long"], "<", 0), _band(p["bb_short"], ">=", p["k2"]), _cci(p["cci_short"], ">", p["cci_th"])]
    return [
        {"code": ind.LABELS[2], "all": buy + [_band(p["bb_short"], "<=", -p["k3"])]},
        {"code": ind.LABELS[1], "all": buy},
        {"code": ind.LONG_OVERSOLD_LABEL, "all": [_band(p["bb_long"], "<=", -p["k2"])], "only_if_no_signal": True},
        {"code": ind.LABELS[-2], "all": sell + [_band(p["bb_short"], ">=", p["k3"])], "note": ind.SELL_NOTE},
        {"code": ind.LABELS[-1], "all": sell, "note": ind.SELL_NOTE},
    ]


def cci_event_rules() -> dict[str, Any]:
    return {
        "level": ind.CCI_ALERT_LEVEL,
        "periods": [ind.P["cci_short"], ind.P["cci_long"]],
        "events": list(ind.CCI_EVENTS),
        "notify_events": list(ind.NOTIFY_EVENTS),
        "spike": {
            "event": "both_down",
            "quantile": ind.SPIKE_Q,
            "lookback_days": ind.SPIKE_LOOKBACK,
            "min_days": ind.SPIKE_MIN_DAYS,
            "min_frac_of_universe": ind.SPIKE_MIN_FRAC,
        },
    }


# ── 生成物の要約 ───────────────────────────────────────────────────────
def verify_summary(v: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(v, dict):
        return {"available": False}
    markets = {}
    for k, m in (v.get("markets") or {}).items():
        full, rec = m.get("full") or {}, m.get("recent6m") or {}
        markets[k] = {
            "label": m.get("label") or k,
            "symbols": m.get("symbols"),
            "last_date": m.get("last_date"),
            "full": {"base": full.get("base"), "chart": full.get("chart"), "composite": full.get("composite")},
            "recent6m": {"since": rec.get("since"), "base": rec.get("base"), "chart": rec.get("chart")},
            "weakened": m.get("weakened"),
        }
    tiers = {}
    for k, t in (v.get("score_tiers") or {}).items():
        if isinstance(t, dict):
            tiers[k] = {
                "parts": t.get("parts"),
                "symbols": t.get("symbols"),
                "full": t.get("full"),
                "recent6m": t.get("recent6m"),
                "since": t.get("since"),
                "weakened": t.get("weakened"),
                "evidence_weak": t.get("evidence_weak"),
                "gate": t.get("gate"),
            }
    return {
        "available": True,
        "score_tiers": tiers,
        "generated_at": v.get("generated_at"),
        "as_of": v.get("as_of"),
        "method": v.get("method"),
        "weakened": v.get("weakened"),
        "weakened_items": v.get("weakened_items") or [],
        "markets": markets,
    }


def meta_summary(meta: dict[str, Any] | None, now: dt.datetime) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {"available": False}
    age = None
    try:
        age = round((now - dt.datetime.fromisoformat(str(meta.get("updated_at")))).total_seconds() / 3600, 1)
    except (TypeError, ValueError):
        age = None
    uni = {
        tab: {
            "count": r.get("count"),
            "target": r.get("target"),
            "source_mode": r.get("source_mode"),
            "universe_source": r.get("universe_source"),
            "fetch_failures": list(r.get("fetch_failures") or []),
        }
        for tab, r in (meta.get("universe") or {}).items()
        if isinstance(r, dict)
    }
    return {
        "available": True,
        "updated_at": meta.get("updated_at"),
        "age_hours_at_build": age,
        "stale_hours": meta.get("stale_hours"),
        "counts": meta.get("counts") or {},
        "universe": uni,
        "fallbacks": [
            {"source": f.get("source"), "reason": f.get("reason")}
            for f in (meta.get("fallbacks") or [])
            if isinstance(f, dict)
        ],
        "nan_report": meta.get("nan_report") or {},
    }


def schedule_summary(now: dt.datetime, deploy_yml: Path = schedule.DEPLOY_YML) -> dict[str, Any]:
    try:
        crons = schedule.workflow_crons(deploy_yml)
    except OSError:
        crons = {}
    nxt = {}
    for job in crons:
        t = schedule.next_job_run(job, now, deploy_yml)
        nxt[job] = t.isoformat() if t else None
    return {"source": ".github/workflows/deploy.yml", "tz": "UTC", "crons": crons, "next": nxt}


def mac_mini() -> dict[str, Any]:
    """Mac mini 版の仕組みと定義だけ（数字は定義の定数のみ。J-Quants 由来のデータは読まない）。"""
    return {
        "public": False,
        "theory_price": {"model": "residual_income", "params": dict(value.RI)},
        "overall": {
            "levels": ["A", "B", "C"],
            "a_requires": ["cheap_quintile", "buy_type"],
            "buy_type": list(ind.BUY_LABELS),
            "cheap_quintile": {
                "tse_markets": [TSE_MARKET.get(m, m) for m in screen.QUINTILE_MARKETS],
                "exclude_financial": True,
                "min_market_cap_oku_jpy": screen.QUINTILE_MIN_MCAP_OKU,
            },
        },
        "score": {"japan_parts": list(score.ALL_PARTS), "etf_source": "jquants_market_other_etf"},
        "cci_notify": {
            "markets": list(alerts.MARKETS),
            "spike_markets": [k for k, m in alerts.MARKETS.items() if m.get("spike")],
            "unverified_markets": [k for k, m in alerts.MARKETS.items() if not m.get("verified")],
            "events": list(ind.NOTIFY_EVENTS),
            "channel": "mac_local_notification",
        },
    }


def tabs(index_html: Path = INDEX_HTML) -> list[str]:
    try:
        return _TAB.findall(index_html.read_text(encoding="utf-8"))
    except OSError:
        return []


def commit_sha(root: Path = ROOT) -> dict[str, Any]:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return {"sha": sha, "source": "github_sha"}
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return {"sha": out.stdout.strip(), "source": "git"}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"sha": None, "source": None}


def build(
    meta: dict[str, Any] | None,
    verify: dict[str, Any] | None,
    now: dt.datetime | None = None,
    *,
    deploy_yml: Path = schedule.DEPLOY_YML,
    index_html: Path = INDEX_HTML,
    commit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(schedule.JST)
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "commit": commit if commit is not None else commit_sha(),
        "params": {
            "P": dict(ind.P),
            "min_bars": ind.MIN_BARS,
            "cci_alert_level": ind.CCI_ALERT_LEVEL,
            "composite_periods": composite.rules()["periods"],
        },
        "rules": {
            "chart": chart_rules(),
            "buy_type": list(ind.BUY_LABELS),
            "sell_type": list(ind.SELL_LABELS),
            "composite": composite.rules(),
            "cci_events": cci_event_rules(),
            "score": score.rules(),
            "cci200": {
                "labels": list(ind.CCI200_LABELS),
                "level": ind.CCI_ALERT_LEVEL,
                "periods": [ind.P["cci_short"], ind.P["cci_long"]],
                "events": {ind.CCI200_BUY: "both_down", ind.CCI200_SELL: "both_up"},
                "recent_bars": ind.CCI200_RECENT_BARS,
                "points": {m: dict(v) for m, v in score.CCI200.items()},
                "unverified_markets": list(score.CCI200_UNVERIFIED),
                "sell_note": ind.SELL_NOTE,
            },
            "etf": {"symbols": {s: k for s, (_n, k) in assets.ETFS.items()}, "kinds": list(assets.ETF_KINDS)},
            # 米国株の理論株価: 業種（SEC の SIC 上2桁）の黒字企業の PER の中央値 × EPS（calc.fund_us.relative_value）
            "us_fair_price": {
                "model": "sector_median_per",
                "group_min": fund_us.PER_BENCH["group_min"],
                "levels": list(fund_us.PER_LEVELS),
                "industry_code": "sec_sic",
            },
        },
        "schedule": schedule_summary(now, deploy_yml),
        "verify": verify_summary(verify),
        "meta": meta_summary(meta, now),
        "tabs": tabs(index_html),
        "limitations": list(LIMITATIONS),
        "disclaimer": DISCLAIMER,
        "mac_mini": mac_mini(),
    }
