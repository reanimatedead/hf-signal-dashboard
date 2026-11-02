"""GitHub Actions の cron（UTC・5項目）から次の実行時刻を出す。表示用の「次回」を固定の文字で書かないため。

実行時刻の正本は .github/workflows/deploy.yml の schedule だけ。各行の末尾コメントの先頭の語がジョブ名:
    - cron: "30 22 * * *"     # full — 07:30 JST daily
ここはその行を読んで計算するだけ（時刻をここに書かない）。外部のライブラリは使わない。
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

UTC = dt.UTC
JST = dt.timezone(dt.timedelta(hours=9))
DEPLOY_YML = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy.yml"
_LINE = re.compile(r'^\s*-\s*cron:\s*"([^"]+)"\s*#\s*([A-Za-z_]+)')
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))  # 分 時 日 月 曜日(0=日)


def _field(text: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            a, b = (int(v) for v in base.split("-"))
        else:
            a = b = int(base)
        if step and base != "*" and "-" not in base:
            b = hi
        vals = set(range(a, b + 1, int(step) if step else 1))
        if hi == 6:
            vals = {0 if v == 7 else v for v in vals}  # 7 も日曜
        if not vals or min(vals) < lo or max(vals) > hi:
            raise ValueError(f"cron の値が範囲外: {text}")
        out |= vals
    return out


def parse(expr: str) -> tuple[set[int], ...]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron は5項目: {expr!r}")
    return tuple(_field(p, lo, hi) for p, (lo, hi) in zip(parts, _RANGES, strict=True))


def matches(expr: str, t: dt.datetime) -> bool:
    """t（UTC）がこの cron の発火時刻か。日と曜日が両方指定のときは どちらか（cron の規則）。"""
    mi, ho, dom, mon, dow = parse(expr)
    f = expr.split()
    t = t.astimezone(UTC)
    wd = (t.weekday() + 1) % 7  # Python: 月=0 → cron: 日=0
    day_ok = (t.day in dom or wd in dow) if (f[2] != "*" and f[4] != "*") else (t.day in dom and wd in dow)
    return t.minute in mi and t.hour in ho and t.month in mon and day_ok


def next_after(expr: str, now: dt.datetime) -> dt.datetime:
    """now より後で最初の発火時刻（UTC）。"""
    t = now.astimezone(UTC).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if matches(expr, t):
            return t
        t += dt.timedelta(minutes=1)
    raise ValueError(f"1年以内に発火しない cron: {expr!r}")


def workflow_crons(path: Path = DEPLOY_YML) -> dict[str, list[str]]:
    """{ジョブ名: [cron, ...]}（deploy.yml の schedule の行から）。"""
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m:
            out.setdefault(m.group(2), []).append(m.group(1))
    return out


def next_job_run(job: str, now: dt.datetime, path: Path = DEPLOY_YML) -> dt.datetime | None:
    """そのジョブの次の実行（JST）。deploy.yml が読めない・ジョブが無いときは None（画面は「—」）。"""
    try:
        crons = workflow_crons(path).get(job) or []
    except OSError:
        return None
    if not crons:
        return None
    return min(next_after(c, now) for c in crons).astimezone(JST)
