#!/usr/bin/env bash
# 本仓库的工程门禁：格式、静态检查与测试。
# 用法：./scripts/check.sh          （跳过 slow 标记的重测试）
#       ./scripts/check.sh --full   （全跑）
# 需要 .venv 已安装 Slatehand Core（../slatehand，含 dev extras）与本仓库 .[services]；
# 测试复用 Core 检出目录里的测试支撑（见 provider_tests/conftest.py）。
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  "") PYTEST_MARK="not slow" ;;
  --full) PYTEST_MARK="not slow or slow" ;;
  *)
    echo "用法：$0 [--full]" >&2
    exit 2
    ;;
esac

.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -n auto -m "$PYTEST_MARK"
git diff --check
echo "check: all gates green"
