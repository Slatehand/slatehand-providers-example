#!/usr/bin/env python3
"""在当前终端的用户会话中独立启停 Mac Provider。"""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "var/codex-image-provider"
LAUNCHER = ROOT / "default_model_providers_implement/macos/run_codex_server.sh"
STDERR = STATE / "service.stderr.log"
HOST, PORT = "127.0.0.1", 8792


def running_pid() -> int | None:
    try:
        pid = int((STATE / "service.pid").read_text(encoding="ascii"))
    except (FileNotFoundError, ValueError):
        return None
    if pid <= 1:
        return None
    process = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    )
    invocation = (
        f" -m default_model_providers_implement.server --host {HOST} "
        f"--port {PORT} --state-root {STATE} --services "
    )
    return pid if process.returncode == 0 and invocation in process.stdout else None


def listening() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return True
    except OSError:
        return False


def start() -> None:
    deadline = time.monotonic() + 20
    with (STATE / "service.stdout.log").open("ab") as stdout, STDERR.open("ab") as stderr:
        process = subprocess.Popen(
            [str(LAUNCHER)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if running_pid() == process.pid and listening():
                print(f"Mac Provider 已启动（{HOST}:{PORT}，PID {process.pid}）。")
                return
            time.sleep(0.2)
        raise SystemExit(f"Mac Provider 启动失败，请查看 {STDERR}")
    except (SystemExit, KeyboardInterrupt):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise


def stop(pid: int) -> None:
    # 服务处理 SIGTERM，等待调度器结束任务并写回状态。
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 20
    while running_pid() == pid and time.monotonic() < deadline:
        time.sleep(0.2)
    if running_pid() == pid:
        raise SystemExit(f"等待 Mac Provider 停止超时，请查看 {STDERR}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "status", "down"))
    action = parser.parse_args().action
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "mac-node.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pid = running_pid()
        if action == "down" and pid is not None:
            stop(pid)
            pid = None
        if pid is not None:
            print(f"Mac Provider 正在运行（{HOST}:{PORT}，PID {pid}）。")
            return 0
        if action == "up":
            if listening():
                raise SystemExit(f"{HOST}:{PORT} 已被其它进程占用。")
            start()
            return 0
        print("Mac Provider 未运行。")
        return 1 if action == "status" else 0


if __name__ == "__main__":
    raise SystemExit(main())
