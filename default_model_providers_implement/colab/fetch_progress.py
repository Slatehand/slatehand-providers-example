"""多连接下载（Colab 缓存权重用）：以 GB 显示已下载/总量、速度与预计剩余时间。

用法：fetch_progress.py <URL> <目标文件> --size <字节数> --label <阶段名>
      [--done 已完成字节] [--total 总字节]

先解析一次跳转得到最终地址，按 64 MB 分块由多个连接（默认 16，``SLATEHAND_FETCH_CONNECTIONS`` 可改）
并行发 Range 请求，以 pwrite 写入预分配的目标文件；单块失败最多重试 4 次，结束后核对总字节数。
``--done``/``--total`` 让同一阶段的多个文件共用一条总进度。终端里原地刷新同一行；
输出到日志或管道时每 10 秒追加一行（``SLATEHAND_PROGRESS_INTERVAL`` 可改），
本机 scripts/progress_view.py 会渲染成进度条。
只用标准库。
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

PIECE = 64 * 1024 * 1024
CHUNK = 4 * 1024 * 1024
ATTEMPTS = 4
GB = 1024**3


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600} 小时 {seconds % 3600 // 60} 分"
    if seconds >= 60:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds} 秒"


class Progress:
    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = total
        self.tty = sys.stdout.isatty()
        default = 1.0 if self.tty else 10.0
        self.interval = float(os.environ.get("SLATEHAND_PROGRESS_INTERVAL", default))
        self.samples: deque[tuple[float, int]] = deque()
        self.last_print = 0.0

    def update(self, done: int, name: str, *, final: bool = False) -> None:
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


def resolve(url: str) -> str:
    """跟随跳转（例如 Hugging Face → CDN），返回最终下载地址。"""
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as response:
        return response.geturl()


def fetch(url: str, target: Path, size: int, connections: int, report) -> None:
    """并行分块下载到 target；``report(已下载字节)`` 只在调用线程里被调用。"""
    final = resolve(url)
    with target.open("wb") as writer:
        writer.truncate(size)
    pieces: queue.SimpleQueue[int] = queue.SimpleQueue()
    for offset in range(0, size, PIECE):
        pieces.put(offset)
    downloaded = [0]
    lock = threading.Lock()
    errors: list[BaseException] = []

    def piece(fd: int, offset: int) -> None:
        end = min(offset + PIECE, size)
        for attempt in range(1, ATTEMPTS + 1):
            position, counted = offset, 0
            try:
                request = urllib.request.Request(
                    final, headers={"Range": f"bytes={offset}-{end - 1}"}
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    if response.status != 206:
                        raise OSError(f"服务器不支持分段下载（HTTP {response.status}）。")
                    while position < end:
                        data = response.read(min(CHUNK, end - position))
                        if not data:
                            raise OSError(f"连接在 {position} 字节处提前结束。")
                        view = memoryview(data)
                        while view:
                            written = os.pwrite(fd, view, position)
                            position += written
                            view = view[written:]
                        counted += len(data)
                        with lock:
                            downloaded[0] += len(data)
                return
            except OSError:
                with lock:
                    downloaded[0] -= counted
                if attempt == ATTEMPTS:
                    raise
                time.sleep(2 * attempt)

    def worker() -> None:
        fd = os.open(target, os.O_WRONLY)
        try:
            while not errors:
                try:
                    offset = pieces.get_nowait()
                except queue.Empty:
                    return
                piece(fd, offset)
        except BaseException as error:
            errors.append(error)
        finally:
            os.close(fd)

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, connections))]
    for thread in workers:
        thread.start()
    while any(thread.is_alive() for thread in workers):
        report(downloaded[0])
        time.sleep(0.5)
    if errors:
        raise errors[0]
    if downloaded[0] != size or target.stat().st_size != size:
        raise OSError(f"{target.name} 只下载了 {downloaded[0]} / {size} 字节。")
    report(downloaded[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("target", type=Path)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--done", type=int, default=0)
    parser.add_argument("--total", type=int, default=0)
    args = parser.parse_args(argv)
    progress = Progress(args.label, args.total or args.done + args.size)
    connections = int(os.environ.get("SLATEHAND_FETCH_CONNECTIONS", "16"))
    args.target.parent.mkdir(parents=True, exist_ok=True)
    name = args.target.name
    fetch(
        args.url,
        args.target,
        args.size,
        connections,
        lambda downloaded: progress.update(args.done + downloaded, name),
    )
    progress.update(args.done + args.size, name, final=args.done + args.size >= progress.total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
