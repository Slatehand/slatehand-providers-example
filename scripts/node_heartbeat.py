#!/usr/bin/env python3
"""维持 Windows 模型服务的控制租约（活性心跳），由 scripts/windows_node.sh up 在前台运行。

每 5 秒 acquire/heartbeat 一次；Ctrl-C、关闭终端（SIGHUP）或 SIGTERM 时释放租约后退出。
Windows 服务以 ``--exit-when-controller-lost`` 运行，租约一释放就取消任务、释放 GPU 并自行退出；
本进程被强杀或 Mac 休眠时，租约 20 秒后超时，效果相同。
只用标准库；Token 从文件读取，不出现在命令行或日志里。

用法：node_heartbeat.py <endpoint> <token-file>
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

INTERVAL_SECONDS = 5.0
TIMEOUT_SECONDS = 3.0


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def request(method: str, url: str, token: str, body: dict | None = None) -> int:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    endpoint = sys.argv[1].rstrip("/")
    token = Path(sys.argv[2]).read_text(encoding="ascii").strip()
    session = uuid.uuid4().hex
    stop = threading.Event()
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    acquired = False
    state = ""
    log("心跳已启动；Ctrl-C 或关闭终端即释放租约，Windows 服务随之退出。")
    while not stop.is_set():
        route = "heartbeat" if acquired else "acquire"
        try:
            status = request(
                "POST",
                f"{endpoint}/control/controller-lease/{route}",
                token,
                {"session_id": session},
            )
        except OSError as error:
            status, detail = 0, str(error)
        else:
            detail = f"HTTP {status}"
        acquired = status in ({200} if acquired else {200, 201})
        current = "已持有租约" if acquired else f"未持有租约（{detail}）"
        if current != state:
            log(current)
            state = current
        stop.wait(INTERVAL_SECONDS)
    if acquired:
        try:
            status = request("DELETE", f"{endpoint}/control/controller-leases/{session}", token)
            log(f"已释放租约（HTTP {status}）。")
        except OSError as error:
            log(f"释放租约失败：{error}（服务会在 20 秒后自行超时释放）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
