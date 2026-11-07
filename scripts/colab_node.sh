#!/usr/bin/env bash
# 手动开关 Colab G4 节点（H3 + Breeze TTS 2）。在自己的终端运行：挂 Drive 需要在浏览器里授权。
#
#   scripts/colab_node.sh up       开机（缺会话时创建 G4）→ 挂 Drive（交互授权）→ 同步代码与 Token →
#                            安装环境、缓存 Turbo 权重 → 启动模型服务 → 持续显示后台搬运进度直到搬完。
#                            可重复执行，已完成的步骤会跳过。
#   scripts/colab_node.sh status   查看会话、服务与显存
#   scripts/colab_node.sh down     回收 VM（VM 本地环境清空，Drive 里的权重不受影响；下次 up 重建）
#
# Core 运行时会自动经 colab ssh 建立隧道；在 Provider 设置页把 H3 / Breeze 的「运行节点」切到
# Colab G4 即可使用。会话名取本仓库 provider.local.env 的 SLATEHAND_COLAB_SESSION。
set -euo pipefail
trap 'echo "colab_node.sh 第 ${LINENO} 行失败（退出码 $?），已中止。" >&2' ERR

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
TOKEN=var/secrets/colab-model-service-token
SESSION=${SLATEHAND_COLAB_SESSION:-$(sed -n 's/^SLATEHAND_COLAB_SESSION=//p' provider.local.env 2>/dev/null | tr -d "'\"" | tail -n 1)}
SESSION=${SESSION:-slate}
COLAB=${SLATEHAND_COLAB_CLI:-colab}
REMOTE=/content/slatehand-providers

# 远程命令走 kernel 通道（colab exec），不占用 SSH：Core 运行时其 Colab 隧道独占唯一的 colab ssh 连接。
# colab exec 的退出码恒为 0，这里由远端打印退出码标记，本机解析后作为返回值；输出实时回显。
remote() {
  local output status
  output=$(mktemp -t slatehand-remote)
  {
    printf 'command = %s\n' "$(printf '%s' "$1" | python3 -c 'import sys; print(repr(sys.stdin.read()))')"
    cat <<'PY'
import subprocess, sys
process = subprocess.Popen(["bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for chunk in iter(lambda: process.stdout.read1(65536), b""):
    sys.stdout.write(chunk.decode(errors="replace"))
    sys.stdout.flush()
print(f"__SLATEHAND_RC__={process.wait()}")
PY
  } | "$COLAB" exec -s "$SESSION" --timeout 0 | tee "$output" | { grep -v '^__SLATEHAND_RC__=' || true; } \
    | python3 "$REPO/scripts/progress_view.py"
  status=$(sed -n 's/^__SLATEHAND_RC__=//p' "$output" | tail -n 1)
  rm -f "$output"
  [ "${status:-1}" = 0 ]
}
session_running() { "$COLAB" sessions 2>/dev/null | grep -q "^\[$SESSION\] "; }
drive_mounted() { remote "test -d /content/drive/MyDrive" >/dev/null 2>&1; }

# 主体包在函数里，并在最后一行“调用 + 退出”：bash 先读完整个文件与这一行再执行、执行完直接退出，
# 运行中修改脚本也不会读错位。
main() {
  case "${1:-}" in
    up)
      if [ ! -s "$TOKEN" ]; then
        mkdir -p "$(dirname "$TOKEN")"
        (umask 077 && openssl rand -hex 32 > "$TOKEN")
        echo "已生成 ${TOKEN}。"
      fi
      if ! session_running; then
        echo "==> 创建 Colab G4 会话 ${SESSION}"
        "$COLAB" new -s "$SESSION" --gpu G4
      fi
      if ! drive_mounted; then
        echo "==> 挂载 Google Drive：打开下面的链接授权，把授权码粘回来"
        "$COLAB" drivemount -s "$SESSION"
        drive_mounted || { echo "Drive 仍未挂载，请重新执行 $0 up。" >&2; exit 2; }
      fi
      echo "==> 同步代码与 Token"
      archive=$(mktemp -t slatehand-colab).tar.gz
      trap 'rm -f "$archive"' EXIT
      COPYFILE_DISABLE=1 tar --no-xattrs --exclude '__pycache__' -czf "$archive" default_model_providers_implement
      "$COLAB" upload -s "$SESSION" "$archive" /content/slatehand-providers.tar.gz >/dev/null
      "$COLAB" upload -s "$SESSION" "$TOKEN" /root/.slatehand-colab-token >/dev/null
      remote "chmod 600 /root/.slatehand-colab-token && rm -rf $REMOTE/default_model_providers_implement && mkdir -p $REMOTE && tar -xzf /content/slatehand-providers.tar.gz -C $REMOTE"
      echo "==> 安装环境、缓存 Turbo 所需权重（其余权重随后在后台搬运）"
      remote "SLATEHAND_PROGRESS_INTERVAL=3 bash $REMOTE/default_model_providers_implement/colab/setup.sh"
      echo "==> 启动模型服务"
      remote "bash $REMOTE/default_model_providers_implement/colab/run_server.sh stop >/dev/null; bash $REMOTE/default_model_providers_implement/colab/run_server.sh start"
      echo "Colab 节点已可用 H3 Turbo。不用时记得 $0 down（空闲也按约每小时 10 个计算单元计费）。"
      echo "==> 后台搬运 Breeze、Hybrid V2、官方 BF16（搬完自动结束；Ctrl-C 只停止查看，不影响后台）"
      # 进度行经 progress_view.py 原地刷新成进度条，不刷屏。
      {
        last=""
        while true; do
          state=$(remote "tail -n 1 /content/slatehand-state/setup-background.log 2>/dev/null; kill -0 \$(cat /content/slatehand-state/setup-background.pid 2>/dev/null) 2>/dev/null && echo __RUNNING__ || true" 2>/dev/null || true)
          line=$(printf '%s\n' "$state" | grep -v '^__RUNNING__$' | tail -n 1 || true)
          if [ -n "$line" ] && [ "$line" != "$last" ]; then echo "$line"; fi
          last=$line
          printf '%s\n' "$state" | grep -q '^__RUNNING__$' || break
          sleep 5
        done
        echo "后台搬运已结束。"
      } | python3 "$REPO/scripts/progress_view.py"
      ;;
    status)
      if ! session_running; then echo "会话 ${SESSION} 未运行。"; exit 1; fi
      remote "bash $REMOTE/default_model_providers_implement/colab/run_server.sh status; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader; echo '后台搬运：'; tail -n 3 /content/slatehand-state/setup-background.log 2>/dev/null"
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
}

main "$@"; exit $?
