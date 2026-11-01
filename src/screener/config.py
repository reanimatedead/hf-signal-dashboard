"""設定の読み込みとデータ置き場の決定。

- 設定ファイル: 環境変数 SCREENER_CONFIG → ~/.config/screener/config.toml（無ければ既定値だけ）。
- データ置き場: 既定 ~/screener-data。リポジトリの中は既定にしない（J-Quants 由来のデータを
  誤ってコミットしないため。ADR-002）。設定でリポジトリの中を指したら止める。
- リポジトリ: 既定 ~/hf-signal-dashboard（Mac mini の clone。daily.py はここで git pull --ff-only する）。

config.toml の例（install_macmini.sh が作る）::

    [paths]
    data_dir = "~/screener-data"
    repo_dir = "~/hf-signal-dashboard"
    [ntfy]
    topic = "screener-<ランダム32桁>"
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JST = dt.timezone(dt.timedelta(hours=9), "JST")
PACKAGE_REPO = Path(__file__).resolve().parents[2]  # このファイルがあるリポジトリ（src/screener/config.py の2つ上）

DEFAULTS: dict[str, dict[str, Any]] = {
    "paths": {"data_dir": "~/screener-data", "repo_dir": "~/hf-signal-dashboard"},
    "jquants": {"keychain_service": "screener-jquants", "rate_per_min": 50, "history_years": 5},
    "ntfy": {"server": "https://ntfy.sh", "topic": ""},
    "edgar": {"user_agent": "screener research (local)"},
}


def default_config_path() -> Path:
    env = os.environ.get("SCREENER_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "screener" / "config.toml"


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@dataclass
class Config:
    data_dir: Path
    repo_dir: Path
    raw: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # データ置き場の下の決まった場所
    @property
    def jp_dir(self) -> Path:
        return self.data_dir / "japan"

    @property
    def us_dir(self) -> Path:
        return self.data_dir / "us"

    @property
    def out_dir(self) -> Path:
        return self.data_dir / "out"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def jp(self, *parts: str) -> Path:
        return self.jp_dir.joinpath(*parts)

    def us(self, *parts: str) -> Path:
        return self.us_dir.joinpath(*parts)

    def out(self, *parts: str) -> Path:
        return self.out_dir.joinpath(*parts)

    @property
    def ntfy_topic(self) -> str:
        return str(self.get("ntfy.topic", "") or "")

    @property
    def ntfy_server(self) -> str:
        return str(self.get("ntfy.server", "https://ntfy.sh")).rstrip("/")

    def ensure_dirs(self) -> None:
        for d in (self.out_dir, self.log_dir, self.jp("daily"), self.jp("fins"), self.us("px"), self.us("facts")):
            d.mkdir(parents=True, exist_ok=True)


def load(path: str | Path | None = None) -> Config:
    p = Path(path).expanduser() if path else default_config_path()
    file_raw: dict[str, Any] = {}
    if p.exists():
        with open(p, "rb") as fh:
            file_raw = tomllib.load(fh)
    raw = {k: {**v, **(file_raw.get(k) or {})} for k, v in DEFAULTS.items()}
    for k, v in file_raw.items():
        raw.setdefault(k, v)
    data_dir = Path(os.path.expanduser(str(raw["paths"]["data_dir"])))
    repo_dir = Path(os.path.expanduser(str(raw["paths"]["repo_dir"])))
    if not data_dir.is_absolute():
        raise ValueError(f"data_dir は絶対パス（~ 可）で書いてください: {data_dir}")
    for repo in {PACKAGE_REPO, repo_dir}:
        if _inside(data_dir, repo):
            raise ValueError(
                f"data_dir がリポジトリの中です（{data_dir}）。J-Quants 由来のデータはリポジトリの外に置く"
            )
    return Config(data_dir=data_dir, repo_dir=repo_dir, raw=raw, path=p if p.exists() else None)


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


def main(argv: list[str]) -> int:
    """python -m screener.config get ntfy.topic / path data_dir（シェルから値を読む）。"""
    cfg = load()
    if len(argv) >= 2 and argv[0] == "get":
        print(cfg.get(argv[1], ""))
        return 0
    if len(argv) >= 2 and argv[0] == "path":
        print(getattr(cfg, argv[1]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
