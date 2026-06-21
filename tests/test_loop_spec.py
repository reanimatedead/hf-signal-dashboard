"""Agent 1 — 仕様: 5 仮説登録 + 理論根拠 + 指数限定ユニバース (SPEC_LOOP §0, §2)."""
import pytest

reg = pytest.importorskip(
    "loop.registry",
    reason="Agent 1 未実装。loop/registry.py を作ると緑になる。",
)


def test_exactly_five_hypotheses_registered():
    names = [h["name"] for h in reg.REGISTRY]
    assert sorted(names) == sorted(["288_cross", "288_slope", "288_band",
                                      "index_tsmom", "regime_tsmom"]), names


def test_each_hypothesis_has_theoretical_basis():
    for h in reg.REGISTRY:
        rationale = h.get("rationale", "")
        assert isinstance(rationale, str) and len(rationale) >= 30, (
            f"{h['name']}: 理論根拠は必須 (>=30 chars), got {rationale!r}"
        )
        # 「why this works」の一言が無い仮説は登録不可
        assert any(tok in rationale.lower() for tok in
                   ("momentum", "mean", "trend", "rebal", "regime",
                    "literature", "research", "ファマ", "リバランス", "節目",
                    "trend persistence", "tactical")), (
            f"{h['name']}: 理論根拠に金融研究の参照が必要: {rationale}"
        )


def test_each_hypothesis_has_predict_function():
    for h in reg.REGISTRY:
        assert callable(h.get("predict")), f"{h['name']}: predict() callable required"


def test_each_hypothesis_params_are_fixed():
    for h in reg.REGISTRY:
        # params 辞書はあって良いが、各仮説で 1 つの dict 固定 (リストではなくスカラー)
        params = h.get("params", {})
        for k, v in params.items():
            assert not isinstance(v, (list, tuple, set)), (
                f"{h['name']}: param {k} must be scalar (no auto search range): {v}"
            )


def test_allowed_symbols_indices_and_fx_only():
    allowed = reg.ALLOWED_SYMBOLS
    assert isinstance(allowed, (set, frozenset))
    for s in allowed:
        is_index = s.startswith("^")
        is_fx = s.endswith("=X")
        assert is_index or is_fx, f"non-index/non-FX symbol leaked: {s}"


def test_individual_stocks_not_in_universe():
    # AAPL, MSFT, 7203.T などの個別株 ticker パターンが allowed に混入していないこと
    bad = [s for s in reg.ALLOWED_SYMBOLS
            if (("." in s and not s.endswith("=X")) or (not s.startswith("^") and not s.endswith("=X")))]
    assert not bad, f"individual stocks leaked into ALLOWED_SYMBOLS: {bad}"


def test_holdout_constant_is_two_years_back():
    import datetime
    from loop import holdout
    today = datetime.date.today()
    expected_year = today.year - 2
    assert holdout.HOLDOUT_START is not None
    assert holdout.HOLDOUT_START.startswith(f"{expected_year}-")
