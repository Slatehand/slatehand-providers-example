"""带进度的复制（Colab 从 Drive 缓存权重用）：以 GB 显示已复制/总量、速度与预计剩余时间。

用法：copy_progress.py <源文件或目录> <目标> --label <阶段名> [--done 已完成字节] [--total 总字节]

``--done``/``--total`` 让同一阶段的多个文件共用一条总进度。终端里原地刷新同一行；输出到日志或
管道时每 10 秒追加一行（``SLATEHAND_PROGRESS_INTERVAL`` 可改），便于 ``tail`` 查看。
目录按文件逐个复制。

Drive 挂载对单个顺序读取限速明显，因此每个文件切成 64 MB 的块，由多个线程（默认 8，
``SLATEHAND_COPY_THREADS`` 可改）以 pread/pwrite 并行读写各自的块；目标文件先按源大小预分配。
"""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import sys
import threading
import time
from collections import deque
from pathlib import Path

CHUNK = 16 * 1024 * 1024
PIECE = 64 * 1024 * 1024
GB = 1024**3


def _files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(path for path in source.rglob("*") if path.is_file())


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600} 小时 {seconds % 3600 // 60} 分"
    if seconds >= 60:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds} 秒"


class Progress:
    def __init__(self, label: str, done: int, total: int) -> None:
        self.label = label
        self.done = done
        self.total = total
        self.tty = sys.stdout.isatty()
        default = 1.0 if self.tty else 10.0
        self.interval = float(os.environ.get("SLATEHAND_PROGRESS_INTERVAL", default))
        self.samples: deque[tuple[float, int]] = deque()
        self.last_print = 0.0

    def update(self, done: int, name: str, *, final: bool = False) -> None:
        self.done = done
        now = time.monotonic()
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > 20:
            self.samples.popleft()
        if not final and now - self.last_print < self.interval:
            return
        self.last_print = now
        start_time, start_done = self.samples[0]
        speed = (done - start_done) / (now - start_time) if now > start_time else 0.0
        remaining = max(0, self.total - done)
        eta = f"剩余约 {_duration(remaining / speed)}" if speed > 0 and remaining else "估算中"
        if final:
            eta = "完成"
        line = (
            f"{time.strftime('%H:%M:%S')} {self.label} "
            f"{done / GB:.1f} / {self.total / GB:.1f} GB · "
            f"{speed / 1024**2:.0f} MB/s · {eta} · {name}"
        )
        if self.tty:
            print("\r\033[K" + line, end="\n" if final else "", flush=True)
        else:
            print(line, flush=True)


def copy_file(source: Path, target: Path, report, threads: int) -> None:
    """并行分块复制；``report(已复制字节)`` 只在调用线程里被调用。"""
    size = source.stat().st_size
    with target.open("wb") as writer:
        writer.truncate(size)
    pieces: queue.SimpleQueue[int] = queue.SimpleQueue()
    for offset in range(0, size, PIECE):
        pieces.put(offset)
    copied = [0]
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        reader = os.open(source, os.O_RDONLY)
        writer = os.open(target, os.O_WRONLY)
        try:
            while not errors:
                try:
                    offset = pieces.get_nowait()
                except queue.Empty:
                    return
                end = min(offset + PIECE, size)
                position = offset
                while position < end:
                    data = os.pread(reader, min(CHUNK, end - position), position)
                    if not data:
                        raise OSError(f"读取 {source.name} 时提前结束于 {position} 字节。")
                    view = memoryview(data)
                    while view:
                        written = os.pwrite(writer, view, position)
                        position += written
                        view = view[written:]
                    with lock:
                        copied[0] += len(data)
        except BaseException as error:
            errors.append(error)
        finally:
            os.close(reader)
            os.close(writer)

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, threads))]
    for thread in workers:
        thread.start()
    while any(thread.is_alive() for thread in workers):
        report(copied[0])
        time.sleep(0.5)
    if errors:
        raise errors[0]
    if copied[0] != size:
        raise OSError(f"{source.name} 只复制了 {copied[0]} / {size} 字节。")
    report(copied[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--done", type=int, default=0)
    parser.add_argument("--total", type=int, default=0)
    args = parser.parse_args(argv)
    files = _files(args.source)
    size = sum(path.stat().st_size for path in files)
    progress = Progress(args.label, args.done, args.total or args.done + size)
    threads = int(os.environ.get("SLATEHAND_COPY_THREADS", "8"))
    done = args.done
    for path in files:
        target = (
            args.target if args.source.is_file() else args.target / path.relative_to(args.source)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        base = done
        copy_file(
            path,
            target,
            lambda copied, base=base, name=path.name: progress.update(base + copied, name),
            threads,
        )
        done = base + path.stat().st_size
        shutil.copystat(path, target, follow_symlinks=True)
    progress.update(done, args.source.name, final=args.done + size >= progress.total)
    os.sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
