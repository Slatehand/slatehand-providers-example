#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# 仓库根目录：虚拟环境 .venv 与 Demucs 运行时 .demucs-venv 都在这里。
repository_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
python="${SLATEHAND_PROVIDER_PYTHON:-$repository_root/.venv/bin/python}"

if [ ! -x "$python" ]; then
    echo "缺少 Python 虚拟环境；请先在本仓库创建 .venv 并安装 Slatehand Core 与 .[services]（见 README）。" >&2
    exit 2
fi

export PYTHONPATH="$repository_root"
export SLATEHAND_CODEX_OUTPUT_ROOT="${SLATEHAND_CODEX_OUTPUT_ROOT:-$HOME/.codex/generated_images}"
export SLATEHAND_AGY_OUTPUT_ROOT="${SLATEHAND_AGY_OUTPUT_ROOT:-$HOME/.gemini/antigravity-cli/brain}"
# launchd 不继承交互式 shell 的 PATH；Demucs worker 需要发现 Homebrew 的
# ffmpeg/ffprobe。Intel 与 Apple Silicon 的常见安装位置都显式列出。
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export SLATEHAND_FFPROBE="${SLATEHAND_FFPROBE:-/opt/homebrew/bin/ffprobe}"
export SLATEHAND_DEMUCS_PYTHON="${SLATEHAND_DEMUCS_PYTHON:-$repository_root/.demucs-venv/bin/python}"

exec "$python" -m default_model_providers_implement.server \
    --host 127.0.0.1 \
    --port 8792 \
    --state-root "$repository_root/var/codex-image-provider" \
    --services codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit,demucs_audio_separation \
    --lane network_image:4:codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit \
    --lane mac_heavy:1:demucs_audio_separation
