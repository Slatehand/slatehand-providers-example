#!/usr/bin/env python3
"""把 fetch_progress.py 的进度行渲染成原地刷新的进度条（scripts/colab_node.sh 的显示过滤器）。

识别形如 ``HH:MM:SS <阶段> 12.3 / 40.2 GB · 77 MB/s · 剩余约 6 分 30 秒 · <文件>`` 的行，
在终端里用同一行重画进度条；其它行照常输出（先结束正在刷新的进度行）。
stdout 不是终端时原样透传。只用标准库。
"""

from __future__ import annotations

import re
import shutil
import sys

PROGRESS = re.compile(
    r"^\d\d:\d\d:\d\d (?P<label>.+?) (?P<done>[\d.]+) / (?P<total>[\d.]+) GB · "
    r"(?P<speed>\d+) MB/s · (?P<eta>[^·]+?)(?: · (?P<name>.*))?$"
)


def render(match: re.Match[str]) -> str:
    done, total = float(match["done"]), float(match["total"])
    ratio = min(1.0, done / total) if total else 1.0
    columns = shutil.get_terminal_size((100, 20)).columns
    text = (
        f" {ratio * 100:3.0f}%  {done:.1f} / {total:.1f} GB · {match['speed']} MB/s · "
        f"{match['eta'].strip()}"
    )
    width = max(10, min(30, columns - len(match["label"]) - len(text) - 6))
    filled = round(width * ratio)
    line = f"{match['label']} [{'█' * filled}{'░' * (width - filled)}]{text}"
    return line[: max(20, columns - 1)]


def main() -> int:
    tty = sys.stdout.isatty()
    in_place = False
    for line in iter(sys.stdin.readline, ""):
        line = line.rstrip("\n")
        match = PROGRESS.match(line) if tty else None
        if match:
            sys.stdout.write("\r\033[K" + render(match))
            in_place = True
            if match["eta"].strip() == "完成":
                sys.stdout.write("\n")
                in_place = False
        else:
            if in_place:
                sys.stdout.write("\n")
                in_place = False
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
    if in_place:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
