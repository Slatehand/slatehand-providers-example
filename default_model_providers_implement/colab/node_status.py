"""Colab 节点状态（scripts/colab_node.sh status/watch 远程调用）：服务、GPU、权重、任务与后台下载。

输出若干行「标签<TAB>内容」，由本机 scripts/progress_view.py 排版。只用标准库，只读不改。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

STATE = Path("/content/slatehand-state")
MODELS = Path("/content/ComfyUI/models")
H3 = MODELS / "diffusion_models" / "minimax-h3"
WEIGHTS = (
    ("Turbo V2", (H3 / "DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors",)),
    ("Hybrid V2", (H3 / "DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors",)),
    (
        "官方 BF16",
        (
            H3 / "minimax_h3_fl2va_pruned_bf16.safetensors",
            H3 / "minimax_h3_ref2va_pruned_bf16.safetensors",
        ),
    ),
    ("Breeze", (Path("/content/models/Breeze-TTS-2/model.safetensors.index.json"),)),
)


def _alive(pid_file: Path) -> int | None:
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def main() -> None:
    rows: list[tuple[str, str]] = []
    pid = _alive(STATE / "service.pid")
    rows.append(("模型服务", f"运行中（PID {pid}）" if pid else "未运行"))

    try:
        gpu = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.split(",")
        used, total = int(gpu[0]) / 1024, int(gpu[1]) / 1024
        rows.append(("GPU", f"显存 {used:.1f} / {total:.1f} GB · 利用率 {gpu[2].strip()}%"))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        rows.append(("GPU", "读取失败"))

    marks = []
    for label, paths in WEIGHTS:
        marks.append(f"{label} {'✓' if all(path.exists() for path in paths) else '…'}")
    rows.append(("权重", "   ".join(marks)))

    try:
        tasks = json.loads((STATE / "runtime-state.json").read_text(encoding="utf-8"))["tasks"]
        states = [task["state"] for task in tasks]
        running = [task for task in tasks if task["state"] == "running"]
        detail = (
            f"运行中 {states.count('running')} · 排队 {states.count('queued')} · 累计 {len(tasks)}"
        )
        if running:
            detail += f" · 当前 {running[0]['kind']} {running[0]['progress'] * 100:.0f}%"
        rows.append(("任务", detail))
    except (OSError, ValueError, KeyError):
        rows.append(("任务", "暂无"))

    try:
        last = (STATE / "setup-background.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    except (OSError, IndexError):
        last = "无"
    downloading = _alive(STATE / "setup-background.pid")
    rows.append(("后台下载", last if downloading else "已结束"))

    for label, text in rows:
        print(f"{label}\t{text}")


if __name__ == "__main__":
    main()
