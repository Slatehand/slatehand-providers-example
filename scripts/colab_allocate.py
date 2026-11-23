"""在一小时内等待 Colab CLI 分配 G4，会话就绪后由节点脚本继续部署。"""

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress

WAIT_SECONDS = 3600
PROGRESS_SECONDS = 60


def allocate(cli: str, session: str) -> int:
    cancelled = False

    def cancel(_signum, _frame):
        nonlocal cancelled
        cancelled = True

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, cancel)

    print(f"==> 等待 Colab 分配 G4 会话 {session}（最多 1 小时，随时按 Ctrl-C 取消）", flush=True)
    started = time.monotonic()
    next_progress = started + PROGRESS_SECONDS
    # CLI 用同一 notebook hash 核对分配结果，再重试临时错误。
    # 10 次指数退避从 5 秒开始，总计超过一小时，由外层控制总时限。
    env = {
        **os.environ,
        "COLAB_CLI_REQUEST_TIMEOUT": str(WAIT_SECONDS),
        "COLAB_CLI_ASSIGN_RETRIES": "10",
        "COLAB_CLI_RETRY_BACKOFF": "5",
    }
    try:
        process = subprocess.Popen(
            [cli, "new", "-s", session, "--gpu", "G4"], env=env, start_new_session=True
        )
    except OSError as error:
        print(f"无法启动 Colab CLI（{error.strerror}）。", file=sys.stderr)
        return 1

    try:
        while not cancelled:
            status = process.poll()
            if status is not None:
                return status
            now = time.monotonic()
            remaining = WAIT_SECONDS - (now - started)
            if remaining <= 0:
                print("等待 Colab 分配 G4 已满 1 小时，已停止等待。", file=sys.stderr)
                return 124
            if now >= next_progress:
                elapsed_minutes = int(now - started) // 60
                print(
                    f"Colab G4 仍在等待分配（已等 {elapsed_minutes}/60 分钟，Ctrl-C 取消）。",
                    flush=True,
                )
                next_progress = now + PROGRESS_SECONDS
            time.sleep(min(remaining, next_progress - now, 0.25))

        print("\n已取消等待 Colab 分配 G4。", file=sys.stderr)
        return 130
    finally:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    sys.exit(allocate(*sys.argv[1:]))
