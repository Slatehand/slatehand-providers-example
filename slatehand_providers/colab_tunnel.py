"""随 Core 启停的 Colab 隧道：把本机回环端口经 ``colab ssh`` 转发到 VM 上的模型服务。

Colab 会话由人按需开关，不随 Core 启停，因此 ``start()`` 不等待隧道可用、也不因会话缺席而失败：
后台线程只在 ``colab sessions`` 列出目标会话时才建立 SSH 转发（``colab ssh --proxy-mode`` 遇到缺席
会话会自动开新 VM，先确认可避免误开计费机器），断开后自动重连。隧道不通时 H3 的 Colab 节点
提交会得到连接错误，本地 Windows 节点不受影响。
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import threading

from .deployment import ColabDeployment

REMOTE_PORT = 8791
SESSION_POLL_SECONDS = 30.0
RECONNECT_SECONDS = 5.0


class ColabTunnelService:
    def __init__(
        self,
        deployment: ColabDeployment,
        *,
        run=subprocess.run,
        popen=subprocess.Popen,
        wait=None,
    ) -> None:
        self._deployment = deployment
        self._run = run
        self._popen = popen
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._state = ""

    def start(self) -> None:
        print(
            f"Colab H3 节点：会话 {self._deployment.session} → {self._deployment.endpoint}"
            "（隧道在后台按需建立）。",
            flush=True,
        )
        self._thread = threading.Thread(target=self._loop, name="colab-tunnel", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self._thread is not None:
            self._thread.join(timeout=15)

    # ------------------------------------------------------------ 后台

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.session_running():
                self._report("absent", "Colab 会话未运行，H3 Colab 节点暂不可用。")
                self._wait(SESSION_POLL_SECONDS)
                continue
            with self._lock:
                if self._stop.is_set():
                    return
                self._process = self._popen(
                    self.ssh_command(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                process = self._process
            self._report("up", "Colab 隧道已建立。")
            _out, err = process.communicate()
            if self._stop.is_set():
                return
            detail = (err or "").strip()[-300:] or f"退出码 {process.returncode}"
            self._report("down", f"Colab 隧道断开，稍后重连：{detail}")
            self._wait(RECONNECT_SECONDS)

    def session_running(self) -> bool:
        try:
            result = self._run(
                [self._deployment.cli, "sessions"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        prefix = f"[{self._deployment.session}] "
        return result.returncode == 0 and any(
            line.startswith(prefix) for line in result.stdout.splitlines()
        )

    def ssh_command(self) -> list[str]:
        deployment = self._deployment
        proxy = shlex.join([deployment.cli, "ssh", "--proxy-mode", "-s", deployment.session])
        return [
            "ssh",
            "-N",
            "-o",
            f"ProxyCommand={proxy}",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-L",
            f"127.0.0.1:{deployment.local_port}:127.0.0.1:{REMOTE_PORT}",
            "root@colab-runtime",
        ]

    def _report(self, state: str, message: str) -> None:
        if state != self._state:
            self._state = state
            print(message, file=sys.stderr if state != "up" else sys.stdout, flush=True)
