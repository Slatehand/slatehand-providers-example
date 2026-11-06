"""随 Core 启停的部署服务：经 SSH 启停 Windows 模型服务、Mac LaunchAgent 与本机 whisper.cpp。

``start()`` 阻塞到服务可达，失败时抛出 ``RuntimeError`` 让 Core 停止启动并回滚已启动的服务；
``close()`` 只报告失败，不抛出。
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .deployment import WHISPER_PORT, WindowsDeployment

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


def powershell_command(script_path: str, listen_address: str | None = None) -> str:
    """生成经 SSH 执行 Windows 脚本的 ``-EncodedCommand``；只运行仓库内固定脚本。"""

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    arguments = f" -ListenAddress {quote(listen_address)}" if listen_address else ""
    command = f"""
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$Culture = [System.Globalization.CultureInfo]::GetCultureInfo("en-US")
[System.Globalization.CultureInfo]::CurrentCulture = $Culture
[System.Globalization.CultureInfo]::CurrentUICulture = $Culture
try {{
    $scriptPath = {quote(script_path)}
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {{
        throw "Windows Provider script not found: $scriptPath"
    }}
    & $scriptPath{arguments}
    if (-not $?) {{ exit 1 }}
}} catch {{
    [Console]::Error.WriteLine("Windows Provider command failed: " + $_.Exception.Message)
    exit 1
}}
"""
    return base64.b64encode(command.encode("utf-16le")).decode("ascii")


class WindowsProviderService:
    """启动时经 SSH 重装并启动 Windows 计划任务，关闭时经 SSH 停止模型服务。"""

    def __init__(self, deployment: WindowsDeployment, *, run=subprocess.run) -> None:
        if not (deployment.ssh_target and deployment.repository_root and deployment.listen_address):
            raise ValueError("Windows 服务启停需要 SSH 目标、仓库路径与监听地址。")
        self._deployment = deployment
        self._run = run
        scripts = deployment.repository_root.rstrip("\\") + (
            "\\default_model_providers_implement\\windows\\"
        )
        self._install = scripts + "install_scheduled_task.ps1"
        self._stop = scripts + "stop_services.ps1"

    def start(self) -> None:
        deployment = self._deployment
        say(f"正在通过 {deployment.ssh_target} 重启 Windows Model Provider……")
        result = self._ssh(powershell_command(self._install, deployment.listen_address))
        if result.returncode != 0:
            raise RuntimeError(f"Windows Model Provider 重启失败：{_tail(result)}")
        wait_reachable("Windows Model Provider", deployment.endpoint + "/", 60)
        wait_reachable("Windows Breeze TTS 2", deployment.breeze_endpoint + "/", 60)

    def close(self) -> None:
        say(f"正在通过 {self._deployment.ssh_target} 关闭 Windows Model Provider……")
        try:
            result = self._ssh(powershell_command(self._stop))
        except (OSError, subprocess.SubprocessError) as exc:
            result = None
            detail = str(exc)
        else:
            detail = _tail(result)
        if result is None or result.returncode != 0:
            print(
                f"警告：Windows Model Provider 未能确认关闭：{detail}", file=sys.stderr, flush=True
            )

    def _ssh(self, encoded: str):
        return self._run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                self._deployment.ssh_target,
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-OutputFormat",
                "Text",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )


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
