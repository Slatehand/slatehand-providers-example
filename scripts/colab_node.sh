#!/usr/bin/env bash
# 在本机开关 Colab H3 节点：up 开机（缺会话时创建 G4）→ 同步代码与 Token → 安装/缓存 → 启动服务；
# status 查看；down 关机（colab stop 回收 VM，Drive 内容不受影响）。
# Drive 挂载需要人工授权：up 发现未挂载时提示运行 colab drivemount 后重跑。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
ENV_FILE=provider.local.env
TOKEN=var/secrets/colab-model-service-token
SESSION=${SLATEHAND_COLAB_SESSION:-$(sed -n 's/^SLATEHAND_COLAB_SESSION=//p' "$ENV_FILE" 2>/dev/null | tr -d "'\"" | tail -n 1)}
SESSION=${SESSION:-slate}
COLAB=${SLATEHAND_COLAB_CLI:-colab}
REMOTE=/content/slatehand-providers

remote() { "$COLAB" ssh -s "$SESSION" -- bash -lc "$1"; }
session_running() { "$COLAB" sessions 2>/dev/null | grep -q "^\[$SESSION\] "; }

case "${1:-}" in
  up)
    if [ ! -s "$TOKEN" ]; then
      mkdir -p "$(dirname "$TOKEN")"
      (umask 077 && openssl rand -hex 32 > "$TOKEN")
      echo "已生成 ${TOKEN}。"
    fi
    if ! session_running; then
      echo "创建 Colab G4 会话 ${SESSION} ……"
      "$COLAB" new -s "$SESSION" --gpu G4
    fi
    if ! remote "test -d /content/drive/MyDrive" >/dev/null 2>&1; then
      echo "Drive 未挂载。请在自己的终端运行：${COLAB} drivemount -s ${SESSION}，授权后重新执行 ${0} up" >&2
      exit 2
    fi
    archive=$(mktemp -t slatehand-colab).tar.gz
    trap 'rm -f "$archive"' EXIT
    COPYFILE_DISABLE=1 tar --no-xattrs --exclude '__pycache__' -czf "$archive" default_model_providers_implement
    "$COLAB" upload -s "$SESSION" "$archive" /content/slatehand-providers.tar.gz >/dev/null
    "$COLAB" upload -s "$SESSION" "$TOKEN" /root/.slatehand-colab-token >/dev/null
    remote "chmod 600 /root/.slatehand-colab-token && rm -rf $REMOTE/default_model_providers_implement && mkdir -p $REMOTE && tar -xzf /content/slatehand-providers.tar.gz -C $REMOTE"
    remote "bash $REMOTE/default_model_providers_implement/colab/setup.sh"
    remote "bash $REMOTE/default_model_providers_implement/colab/run_server.sh stop >/dev/null; bash $REMOTE/default_model_providers_implement/colab/run_server.sh start"
    echo "Colab H3 节点就绪；Core 运行时会自动建立隧道。"
    ;;
  status)
    if ! session_running; then echo "会话 ${SESSION} 未运行。"; exit 1; fi
    remote "bash $REMOTE/default_model_providers_implement/colab/run_server.sh status; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader"
    ;;
  down)
    if session_running; then
      "$COLAB" stop -s "$SESSION"
    else
      echo "会话 ${SESSION} 未运行。"
    fi
    ;;
  *)
    echo "用法：$0 up|status|down" >&2
    exit 2
    ;;
esac
