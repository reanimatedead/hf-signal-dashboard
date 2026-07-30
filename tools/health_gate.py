#!/usr/bin/env python3
"""tools/health_gate.py — deploy health gate.

Reads a data.json, evaluates FAIL/WARN checks, writes <dir>/health.json, prints a
summary, and exits 1 on any FAIL (0 on PASS/WARN). Used by .github/workflows/
deploy.yml between generation and upload so a broken/stale payload never
overwrites the live site (deploy-pages keeps the previous good deploy on failure).

Runnable standalone:
    PYTHONPATH=. python3 tools/health_gate.py [path/to/data.json]

Checks (A-Ⅰ-2):
  FAIL (exit 1 if any):
    - us_rates lag  > 3d
    - jgb lag       > 5d
    - fred_daily lag> 4d
    - equity 4-tab ready rate < 90%
    - data.json missing any of markets / summary / money_flow / survival_loop
    - relations の 3 地域いずれかが series 200 件未満   (Task 5-2)
    - correlations.align が inner_join でない            (Task 5-2)
    - macro_v2 の fisher.ok が False                     (Task 5-2)
  WARN (exit 0, logged):
    - boj_assets lag > 45d
    - imm lag        > 12d
    - gamma が data_status error / unavailable           (Task 5-2)
    - macro_v2 の error 系列が 3 件以上                    (Task 5-2)
    - relations の d20_z が |値| > 2（速度警告）          (Task 5-2)
    - decisions.jsonl の review_date が到来               (Task 5-3)

Freshness reference — honest-limitation note: the current data.json schema stores
NO per-observation date on the US-rate / JGB / FRED-daily rows (they are live /
auto series refetched every pipeline run). us_rates/jgb/fred_daily lag is therefore
measured against meta.updated_at (the pipeline run date), i.e. it catches a stale
DEPLOY, not a stale individual observation. boj_assets and imm DO carry real dates
and are measured directly. Once the macro layer (macro_v2.json / relations.json)
lands with dated series, tighten these to true per-observation dates.
"""
import json
import os
import sys
from datetime import datetime, timezone

DATA = sys.argv[1] if len(sys.argv) > 1 else "docs/data.json"
DOCS_DIR = os.path.dirname(DATA) or "."
OUT = os.path.join(DOCS_DIR, "health.json")


def _load_sibling(name):
    """docs/<name> を読む。欠落/破損は None（呼び出し側で unknown/warn 扱い）。"""
    try:
        with open(os.path.join(DOCS_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

FAIL_LAG = {"us_rates": 3, "jgb": 5, "fred_daily": 4}
WARN_LAG = {"boj_assets": 45, "imm": 12}
READY_MIN_PCT = 90.0
REQUIRED_TOP = ("markets", "summary", "money_flow", "survival_loop")
EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")


def _today():
    return datetime.now(timezone.utc).date()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def _lag(dt):
    return None if dt is None else max(0, (_today() - dt).days)


def evaluate(d):
    checks = []
    fails = []
    warns = []

    # gate: "deploy" = 配信可否を止める（payload構造/被覆/鮮度の破損）。
    #       "data"   = そのデータ領域(domain)の品質のみ。デプロイは止めない（該当タブを
    #                  警告表示し、コード/UI/他タブは通常反映）。2026-07-30 分離。
    def add(name, level, status, detail, gate="deploy", domain=None):
        checks.append({"name": name, "level": level, "status": status,
                       "detail": detail, "gate": gate, "domain": domain})
        if status == "fail":
            fails.append(name)
        elif status in ("warn", "unknown"):
            warns.append(name)

    # 1) structural completeness (FAIL)
    missing = [k for k in REQUIRED_TOP if k not in d]
    if missing:
        add("structure", "FAIL", "fail", f"missing top-level keys: {missing}")
    else:
        add("structure", "FAIL", "pass",
            "markets/summary/money_flow/survival_loop present")

    # 2) equity chart coverage (FAIL if < 90%)
    tot = rdy = 0
    per = {}
    for tab in EQUITY_TABS:
        rows = (d.get("markets") or {}).get(tab, [])
        r = sum(1 for x in rows if x.get("chart_status") == "ready")
        per[tab] = f"{r}/{len(rows)}"
        tot += len(rows)
        rdy += r
    pct = (rdy / tot * 100) if tot else 0.0
    if tot and pct < READY_MIN_PCT:
        add("equity_ready", "FAIL", "fail", f"{pct:.1f}% < {READY_MIN_PCT}% {per}")
    else:
        add("equity_ready", "FAIL", "pass", f"{pct:.1f}% >= {READY_MIN_PCT}% {per}")

    # freshness reference for live/auto-refetched series = pipeline run date.
    run_dt = _parse_date((d.get("meta") or {}).get("updated_at"))
    run_lag = _lag(run_dt)

    # 3) us_rates / jgb / fred_daily lag (FAIL) — proxied by pipeline run date.
    for name, thr in FAIL_LAG.items():
        if run_lag is None:
            add(name, "FAIL", "unknown", "meta.updated_at missing/unparseable")
        elif run_lag > thr:
            add(name, "FAIL", "fail",
                f"pipeline lag {run_lag}d > {thr}d (ref: meta.updated_at)")
        else:
            add(name, "FAIL", "pass",
                f"pipeline lag {run_lag}d <= {thr}d (ref: meta.updated_at)")

    # 4) boj_assets lag (WARN) — real per-series date/lag.
    boj = ((d.get("money_flow") or {}).get("jp") or {}).get("cb_assets") or {}
    boj_lag = boj.get("lag_days")
    if boj_lag is None:
        boj_lag = _lag(_parse_date(boj.get("as_of")))
    if boj_lag is None:
        add("boj_assets", "WARN", "unknown", "no cb_assets date")
    elif boj_lag > WARN_LAG["boj_assets"]:
        add("boj_assets", "WARN", "warn", f"lag {boj_lag}d > {WARN_LAG['boj_assets']}d")
    else:
        add("boj_assets", "WARN", "pass", f"lag {boj_lag}d <= {WARN_LAG['boj_assets']}d")

    # 5) imm lag (WARN) — CFTC COT weekly; real per-row date.
    imm_dates = [x for x in
                 (_parse_date(r.get("date")) for r in (d.get("markets") or {}).get("imm", []))
                 if x]
    imm_lag = _lag(max(imm_dates)) if imm_dates else None
    if imm_lag is None:
        add("imm", "WARN", "unknown", "no imm date")
    elif imm_lag > WARN_LAG["imm"]:
        add("imm", "WARN", "warn", f"lag {imm_lag}d > {WARN_LAG['imm']}d")
    else:
        add("imm", "WARN", "pass", f"lag {imm_lag}d <= {WARN_LAG['imm']}d")

    # ── Task 5-2: v2 検証層の拡張チェック ──────────────────────────────
    # relations.json / macro_v2.json / gamma.json は data.json の兄弟生成物。
    rel = _load_sibling("relations.json")
    mac = _load_sibling("macro_v2.json")
    gam = _load_sibling("gamma.json")

    # FAIL: relations の 3 地域いずれかが series 200 件未満
    if rel is None:
        add("relations_series", "FAIL", "unknown", "relations.json 読み込み不可")
    else:
        regions = rel.get("regions") or {}
        short = {r: len((regions.get(r) or {}).get("series") or [])
                 for r in ("us", "eu", "jp")
                 if len((regions.get(r) or {}).get("series") or []) < 200}
        if short:
            add("relations_series", "FAIL", "fail",
                f"series < 200 の地域: {short}", gate="data", domain="relations")
        else:
            add("relations_series", "FAIL", "pass",
                "us/eu/jp series >= 200", gate="data", domain="relations")

    # FAIL: correlations.align が inner_join でない
    corr_align = (d.get("correlations") or {}).get("align")
    if corr_align is None:
        add("corr_align", "FAIL", "unknown", "correlations.align 欠落",
            gate="data", domain="correlations")
    elif corr_align != "inner_join":
        add("corr_align", "FAIL", "fail",
            f"correlations.align='{corr_align}' (inner_join でない)",
            gate="data", domain="correlations")
    else:
        add("corr_align", "FAIL", "pass", "correlations.align=inner_join",
            gate="data", domain="correlations")

    # data_gate: macro_v2 の fisher.ok が False（該当タブのみ警告・デプロイは止めない）
    if mac is None:
        add("macro_fisher", "FAIL", "unknown", "macro_v2.json 読み込み不可",
            gate="data", domain="macro")
    else:
        fisher = (mac.get("identities") or {}).get("fisher") or {}
        if fisher.get("ok") is not True:
            add("macro_fisher", "FAIL", "fail",
                f"fisher.ok={fisher.get('ok')} gap={fisher.get('gap')}",
                gate="data", domain="macro")
        else:
            add("macro_fisher", "FAIL", "pass",
                f"fisher.ok gap={fisher.get('gap')}", gate="data", domain="macro")

    # WARN: gamma が data_status: error または unavailable
    if gam is None:
        add("gamma_status", "WARN", "unknown", "gamma.json 読み込み不可")
    else:
        gs = gam.get("data_status")
        if gs in ("error", "unavailable"):
            add("gamma_status", "WARN", "warn", f"gamma.data_status={gs}")
        else:
            add("gamma_status", "WARN", "pass", f"gamma.data_status={gs}")

    # WARN: macro_v2 の系列のうち error のものが 3 件以上
    if mac is not None:
        series = mac.get("series") or {}
        errs = [k for k, v in series.items() if v.get("data_status") == "error"]
        if len(errs) >= 3:
            add("macro_series_errors", "WARN", "warn",
                f"error 系列 {len(errs)} 件: {errs}")
        else:
            add("macro_series_errors", "WARN", "pass",
                f"error 系列 {len(errs)} 件 (< 3)")

    # WARN: relations の d20_z が絶対値 2 を超える（速度警告）
    if rel is not None:
        ctx = (rel.get("balance") or {}).get("context") or {}
        hot = {}
        for k, v in ctx.items():
            dz = (v or {}).get("d20_z")
            if isinstance(dz, (int, float)) and abs(dz) > 2:
                hot[k] = dz
        if hot:
            add("relations_speed", "WARN", "warn",
                f"|d20_z| > 2 の系列: {hot}")
        else:
            add("relations_speed", "WARN", "pass", "|d20_z| <= 2")

    # WARN: decisions.jsonl の review_date が到来（見直し期限）— Task 5-3
    dec_path = os.path.join(DOCS_DIR, "decisions.jsonl")
    if os.path.exists(dec_path):
        due = []
        try:
            with open(dec_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    rv = _parse_date(rec.get("review_date"))
                    if rv is not None and rv <= _today():
                        due.append(rec.get("review_date"))
        except Exception as e:
            add("decisions_review", "WARN", "unknown", f"decisions.jsonl 解析失敗: {e}")
        else:
            if due:
                add("decisions_review", "WARN", "warn",
                    f"review_date 到来 {len(due)} 件: {due} → 判断を見直せ")
            else:
                add("decisions_review", "WARN", "pass", "見直し期限なし")

    # equity fetch heal（バッチ部分劣化の個別再取得）統計を surface — Task Q4。
    # 発動頻度を health.json に恒久記録（CI ログは失効する）。still_degraded>0 は WARN。
    heal = (d.get("meta") or {}).get("equity_fetch_heal") or {}
    if heal:
        deg = heal.get("degraded", 0)
        rec = heal.get("recovered", 0)
        still = heal.get("still_degraded", 0)
        detail = (f"degraded={deg} recovered={rec} still_degraded={still} "
                  f"symbols_degraded={heal.get('symbols_degraded', [])}")
        if still > 0:
            add("equity_fetch_heal", "WARN", "warn",
                detail + " (再取得後も劣化が残存)")
        else:
            add("equity_fetch_heal", "WARN", "pass", detail)

    # ── ゲート分離 (2026-07-30) ─────────────────────────────────────────
    # deploy_gate だけが exit code を左右する。data_gate の fail は該当 domain を
    # 「degraded」にするだけで配信は止めない（無関係なコード/UI/他タブは即反映）。
    real_fails = [c["name"] for c in checks if c["status"] == "fail"]
    real_warns = [c["name"] for c in checks if c["status"] in ("warn", "unknown")]
    deploy_fails = [c["name"] for c in checks
                    if c["status"] == "fail" and c.get("gate", "deploy") == "deploy"]
    data_fails = [c["name"] for c in checks
                  if c["status"] == "fail" and c.get("gate") == "data"]
    degraded_domains = sorted({c.get("domain") for c in checks
                               if c["status"] == "fail" and c.get("gate") == "data"
                               and c.get("domain")})
    deploy_status = "FAIL" if deploy_fails else "PASS"
    data_status = "DEGRADED" if data_fails else "OK"
    # 後方互換: 従来の "status" は残す（deploy_gate に連動）。judgment ロジックは不変。
    status = deploy_status if deploy_fails else ("WARN" if real_warns or data_fails else "PASS")
    return {
        "status": status,
        "deploy_gate": {"status": deploy_status, "fails": deploy_fails},
        "data_gate": {"status": data_status, "fails": data_fails,
                      "degraded_domains": degraded_domains},
        "generated_from": DATA,
        "as_of_utc": _today().isoformat(),
        "fails": real_fails,
        "warns": real_warns,
        "checks": checks,
        "notes": [
            "deploy_gate だけが exit code を決める。data_gate の fail(fisher/relations/corr)は "
            "該当 domain を degraded にするのみで配信は止めない（UI が該当タブを警告表示）。",
            "us_rates/jgb/fred_daily lag is proxied by meta.updated_at (pipeline run date).",
            "boj_assets and imm use real per-series dates.",
        ],
    }


def main():
    try:
        d = json.load(open(DATA, encoding="utf-8"))
    except Exception as e:
        rep = {"status": "FAIL", "error": f"cannot read {DATA}: {e}",
               "fails": ["read"], "warns": [], "checks": []}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(json.dumps(rep, ensure_ascii=False))
        return 1
    rep = evaluate(d)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    dg = rep.get("deploy_gate", {})
    da = rep.get("data_gate", {})
    print(f"\nhealth_gate: deploy_gate={dg.get('status')} (fails={dg.get('fails')}) | "
          f"data_gate={da.get('status')} (degraded={da.get('degraded_domains')}) | "
          f"warns={rep['warns']}  → {OUT}")
    # exit code は deploy_gate だけで決める。data_gate の degraded は配信を止めない。
    return 1 if dg.get("status") == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
