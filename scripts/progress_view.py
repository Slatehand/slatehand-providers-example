#!/usr/bin/env python3
"""scripts/colab_node.sh 的显示过滤器：进度条与状态面板。只用标准库。

默认模式：识别 fetch_progress.py 形如
``HH:MM:SS <阶段> 12.3 / 40.2 GB · 77 MB/s · 剩余约 6 分 30 秒 · <文件>`` 的行，在终端里用同一行
重画进度条；其它行照常输出。stdout 不是终端时原样透传。

``--panel <标题>``：读入若干行「标签<TAB>内容」，清屏后排版成状态面板（内容是进度行时画成进度条）。

行宽按终端显示宽度计算（中日韩字符占两格），超出终端宽度的行截断，避免换行后 ``\\r`` 无法回到行首。
"""

from __future__ import annotations

import re
import shutil
import sys
import time
import unicodedata

PROGRESS = re.compile(
    r"^\d\d:\d\d:\d\d (?P<label>.+?) (?P<done>[\d.]+) / (?P<total>[\d.]+) GB · "
    r"(?P<speed>\d+) MB/s · (?P<eta>[^·]+?)(?: · (?P<name>.*))?$"
)


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def fit(text: str, columns: int) -> str:
    """按显示宽度截断到 columns 以内。"""
    used, kept = 0, []
    for char in text:
        used += 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used > columns:
            break
        kept.append(char)
    return "".join(kept)


def columns() -> int:
    return shutil.get_terminal_size((100, 20)).columns


def bar(match: re.Match[str], prefix: str, room: int) -> str:
    done, total = float(match["done"]), float(match["total"])
    ratio = min(1.0, done / total) if total else 1.0
    text = (
        f" {ratio * 100:3.0f}%  {done:.1f} / {total:.1f} GB · {match['speed']} MB/s · "
        f"{match['eta'].strip()}"
    )
    size = max(8, min(30, room - width(prefix) - width(text) - 3))
    filled = round(size * ratio)
    return f"{prefix}[{'█' * filled}{'░' * (size - filled)}]{text}"


def stream() -> int:
    tty = sys.stdout.isatty()
    in_place = False
    for line in iter(sys.stdin.readline, ""):
        line = line.rstrip("\n")
        match = PROGRESS.match(line) if tty else None
        if match:
            room = columns() - 1
            sys.stdout.write("\r\033[K" + fit(bar(match, match["label"] + " ", room), room))
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


def panel(title: str) -> int:
    room = columns() - 1
    rows = [line.rstrip("\n").split("\t", 1) for line in sys.stdin if "\t" in line]
    label_width = max((width(label) for label, _ in rows), default=0) + 2
    out = [fit(f"{title} · {time.strftime('%H:%M:%S')}", room), ""]
    for label, text in rows:
        prefix = label + " " * (label_width - width(label))
        match = PROGRESS.match(text)
        stage = match["label"].replace(" 后台下载", "").replace(" 前台下载", "") if match else ""
        line = bar(match, prefix + stage + " ", room) if match else prefix + text
        out.append(fit(line, room))
    out += ["", fit("Ctrl-C 退出查看（不影响 Colab）。回收 VM：scripts/colab_node.sh down", room)]
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[J")
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--panel":
        return panel(sys.argv[2])
    return stream()


if __name__ == "__main__":
    sys.exit(main())
