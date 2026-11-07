#!/usr/bin/env bash
# Colab VM：启动或停止只含 H3 FL2VA/Ref2VA 的模型服务。只绑定回环地址，Core 经 colab ssh 隧道访问。
# 用法：run_server.sh start|stop|status
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
STATE=/content/slatehand-state
TOKEN_FILE=/root/.slatehand-colab-token
PORT=8791
PID_FILE="$STATE/service.pid"

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

case "${1:-}" in
  start)
    if running; then echo "已在运行（PID $(cat "$PID_FILE")）。"; exit 0; fi
    [ -s "$TOKEN_FILE" ] || { echo "缺少 ${TOKEN_FILE}。" >&2; exit 2; }
    mkdir -p "$STATE"
    [ -f "$STATE/server.log" ] && mv "$STATE/server.log" "$STATE/server.prev.log"
    cd "$REPO"
    SLATEHAND_MODEL_SERVICE_TOKEN=$(cat "$TOKEN_FILE") \
    SLATEHAND_COMFYUI_ROOT=/content/ComfyUI \
    SLATEHAND_H3_PYTHON=$(command -v python3) \
    PYTHONPATH="$REPO" \
      setsid nohup python3 -m default_model_providers_implement.server \
        --host 127.0.0.1 --port "$PORT" --state-root "$STATE" \
        --services h3_fl2va,h3_ref2va --resource-name exclusive_gpu \
        --auth-token-env SLATEHAND_MODEL_SERVICE_TOKEN \
        > "$STATE/server.log" 2>&1 &
    echo $! > "$PID_FILE"
    for _ in $(seq 1 30); do
      if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then echo "H3 服务已启动（PID $(cat "$PID_FILE")）。"; exit 0; fi
      running || { echo "服务启动失败：" >&2; tail -n 20 "$STATE/server.log" >&2; exit 1; }
      sleep 1
    done
    echo "等待服务端口超时。" >&2; exit 1
    ;;
  stop)
    # 服务以独立进程组启动，连同 Comfy Core 子进程一起结束并释放显存。
    if running; then kill -TERM -- "-$(cat "$PID_FILE")"; echo "已停止。"; else echo "未在运行。"; fi
    ;;
  status)
    if running; then echo "running $(cat "$PID_FILE")"; else echo "stopped"; exit 1; fi
    ;;
  *) echo "用法：$0 start|stop|status" >&2; exit 2 ;;
esac
