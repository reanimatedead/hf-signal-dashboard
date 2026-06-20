"""notify.config — config.local の安全な読込み.

公開リポに値を残さないため、`config.local` は .gitignore 済 (Phase 1 で導入).
本モジュールは:
  * 不在時 / JSON 不正 / 読込みエラー で None を返す (例外を外に漏らさない).
  * 例外で落とさないことが SPEC §5.3 の契約.

呼び出し: `notify.config.load()` → dict or None
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Optional, Dict, Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PATHS = [
    ROOT / "config.local",
    ROOT / "config.local.json",
]


def load() -> Optional[Dict[str, Any]]:
    """Return config dict or None when the file is absent / invalid."""
    for p in DEFAULT_PATHS:
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return None
    return None


def is_notify_enabled(cfg: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(cfg, dict):
        return False
    return bool(cfg.get("notify_enabled")) and bool(cfg.get("ntfy_topic"))


def ntfy_topic(cfg: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(cfg, dict):
        return None
    t = cfg.get("ntfy_topic")
    return t if isinstance(t, str) and t.strip() else None


def mac_notify_sound(cfg: Optional[Dict[str, Any]], default: str = "Glass") -> str:
    if isinstance(cfg, dict) and cfg.get("mac_notify_sound"):
        return str(cfg["mac_notify_sound"])
    return default
