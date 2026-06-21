"""H1 のみ実装 + 学習未追加の構造保証 (SPEC_H1 §0, §6).

- backtest/ 配下に h2..h10 ファイルが存在しない (多重検定・無限ビルド防止).
- 既存 test_no_learning_code が backtest/+collector/ を含めて grep してくれるので
  ここでは H1 専用の構造ガードのみ.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKTEST = ROOT / "backtest"


def test_only_h1_module_exists():
    forbidden = [f"h{n}.py" for n in range(2, 11)]
    found = [name for name in forbidden if (BACKTEST / name).exists()]
    assert not found, (
        f"only H1 must be implemented in Phase 1.9; found: {found}"
    )


def test_h1_module_present():
    p = BACKTEST / "h1.py"
    assert p.exists(), "backtest/h1.py must exist (Agent A/B)"


def test_h1_does_not_import_other_hypotheses():
    p = BACKTEST / "h1.py"
    text = p.read_text(encoding="utf-8")
    for n in range(2, 11):
        assert f"from .h{n}" not in text and f"import h{n}" not in text, (
            f"h1.py must not import h{n}"
        )


def test_h1_does_not_train():
    p = BACKTEST / "h1.py"
    text = p.read_text(encoding="utf-8")
    # Phase 2 着工しない構造保証 — safe markers 付きの行は許容 (Phase 2 / not implemented).
    forbidden = (".fit(", ".train(", "optimizer.", "learning_rate", "loss.backward")
    safe_markers = ("Phase 2", "not implemented", "noqa: learning")
    bad = []
    for ln, line in enumerate(text.splitlines(), 1):
        if any(m in line for m in safe_markers):
            continue
        if line.lstrip().startswith("#"):
            continue
        for f in forbidden:
            if f in line:
                bad.append(f"{ln}: {line.strip()}")
    assert not bad, "h1.py must not contain training calls:\n  " + "\n  ".join(bad[:5])
