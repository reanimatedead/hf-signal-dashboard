"""tests/test_payload_budget.py — 初回ロード容量の契約テスト（v7.1・2026-07-31）。

契約: 初回ロード（同一オリジンで boot 時に fetch されるもの＝ docs/index.html +
docs/data.json）の合計が **2 MiB を超えたら FAIL**。目標は 1 MiB 未満（目標未達は
FAIL にしない・実測値をテスト出力に必ず表示する）。

charts/{tab}.json は行展開時の遅延 fetch（index.html の loadCharts）であり初回ロードに
含まれない。ここが崩れて charts が data.json にインライン復帰すると初回ロードが
一気に 12 MB 級になるため、「markets 行に charts キーが無い」ことも契約に含める。

meta.payload_size = {initial_bytes, total_bytes} は生成時実測（fetch_signals.
record_payload_size）。correlations マージ（build_corr）後も再実測される。
検査対象は CI で generation 後に生成される docs/*.json（fail-closed・skip しない）。
"""
import json
import pathlib

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"

MIB = 1024 * 1024
INITIAL_HARD_LIMIT = 2 * MIB      # 契約: 超えたら FAIL
INITIAL_GOAL = 1 * MIB            # 目標: 未達でも FAIL しない（表示のみ）


def _initial_files():
    """初回ロードを構成するファイル（index.html + data.json）。"""
    return [DOCS / "index.html", DOCS / "data.json"]


def _measure_initial():
    sizes = {}
    for p in _initial_files():
        assert p.exists(), f"初回ロード構成ファイルが無い（生成が壊れた）: {p}"
        sizes[p.name] = p.stat().st_size
    return sizes


def test_initial_payload_under_2mib():
    """初回ロード合計 > 2 MiB で FAIL（契約）。1 MiB 目標は表示のみ。"""
    sizes = _measure_initial()
    total = sum(sizes.values())
    detail = ", ".join(f"{k}={v:,}B" for k, v in sizes.items())
    goal = "達成" if total < INITIAL_GOAL else "未達"
    print(f"\n  初回ロード実測: {total:,} B ({detail}) — 1MiB目標: {goal}")
    assert total <= INITIAL_HARD_LIMIT, (
        f"初回ロード {total:,} B > 契約上限 {INITIAL_HARD_LIMIT:,} B (2 MiB)。"
        f"内訳: {detail}。charts のインライン復帰か data.json の肥大を疑うこと。")


def test_charts_not_inlined_in_data_json():
    """markets の行に charts キーが残っていたら分割（v6.0 split）が壊れている。"""
    data = json.loads((DOCS / "data.json").read_text(encoding="utf-8"))
    bad = []
    for tab, rows in (data.get("markets") or {}).items():
        for r in rows:
            if isinstance(r, dict) and "charts" in r:
                bad.append(f"{tab}/{r.get('symbol', '?')}")
    assert not bad, (
        f"charts が data.json にインライン残留（遅延ロード契約違反・初回ロード肥大の芽）: "
        f"{bad[:10]}")


def test_meta_payload_size_recorded():
    """meta.payload_size = {initial_bytes, total_bytes} が生成時実測で記録されている。"""
    data = json.loads((DOCS / "data.json").read_text(encoding="utf-8"))
    ps = (data.get("meta") or {}).get("payload_size")
    assert isinstance(ps, dict), "meta.payload_size が無い（record_payload_size 未通過）"
    for k in ("initial_bytes", "total_bytes"):
        assert isinstance(ps.get(k), int) and ps[k] > 0, f"payload_size.{k} が不正: {ps.get(k)!r}"
    assert ps["initial_bytes"] <= ps["total_bytes"], (
        f"initial({ps['initial_bytes']:,}) > total({ps['total_bytes']:,}) はあり得ない")
    # 記録値も契約に従う（実測テストと二重化: 記録の捏造・陳腐化の両方を検知）。
    assert ps["initial_bytes"] <= INITIAL_HARD_LIMIT, (
        f"記録された initial_bytes {ps['initial_bytes']:,} B > 2 MiB")


def test_meta_payload_size_matches_actual():
    """記録値が実測とかけ離れていないこと（±5%）。

    生成→correlations マージの各段で再実測される設計なので通常は一致する。
    ローカルで index.html だけ編集した直後などの軽微なズレは許容（5%）し、
    「記録だけ更新されず実体と乖離」した状態を検知する。
    """
    data = json.loads((DOCS / "data.json").read_text(encoding="utf-8"))
    ps = (data.get("meta") or {}).get("payload_size") or {}
    recorded = ps.get("initial_bytes")
    assert isinstance(recorded, int), "meta.payload_size.initial_bytes が無い"
    actual = sum(_measure_initial().values())
    drift = abs(actual - recorded) / max(actual, 1)
    print(f"\n  payload_size 記録={recorded:,}B 実測={actual:,}B 乖離={drift * 100:.2f}%")
    assert drift <= 0.05, (
        f"meta.payload_size.initial_bytes={recorded:,} B が実測 {actual:,} B と "
        f"{drift * 100:.1f}% 乖離（>5%）。生成後に record_payload_size を通していない疑い。")
