"""随 Core 启停的部署服务：Mac LaunchAgent 与本机 whisper.cpp。

``start()`` 阻塞到服务可达，失败时抛出 ``RuntimeError`` 让 Core 停止启动并回滚已启动的服务；
``close()`` 只报告失败，不抛出。
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .deployment import WHISPER_PORT

MAC_LABEL = "com.slatehand.codex-image"


def say(message: str) -> None:
    print(message, flush=True)


def wait_reachable(
    name: str,
    url: str,
    seconds: float,
    *,
    alive: Callable[[], bool] = lambda: True,
    require_success: bool = False,
) -> None:
    """轮询到 URL 有 HTTP 响应（``require_success`` 时须为 2xx）；超时或进程退出时报错。"""
    deadline = time.monotonic() + seconds
    while True:
        if not alive():
            raise RuntimeError(f"{name} 在启动过程中退出。")
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except urllib.error.HTTPError:
            if not require_success:
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError(f"等待 {name} 可达超时：{url}")
        time.sleep(0.5)


class MacProviderService:
    """安装并启动本机 LaunchAgent（Codex/AGY 生图、Demucs），关闭时卸载。"""

    def __init__(self, install_script: Path, endpoint: str, *, run=subprocess.run) -> None:
        self._install_script = install_script
        self._endpoint = endpoint
        self._run = run

    def start(self) -> None:
        if not os.access(self._install_script, os.X_OK):
            raise RuntimeError(f"缺少 Mac Provider 启动脚本：{self._install_script}")
        say("正在重启本机 Mac Model Provider……")
        result = self._run([str(self._install_script)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Mac Model Provider 启动失败：{_tail(result)}")
        wait_reachable("Mac Model Provider", self._endpoint + "/", 60)

    def close(self) -> None:
        self._run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{MAC_LABEL}"],
            capture_output=True,
            check=False,
        )


class WhisperService:
    """在独立 session 中运行 whisper.cpp 服务；首次加载模型可能较慢。"""

    def __init__(self, server: Path, model: Path, *, popen=subprocess.Popen) -> None:
        self._command = [
            str(server),
            "--host",
            "127.0.0.1",
            "--port",
            str(WHISPER_PORT),
            "--model",
            str(model),
            "--language",
            "auto",
            "--flash-attn",
        ]
        self._popen = popen
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        say("正在启动本机 Whisper ASR（首次加载模型可能较慢）……")
        self._process = self._popen(self._command, start_new_session=True)
        process = self._process
        wait_reachable(
            "Whisper ASR",
            f"http://127.0.0.1:{WHISPER_PORT}/",
            240,
            alive=lambda: process.poll() is None,
            require_success=True,
        )

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _tail(result) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text[-1_000:] or f"退出码 {result.returncode}"
