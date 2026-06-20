"""Phase 1.8 担保: 学習 (Phase 2) のコードが backtest/ + collector/ に追加されていないこと.

SPEC_BACKTEST_LIVE §0 / §5. Phase 2 着工は今夜の測定結果を見てから判断する方針.
本テストは「実装が増えていない」ことを構造で守る.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARDED_DIRS = ["backtest", "collector"]

FORBIDDEN_IMPORTS = [
    r"\bimport\s+sklearn\b",
    r"\bfrom\s+sklearn\b",
    r"\bimport\s+torch\b",
    r"\bfrom\s+torch\b",
    r"\bimport\s+tensorflow\b",
    r"\bfrom\s+tensorflow\b",
    r"\bimport\s+keras\b",
    r"\bimport\s+xgboost\b",
    r"\bimport\s+lightgbm\b",
    r"\bimport\s+catboost\b",
]
FORBIDDEN_CALLS = [
    r"\.fit\s*\(",
    r"\.train\s*\(",
    r"\.compile\s*\(",
    r"loss\s*\.\s*backward",
    r"optimizer\s*\.",
    r"GradientTape",
    r"learning_rate",
    r"learn_rate",
]
SAFE_LINE_MARKERS = ("Phase 2", "not implemented", "noqa: learning")


def _iter_py_files():
    for d in GUARDED_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            yield p


def _is_safe_line(line: str) -> bool:
    return any(m in line for m in SAFE_LINE_MARKERS)


def test_no_forbidden_imports():
    bad = []
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8")
        for ln, line in enumerate(text.splitlines(), 1):
            if _is_safe_line(line):
                continue
            for pat in FORBIDDEN_IMPORTS:
                if re.search(pat, line):
                    bad.append(f"{p.relative_to(ROOT)}:{ln}: {line.strip()}")
    assert not bad, "learning imports must not appear in backtest/ or collector/:\n  " + "\n  ".join(bad[:10])


def test_no_training_calls():
    bad = []
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8")
        for ln, line in enumerate(text.splitlines(), 1):
            if _is_safe_line(line):
                continue
            # comments と docstring 部分の単純除外: 行頭 # は無視
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pat in FORBIDDEN_CALLS:
                if re.search(pat, line):
                    bad.append(f"{p.relative_to(ROOT)}:{ln}: {line.strip()}")
    assert not bad, "training calls must not appear in backtest/ or collector/:\n  " + "\n  ".join(bad[:10])


def test_no_model_files_added():
    # Phase 2 用のモデル保存ディレクトリが追加されていないこと
    for forbidden in ("backtest/models", "collector/models",
                      "backtest/training", "collector/training"):
        p = ROOT / forbidden
        assert not p.exists(), f"{forbidden}/ must not exist in Phase 1.8"
