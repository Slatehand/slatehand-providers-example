#!/usr/bin/env bash
# Colab VM：启动或停止只含 H3 FL2VA/Ref2VA 与 Breeze TTS 2 的模型服务。只绑定回环地址，Core 经
# colab ssh 隧道访问。VM 的开关由人手动管理（scripts/colab_node.sh），这里不做租约或自动回收。
# 用法：run_server.sh start|stop|status
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
STATE=/content/slatehand-state
TOKEN_FILE=/root/.slatehand-colab-token
PORT=8791
PID_FILE="$STATE/service.pid"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

case "${1:-}" in
  start)
    mkdir -p "$STATE"
    if alive "$PID_FILE"; then echo "已在运行（PID $(cat "$PID_FILE")）。"; exit 0; fi
    [ -s "$TOKEN_FILE" ] || { echo "缺少 ${TOKEN_FILE}。" >&2; exit 2; }
    [ -f "$STATE/server.log" ] && mv "$STATE/server.log" "$STATE/server.prev.log"
    cd "$REPO"
    SLATEHAND_MODEL_SERVICE_TOKEN=$(cat "$TOKEN_FILE") \
    SLATEHAND_COMFYUI_ROOT=/content/ComfyUI \
    SLATEHAND_H3_PYTHON=$(command -v python3) \
    SLATEHAND_BREEZE_PYTHON_HOST=$(command -v python3) \
    SLATEHAND_BREEZE_PYTHON=/content/breeze-venv/bin/python \
    SLATEHAND_BREEZE_REPOSITORY=/content/breeze-tts \
    SLATEHAND_BREEZE_MODEL=/content/models/Breeze-TTS-2 \
    PYTHONPATH="$REPO" \
      setsid nohup python3 -m default_model_providers_implement.server \
        --host 127.0.0.1 --port "$PORT" --state-root "$STATE" \
        --services h3_fl2va,h3_ref2va,breeze_tts_2 --resource-name exclusive_gpu \
        --auth-token-env SLATEHAND_MODEL_SERVICE_TOKEN \
        > "$STATE/server.log" 2>&1 &
    echo $! > "$PID_FILE"
    for _ in $(seq 1 30); do
      if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
        echo "模型服务已启动（PID $(cat "$PID_FILE")）。"
        exit 0
      fi
      alive "$PID_FILE" || { echo "服务启动失败：" >&2; tail -n 20 "$STATE/server.log" >&2; exit 1; }
      sleep 1
    done
    echo "等待服务端口超时。" >&2; exit 1
    ;;
  stop)
    # 服务以独立进程组启动，连同 Comfy Core / Breeze 子进程一起结束并释放显存。
    if alive "$PID_FILE"; then kill -TERM -- "-$(cat "$PID_FILE")"; echo "已停止。"; else echo "未在运行。"; fi
    ;;
  status)
    if alive "$PID_FILE"; then echo "service running $(cat "$PID_FILE")"; else echo "service stopped"; exit 1; fi
    ;;
  *) echo "用法：$0 start|stop|status" >&2; exit 2 ;;
esac
