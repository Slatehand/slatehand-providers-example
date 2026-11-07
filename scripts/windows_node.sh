#!/usr/bin/env bash
# 启动 Windows GPU 节点（H3、Breeze、IndexTTS2、SeedVR2、Stable Audio 3、YuE2、Qwen Image）。
#
#   scripts/windows_node.sh up       经 SSH 安装并启动 Windows 计划任务，等服务可达后在前台持续维持控制租约（心跳）
#   scripts/windows_node.sh status   查看心跳与服务
#
# up 不返回：心跳在当前终端前台运行。Ctrl-C 或关闭终端即释放租约；Windows 服务以 --exit-when-controller-lost
# 运行，租约一释放（或 20 秒超时，例如 Mac 休眠）就取消任务、释放 GPU 并自行退出。没有 down。
# Core 不启停 Windows、也不维持心跳，只连接。
# 配置取本仓库 provider.local.env 的 SLATEHAND_WINDOWS_RUNTIME_ENDPOINT、
# SLATEHAND_WINDOWS_SSH_TARGET、SLATEHAND_WINDOWS_REPOSITORY_ROOT、SLATEHAND_WINDOWS_LISTEN_ADDRESS。
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
TOKEN=$REPO/var/secrets/windows-model-service-token
STATE=$REPO/var/node-state
HEARTBEAT_PID=$STATE/windows-heartbeat.pid

setting() { sed -n "s/^$1=//p" "$REPO/provider.local.env" | tail -n 1 | sed -e "s/^['\"]//" -e "s/['\"]$//"; }
ENDPOINT=$(setting SLATEHAND_WINDOWS_RUNTIME_ENDPOINT)
SSH_TARGET=$(setting SLATEHAND_WINDOWS_SSH_TARGET)
REPOSITORY_ROOT=$(setting SLATEHAND_WINDOWS_REPOSITORY_ROOT)
LISTEN_ADDRESS=$(setting SLATEHAND_WINDOWS_LISTEN_ADDRESS)
for name in ENDPOINT SSH_TARGET REPOSITORY_ROOT LISTEN_ADDRESS; do
  [ -n "${!name}" ] || { echo "provider.local.env 缺少 Windows 配置：${name}" >&2; exit 2; }
done
[ -s "$TOKEN" ] || { echo "缺少 ${TOKEN}" >&2; exit 2; }

heartbeat_alive() { [ -f "$HEARTBEAT_PID" ] && kill -0 "$(cat "$HEARTBEAT_PID")" 2>/dev/null; }
reachable() { curl -s -o /dev/null -m 3 "$ENDPOINT/"; }

# 经 SSH 运行仓库内固定的 PowerShell 脚本（-EncodedCommand，避免引号与分号转义问题）。
run_windows_script() {
  local script="$1" arguments="${2:-}"
  local path="${REPOSITORY_ROOT%\\}\\default_model_providers_implement\\windows\\${script}"
  local quoted=${path//\'/\'\'}
  local command
  command=$(cat <<EOF
\$ErrorActionPreference = "Stop"
\$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(\$false)
try {
    \$scriptPath = '${quoted}'
    if (-not (Test-Path -LiteralPath \$scriptPath -PathType Leaf)) { throw "script not found: \$scriptPath" }
    & \$scriptPath ${arguments}
    if (-not \$?) { exit 1 }
} catch {
    [Console]::Error.WriteLine("Windows Provider command failed: " + \$_.Exception.Message)
    exit 1
}
EOF
)
  local encoded
  encoded=$(printf '%s' "$command" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$SSH_TARGET" \
    powershell.exe -NoProfile -NonInteractive -OutputFormat Text -ExecutionPolicy Bypass \
    -EncodedCommand "$encoded"
}


# 主体包在函数里并在文件末尾调用：bash 先读完整个文件再执行，运行中修改脚本不会读错位。
main() {
  case "${1:-}" in
    up)
      mkdir -p "$STATE"
      if heartbeat_alive; then
        echo "Windows 节点已在运行（心跳 PID $(cat "$HEARTBEAT_PID")）。要重启，先在它的终端里 Ctrl-C。"
        exit 0
      fi
      echo "==> 经 ${SSH_TARGET} 启动 Windows 模型服务"
      run_windows_script install_scheduled_task.ps1 "-ListenAddress '${LISTEN_ADDRESS}'"
      for _ in $(seq 1 60); do reachable && break; sleep 1; done
      reachable || { echo "等待 ${ENDPOINT} 可达超时。" >&2; exit 1; }
      echo "==> Windows 节点就绪，心跳在前台运行（Ctrl-C 或关闭终端即关闭 Windows 服务）"
      echo $$ > "$HEARTBEAT_PID"
      exec python3 "$REPO/scripts/node_heartbeat.py" "$ENDPOINT" "$TOKEN"
      ;;
    status)
      if heartbeat_alive; then
        echo "心跳运行中（PID $(cat "$HEARTBEAT_PID")）。"
      else
        echo "心跳未运行。"
      fi
      if reachable; then echo "服务可达：${ENDPOINT}"; else echo "服务不可达：${ENDPOINT}"; fi
      ;;
    *)
      echo "用法：$0 up|status" >&2
      exit 2
      ;;
  esac
}

main "$@"
exit $?
