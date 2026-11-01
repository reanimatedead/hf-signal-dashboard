"""生成物（docs/data.json など）が必要なテストの扱い（tests/conftest.py から使う）。

docs/data.json・docs/charts/・docs/macro_v2.json・docs/relations.json・docs/gamma.json は git に入れない生成物
（deploy.yml の full ジョブが生成してから pytest を回す）。オフライン（ci.yml・手元）では作れないので:
  - ファイルが無い → pytest.skip（理由を明記）
  - ただし環境変数 REQUIRE_DATA_JSON=1 のとき（deploy.yml full の「Data tests」ステップ）は pytest.fail
これらのテストには marker `needs_data_json` を付ける（`-m needs_data_json` で選べる）。
"""

from __future__ import annotations

import inspect
import os
import pathlib
import re
from collections.abc import Mapping

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"
# 生成物を読むテストがある（ファイル欠落を fail にしている）モジュール
MODULES = ("test_contract_v2.py", "test_payload_budget.py")
GENERATED = ("data.json", "macro_v2.json", "relations.json", "gamma.json")
_NAME_RE = re.compile(r'"(data\.json|macro_v2\.json|relations\.json|gamma\.json)"')


def required_files(func) -> list[str]:
    """テスト関数のソースから、必要な生成物（docs/ からの相対名）を拾う。"""
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):
        return []
    need = set(_NAME_RE.findall(src))
    if "charts/" in src or "_measure_initial(" in src:
        need.add("data.json")  # charts/ は data.json と同じ生成。初回ロードの計測は data.json
    return sorted(need)


def reason(missing: list[str]) -> str:
    names = "・".join(f"docs/{m}" for m in missing)
    return f"{names} がない（生成は deploy.yml の full ジョブで行う。オフラインでは作れない）"


def gate(missing: list[str], env: Mapping[str, str] = os.environ) -> None:
    """欠けていれば skip。REQUIRE_DATA_JSON=1 なら fail（スキップ禁止）。"""
    if not missing:
        return
    if env.get("REQUIRE_DATA_JSON") == "1":
        pytest.fail(reason(missing) + " — REQUIRE_DATA_JSON=1 のためスキップせず失敗にする", pytrace=False)
    pytest.skip(reason(missing))


def missing_files(names: list[str], docs: pathlib.Path = DOCS) -> list[str]:
    return [n for n in names if not (docs / n).exists()]
