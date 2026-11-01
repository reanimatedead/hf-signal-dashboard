# _to_delete/

削除は本人の承認後。

ここにあるものは今の方針（PLAN2）では使わない。消さずに移しただけ（`git mv`）。

- `workflows/verify_monthly.yml` — 毎月の再検証（作らないもの）
- `workflows/deps_latest.yml` — 毎月の最新版での依存テスト（作らないもの）
- `workflows/marketcalc.yml` — 計算式のテスト。`.github/workflows/ci.yml` に統合した
- `workflows/corr.yml` — 廃止済み（deploy.yml の corr_refresh に統合）。手動実行で docs/data.json を
  コミットしようとする唯一の workflow だったため移した（data.json はコミットしない・ADR-003）
- `tests/test_collect_workflow.py` — workflow ファイルの形を調べるテスト（ci_only）。方針により廃止
- `requirements.lock` / `requirements.txt` — 依存の指定は uv.lock（pyproject.toml）の 1 か所にした。全 workflow は `uv sync --locked`
